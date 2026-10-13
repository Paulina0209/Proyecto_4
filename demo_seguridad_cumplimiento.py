"""Demo de SEC-02, SEC-03 y NFR-04, verificando cada criterio de aceptación.

    python demo_seguridad_cumplimiento.py              # las tres historias
    python demo_seguridad_cumplimiento.py --solo sec02 # o sec03, nfr04

No necesita internet ni OpenAI. Todo ocurre en una carpeta temporal con el
paciente sintético de las pruebas (``SINT-0001``): no toca la base real ni la
clave de cifrado del usuario. Cada paso imprime ✔ si el criterio se cumplió
y ✘ si no; al final, el número de verificaciones fallidas es el código de
salida.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import os
import secrets
import socket
import sqlite3
import ssl
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Optional

RAIZ = Path(__file__).resolve().parent
ANCHO = 78
_fallas: List[str] = []


def titulo(texto: str) -> None:
    print("\n" + "█" * ANCHO + f"\n  {texto}\n" + "█" * ANCHO)


def subtitulo(texto: str) -> None:
    print("\n" + "─" * ANCHO + f"\n{texto}\n" + "─" * ANCHO)


def verificar(condicion: bool, texto: str) -> None:
    print(f"  {'✔' if condicion else '✘'} {texto}")
    if not condicion:
        _fallas.append(texto)


def nota(texto: str) -> None:
    print(f"  ⓘ {texto}")


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _expediente_sintetico(ruta: Path):
    from historia_clinica.db import crear_conexion
    from tests.datos_sinteticos import sembrar_datos_sinteticos

    conn = crear_conexion(str(ruta))
    ids = sembrar_datos_sinteticos(conn)
    conn.commit()
    return conn, ids


# ---------------------------------------------------------------------------
# SEC-02
# ---------------------------------------------------------------------------


def demo_sec02(carpeta: Path) -> None:
    import httpx
    import uvicorn
    from fastapi.testclient import TestClient

    import patients.api as api
    from seguridad.cifrado import cifrador_configurado, esta_cifrado, respaldar_base_cifrada, restaurar_respaldo
    from seguridad.servidor_tls import construir_config, generar_certificado_local
    from seguridad.tls import ConexionInseguraError, contexto_tls_cliente, exigir_url_segura

    titulo("SEC-02 — Cifrado en tránsito y en reposo")

    subtitulo("En tránsito: la API de pacientes servida solo por TLS")
    cert, clave = generar_certificado_local(carpeta / "certs")
    print(f"  Certificado de prueba para localhost: {cert.name}")
    api.DB_PATH, api.EXPEDIENTE_PATH = carpeta / "pacientes.db", carpeta / "expediente_api.db"
    puerto = _puerto_libre()
    config = construir_config("patients.api:app", "127.0.0.1", puerto, str(cert), str(clave))
    config.log_level = "warning"
    servidor = uvicorn.Server(config)
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    try:
        for _ in range(200):
            if servidor.started:
                break
            time.sleep(0.05)
        print(f"  $ python -m seguridad.servidor_tls --cert {cert.name} --key {clave.name}  (puerto {puerto})")

        contexto = contexto_tls_cliente(str(cert))
        with socket.create_connection(("127.0.0.1", puerto), timeout=5) as crudo:
            with contexto.wrap_socket(crudo, server_hostname="localhost") as tls:
                version, cifrado = tls.version(), tls.cipher()[0]
        verificar(version in ("TLSv1.2", "TLSv1.3"), f"Conexión HTTPS negociada con {version} ({cifrado})")

        r = httpx.get(f"https://localhost:{puerto}/pacientes", params={"oncologo_id": 1}, verify=contexto)
        verificar(r.status_code == 200, f"GET https://localhost:{puerto}/pacientes -> {r.status_code}")
        verificar("strict-transport-security" in r.headers,
                  f"El navegador queda obligado a HTTPS: Strict-Transport-Security: {r.headers.get('strict-transport-security')}")

        try:
            httpx.get(f"http://localhost:{puerto}/pacientes", params={"oncologo_id": 1}, timeout=3)
            en_claro = False
        except httpx.HTTPError as exc:
            en_claro = True
            print(f"    http:// al mismo puerto -> {type(exc).__name__}: el servidor no habla en claro")
        verificar(en_claro, "Una petición en claro al servidor TLS no se atiende")

        viejo = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        viejo.check_hostname, viejo.verify_mode = False, ssl.CERT_NONE
        try:
            with contextlib.suppress(ValueError, ssl.SSLError):
                viejo.minimum_version = ssl.TLSVersion.TLSv1
                viejo.maximum_version = ssl.TLSVersion.TLSv1_1
                viejo.set_ciphers("ALL:@SECLEVEL=0")
            with socket.create_connection(("127.0.0.1", puerto), timeout=5) as crudo:
                viejo.wrap_socket(crudo, server_hostname="localhost").close()
            obsoleto_rechazado = False
        except (ssl.SSLError, ConnectionError) as exc:
            obsoleto_rechazado = True
            print(f"    Cliente con TLS 1.0/1.1 -> {type(exc).__name__}")
        verificar(obsoleto_rechazado, "Un cliente con TLS 1.0/1.1 (obsoletos) es rechazado")
    finally:
        servidor.should_exit = True
        hilo.join(timeout=5)

    with TestClient(api.app, base_url="http://testserver") as cliente:
        r = cliente.get("/pacientes", params={"oncologo_id": 1}, follow_redirects=False)
    verificar(r.status_code == 403, f"Detrás de un proxy, lo que no llegó por HTTPS -> {r.status_code}: {r.json()['detail']}")

    subtitulo("En tránsito: integraciones salientes")
    for url in ("https://www.cbioportal.org/api", "http://localhost:8042/dicom-web", "http://pacs.hospital.example/dicom-web"):
        try:
            exigir_url_segura(url, que="La integración")
            print(f"    aceptada:  {url}")
            aceptada = True
        except ConexionInseguraError:
            print(f"    rechazada: {url}")
            aceptada = False
        verificar(aceptada == (not url.startswith("http://pacs")), f"{url} -> {'aceptada' if aceptada else 'rechazada'}")
    nota("http:// solo se admite hacia la propia máquina (el Orthanc local de la demo de HC-03).")

    subtitulo("En reposo: documento clínico cifrado con AES-256-GCM (DOC-01)")
    from documentos_clinicos.carga_documentos import cargar_documento_clinico, crear_conexion, leer_contenido_documento

    conn_hc, ids = _expediente_sintetico(carpeta / "expediente_docs.db")
    contenido = b"%PDF-1.4\nInforme de patologia: carcinoma ductal infiltrante, HER2 negativo.\n%%EOF"
    doc = cargar_documento_clinico(crear_conexion(), conn_hc, ids["paciente_maria"], "patologia.pdf", contenido,
                                   "dra. Gómez", carpeta / "documentos")
    en_disco = Path(doc.ruta_almacenamiento).read_bytes()
    print(f"    Clave: {cifrador_configurado().origen}")
    print(f"    Primeros bytes en disco: {en_disco[:24]!r}...")
    verificar(esta_cifrado(en_disco) and b"carcinoma" not in en_disco, "En disco el informe no se puede leer")
    verificar(leer_contenido_documento(doc) == contenido, "Al leerlo desde el copiloto se recupera idéntico")
    conn_hc.close()

    subtitulo("En reposo: respaldo cifrado de la base de datos")
    respaldo = respaldar_base_cifrada(carpeta / "expediente_docs.db", carpeta / "expediente.db.cpc")
    verificar(b"SQLite format" not in respaldo.read_bytes()[:64] and b"SINT-0001" not in respaldo.read_bytes(),
              f"$ python -m seguridad.cifrado respaldar expediente.db {respaldo.name} -> sin datos legibles")
    restaurada = restaurar_respaldo(respaldo, carpeta / "restaurada.db")
    with contextlib.closing(sqlite3.connect(restaurada)) as c:
        verificar(c.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0] > 0, "Se restaura con la clave")


# ---------------------------------------------------------------------------
# SEC-03
# ---------------------------------------------------------------------------


def demo_sec03(carpeta: Path) -> None:
    from auditoria.models import TipoAccion
    from auditoria.registro_acceso import obtener_eventos_de_paciente
    from clinical_query import NaturalLanguageClinicalQueryService, SQLiteClinicalRepository
    from estadificacion.builder import proponer_estadificacion
    from expediente.adapters import construir_contexto_resumen_caso, obtener_hallazgos_de_paciente
    from privacidad import consentimiento_ia as sec03

    titulo("SEC-03 — Consentimiento informado para el uso de IA")
    conn, ids = _expediente_sintetico(carpeta / "expediente_sec03.db")
    pid = ids["paciente_maria"]
    servicio = NaturalLanguageClinicalQueryService(SQLiteClinicalRepository(conn))

    def probar_ia(momento: str) -> bool:
        """Corre las funciones de IA; True si todas quedaron habilitadas."""
        habilitadas = []
        for nombre, funcion in (
            ("IA-04 resumen", lambda: construir_contexto_resumen_caso(conn, pid)),
            ("DX-02 diferencial", lambda: obtener_hallazgos_de_paciente(conn, pid)),
            ("EST-01 estadificación", lambda: proponer_estadificacion(conn, pid)),
        ):
            try:
                funcion()
                habilitadas.append(True)
            except sec03.ConsentimientoIARequerido:
                habilitadas.append(False)
        respuesta = servicio.ask(str(pid), "¿Cuál es el HER2?")
        habilitadas.append("consentimiento" not in respuesta.answer)
        print(f"\n  [{momento}]")
        print(f"    Oncólogo > ¿Cuál es el HER2?\n    Asistente > {respuesta.answer}")
        print(f"    Funciones de IA habilitadas: {sum(habilitadas)} de {len(habilitadas)}")
        return all(habilitadas) if any(habilitadas) else False

    sec03.activar_consentimiento_ia(conn, 1)
    print("  La institución activa la exigencia de consentimiento (la API lo hace sola al abrir el expediente).")
    print(f"  Paciente: María Fernanda Ríos (sintético), id {pid}")

    subtitulo("AC1 — Paciente sin consentimiento: la IA no se aplica")
    estado = sec03.estado_consentimiento_ia(conn, pid)
    print(f"    Estado: {estado.etiqueta} — {estado.motivo}")
    verificar(not probar_ia("sin consentimiento") and estado.etiqueta == "pendiente",
              "Ninguna función de IA usa sus datos")

    r = sec03.registrar_consentimiento_ia(conn, 2, pid, medio="escrito", soporte="")
    verificar(not r.exito, f"Sin soporte del documento firmado no se registra: {r.motivo_rechazo}")
    r = sec03.registrar_consentimiento_ia(conn, 2, pid, medio="escrito", soporte="consentimiento-SINT-0001.pdf")
    verificar(r.exito, "Consentimiento firmado registrado (medio: escrito, soporte: consentimiento-SINT-0001.pdf)")
    verificar(probar_ia("con consentimiento"), "Con el consentimiento, la IA queda habilitada")

    subtitulo("AC2 — El paciente retira el consentimiento")
    tablas = ("consultas", "laboratorios", "imagenologia", "biomarcadores")
    contar = lambda: {t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE paciente_id = ?", (pid,)).fetchone()[0] for t in tablas}
    antes = contar()
    verificar(sec03.retirar_consentimiento_ia(conn, 2, pid).exito, "Retiro registrado")
    verificar(not probar_ia("tras el retiro"), "Las funciones de IA dejan de aplicarse")
    despues = contar()
    print(f"    Historia clínica antes: {antes}")
    print(f"    Historia clínica después: {despues}")
    verificar(antes == despues, "La historia clínica existente no se borró")

    subtitulo("Evidencia: historial de consentimientos y auditoría (AUD-01)")
    from privacidad.tratamiento_datos import historial_autorizaciones

    for a in reversed(historial_autorizaciones(conn, pid)):
        print(f"    [{a.fecha[:19]}] {a.estado.value:<9} medio={a.medio} soporte={a.evidencia_ref}")
    eventos = [e for e in obtener_eventos_de_paciente(conn, pid) if e.accion is TipoAccion.REGISTRAR_AUTORIZACION]
    verificar(len(eventos) == 2, f"{len(eventos)} eventos en la auditoría (otorgado y retirado), por el usuario que los registró")
    conn.close()


# ---------------------------------------------------------------------------
# NFR-04
# ---------------------------------------------------------------------------


def demo_nfr04(carpeta: Path) -> None:
    import json

    from auditoria.models import TipoAccion
    from auditoria.registro_acceso import registrar_acceso
    from expediente.adapters import construir_contexto_clinico
    from expediente.registro import registrar_consulta
    from ia_clinica.notes.llm_client import build_user_prompt
    from privacidad import consentimiento_ia as sec03
    from privacidad.cumplimiento import evaluar_cumplimiento
    from seguridad.models import Rol, Usuario
    from seguridad.servidor_tls import generar_certificado_local

    titulo("NFR-04 — Cumplimiento normativo (HIPAA / GDPR / norma local)")
    conn, ids = _expediente_sintetico(carpeta / "expediente_nfr04.db")
    pid = ids["paciente_maria"]
    sec03.activar_consentimiento_ia(conn, 1)

    subtitulo("AC3 — Acceso según identidad, rol y permiso")
    otro = conn.execute("SELECT id FROM pacientes WHERE id != ? LIMIT 1", (pid,)).fetchone()[0]
    for rol in (Rol.ENFERMERIA, Rol.AUDITOR, Rol.ADMINISTRADOR):
        r = sec03.registrar_consentimiento_ia(conn, 5, otro, medio="escrito", soporte="doc",
                                              usuario=Usuario(5, rol.value, rol, True))
        print(f"    {rol.value:<15} registra un consentimiento -> {'permitido' if r.exito else 'denegado: ' + r.motivo_rechazo}")
        verificar(r.exito == (rol is Rol.ENFERMERIA), f"Rol {rol.value} tratado según su permiso")

    subtitulo("AC4 — Trazabilidad que no se puede alterar")
    registrar_acceso(conn, 1, TipoAccion.VER, paciente_id=pid, detalle="Demo NFR-04")
    try:
        conn.execute("DELETE FROM eventos_acceso")
        borrado = True
    except sqlite3.IntegrityError as exc:
        borrado = False
        print(f"    DELETE FROM eventos_acceso -> {exc}")
    verificar(not borrado, "La base de datos impide borrar o modificar la auditoría")

    subtitulo("AC5 — Solo lo necesario y autorizado llega al modelo de IA")
    nota_dictada = ("María Fernanda Ríos refiere fatiga leve. Documento SINT-0001, teléfono 300 123 4567, "
                    "correo maria.rios@correo.example. Hemoglobina 11.2 g/dL.")
    consulta = registrar_consulta(conn, pid, "Control", nota_dictada)
    print(f"    Nota dictada: «{nota_dictada}»")
    try:
        construir_contexto_clinico(conn, consulta)
        autorizado = True
    except sec03.ConsentimientoIARequerido:
        autorizado = False
    verificar(not autorizado, "Sin consentimiento, no se construye contexto para la IA (autorizado)")
    sec03.registrar_consentimiento_ia(conn, 2, pid, medio="escrito", soporte="doc-1")
    prompt = json.loads(build_user_prompt(construir_contexto_clinico(conn, consulta)))
    enviado = " ".join(f["text"] for f in prompt["fragments"])
    print(f"    Lo que recibe el modelo: «{enviado}»")
    verificar(not any(t in enviado for t in ("María", "Ríos", "SINT-0001", "300 123 4567", "maria.rios")),
              "Sin nombre, documento, teléfono ni correo (necesario)")
    verificar("Hemoglobina 11.2 g/dL" in enviado, "El dato clínico llega intacto")
    conn.commit()

    subtitulo("Informe de cumplimiento (python -m privacidad.cumplimiento)")
    cert, clave = generar_certificado_local(carpeta / "certs_nfr04", dias=365)
    os.environ["COPILOTO_TLS_CERT"], os.environ["COPILOTO_TLS_KEY"] = str(cert), str(clave)
    from documentos_clinicos.carga_documentos import cargar_documento_clinico
    from documentos_clinicos.carga_documentos import crear_conexion as crear_documentos

    conn_doc = crear_documentos()
    cargar_documento_clinico(conn_doc, conn, pid, "informe.pdf", b"%PDF-1.4 informe", "dra. Gómez", carpeta / "docs_nfr04")
    informe = evaluar_cumplimiento(conn, conn, conn_doc)
    print("\n".join("  " + linea for linea in informe.a_texto().splitlines()))
    verificar({c.criterio for c in informe.controles} == {"AC1", "AC2", "AC3", "AC4", "AC5"},
              "El informe cubre los cinco criterios de aceptación")
    verificar(informe.estado_general.value == "cumple", f"Estado general: {informe.estado_general.value}")
    nota("Con la instalación real, `python -m privacidad.cumplimiento` señala lo que falte (p. ej. sin certificado TLS).")
    conn_doc.close()
    conn.close()


DEMOS = {"sec02": demo_sec02, "sec03": demo_sec03, "nfr04": demo_nfr04}


def main(argv: Optional[List[str]] = None) -> int:
    for flujo in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError):
            flujo.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(RAIZ))
    p = argparse.ArgumentParser(prog="python demo_seguridad_cumplimiento.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--solo", nargs="+", choices=list(DEMOS), help="Correr solo estas historias.")
    args = p.parse_args(argv)

    # Clave propia de la demo: no crea ni usa la del usuario.
    os.environ.setdefault("COPILOTO_CLAVE_CIFRADO", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"))
    _fallas.clear()
    with tempfile.TemporaryDirectory(prefix="copiloto_demo_seg_", ignore_cleanup_errors=True) as tmp:
        for clave in args.solo or DEMOS:
            DEMOS[clave](Path(tmp))
    titulo("FIN" + (f" — {len(_fallas)} verificación(es) fallida(s)" if _fallas else " — todos los criterios verificados"))
    for falla in _fallas:
        print(f"  ✘ {falla}")
    return len(_fallas)


if __name__ == "__main__":
    sys.exit(main())
