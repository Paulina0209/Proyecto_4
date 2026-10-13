"""Demo guiada de HC-02 (laboratorios) y HC-04 (biopsias y biomarcadores).

    python demo_laboratorios_biomarcadores.py              # recorrido con pausas + menú interactivo
    python demo_laboratorios_biomarcadores.py --sin-pausa  # recorrido de corrido
    python demo_laboratorios_biomarcadores.py --solo-auto  # solo el recorrido, sin menú al final
    python demo_laboratorios_biomarcadores.py --sin-ia     # sin la pregunta al agente de TX (GPT)

Qué hace:

    1. Copia la base real (data/copiloto.db y patients/db/pacientes.db) a una
       carpeta temporal y levanta la API de pacientes sobre esa copia: no hace
       falta correr uvicorn aparte y la base real no se modifica.
    2. Ejecuta automáticamente el recorrido de las dos historias, criterio por
       criterio, mostrando lo mismo que se ve en la demo de pacientes y
       verificando cada resultado (CUMPLE / NO CUMPLE).
    3. Abre el menú de la demo de pacientes (python -m patients.demo) sobre la
       misma copia, con todo lo anterior ya cargado, para seguir interactuando.

Requiere la base real preparada (python demo.py --solo pac la crea la primera
vez) con los pacientes de la demo: P-0016350 (EGFR L858R) y P-0008538 (CEA).
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from patients.demo import negrita, resaltar_error, resaltar_ok

RAIZ = Path(__file__).resolve().parent
SALIDA = Path(tempfile.gettempdir()) / "copiloto_demo_hc02_hc04"
ONCOLOGO = {"oncologo_id": 1}
PACIENTE_EGFR = "P-0016350"   # pulmón metastásico, EGFR L858R importado (pendiente)
PACIENTE_CEA = "P-0008538"    # mama IV, series largas de CEA y CA 15-3

# Se completan en preparar().
BASE_URL = ""
#: Certificado autofirmado de la API de la demo (SEC-02); lo crea ``preparar``.
CERTIFICADO: Any = True
PAUSAR = True
verificaciones: list[tuple[str, bool]] = []


# ---------------------------------------------------------------------------
# Presentación
# ---------------------------------------------------------------------------

def titulo(texto: str) -> None:
    print("\n" + "═" * 78)
    print(f"  {negrita(texto)}")
    print("═" * 78)


def paso(codigo: str, texto: str) -> None:
    print("\n" + "─" * 78)
    print(f"{negrita(codigo)} — {texto}")
    print("─" * 78)


def accion(texto: str) -> None:
    print(f"  {negrita('El oncólogo:')} {texto}")


def nota(texto: str) -> None:
    print(f"  {negrita('Nota:')} {texto}")


def resultado(ok: bool) -> str:
    return resaltar_ok("CUMPLE") if ok else resaltar_error("NO CUMPLE")


def verificar(criterio: str, ok: bool, detalle: str) -> None:
    verificaciones.append((criterio, ok))
    print(f"  {resultado(ok)}  {criterio}: {detalle}")


def pausa() -> None:
    if PAUSAR:
        input("\n  [Enter para continuar] ")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def api(metodo: str, ruta: str, json: Optional[dict] = None, **params: Any) -> requests.Response:
    return requests.request(metodo, f"{BASE_URL}{ruta}", params={**ONCOLOGO, **params}, json=json, timeout=60,
                            verify=CERTIFICADO)


def paciente_id(identificacion: str) -> int:
    items = api("GET", "/pacientes/buscar", nombre=identificacion).json()["items"]
    if not items:
        raise SystemExit(f"{identificacion} no está en la base. Prepárela una vez con: python demo.py --solo pac")
    return items[0]["id"]


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def restablecer_estado_inicial(ruta_expediente: Path) -> int:
    """Deja la COPIA como recién importada de cBioPortal: descarta lo que se
    registró a mano o por HL7 (laboratorios, alertas, conflictos, biopsias,
    biomarcadores y variables de TX) y vuelve a "pendiente" los biomarcadores
    importados que se habían confirmado o descartado. Así la demo muestra
    siempre lo mismo aunque antes se haya probado la demo de pacientes.
    Nunca se llama sobre la base real. Devuelve cuántas filas cambió."""
    import sqlite3

    conn = sqlite3.connect(ruta_expediente)
    cambios = 0
    try:
        labs = "SELECT laboratorio_id FROM recepcion_laboratorio WHERE origen != 'cbioportal'"
        for sql in (
            f"DELETE FROM alertas_laboratorio WHERE laboratorio_id IN ({labs})",
            f"DELETE FROM conflictos_laboratorio WHERE laboratorio_a_id IN ({labs}) OR laboratorio_b_id IN ({labs})",
            f"DELETE FROM registros_importados WHERE tabla_destino = 'laboratorios' AND fila_id IN ({labs})",
            f"DELETE FROM laboratorios WHERE id IN ({labs})",
            "DELETE FROM recepcion_laboratorio WHERE origen != 'cbioportal'",
            "UPDATE alertas_laboratorio SET estado = 'activa', revisada_por = NULL, fecha_revision = NULL "
            "WHERE estado != 'activa'",
            "UPDATE conflictos_laboratorio SET estado = 'pendiente', resolucion = NULL, resuelto_por = NULL, "
            "fecha_resolucion = NULL, nota = NULL WHERE estado != 'pendiente'",
            "DELETE FROM biomarcadores WHERE id IN (SELECT biomarcador_id FROM detalle_biomarcador WHERE origen = 'manual')",
            "DELETE FROM detalle_biomarcador WHERE origen = 'manual'",
            "UPDATE detalle_biomarcador SET relevancia = 'pendiente_confirmacion', confirmado_por = NULL, "
            "fecha_confirmacion = NULL WHERE origen = 'importado' AND relevancia != 'pendiente_confirmacion'",
            "DELETE FROM biopsias WHERE origen = 'manual'",
            "DELETE FROM episodios_diagnosticos WHERE origen = 'manual' "
            "AND id NOT IN (SELECT episodio_id FROM biopsias)",
            # Variables de TX registradas a mano (confirmación de biomarcadores,
            # agente de TX): las importadas están en registros_importados.
            "DELETE FROM datos_clinicos_estructurados WHERE id NOT IN "
            "(SELECT fila_id FROM registros_importados WHERE tabla_destino = 'datos_clinicos_estructurados')",
        ):
            cambios += conn.execute(sql).rowcount
        conn.commit()
    finally:
        conn.close()
    return cambios


def preparar() -> int:
    """Copia la base real, la deja en su estado inicial y levanta la API
    sobre la copia. Devuelve cuántos cambios manuales se descartaron."""
    global BASE_URL, CERTIFICADO
    origen_exp, origen_pac = RAIZ / "data" / "copiloto.db", RAIZ / "patients" / "db" / "pacientes.db"
    if not origen_exp.is_file() or not origen_pac.is_file():
        raise SystemExit("Falta la base real. Prepárela una vez (necesita internet) con: python demo.py --solo pac")
    if SALIDA.exists():
        shutil.rmtree(SALIDA)
    SALIDA.mkdir(parents=True)
    copia_exp, copia_pac = SALIDA / "copiloto.db", SALIDA / "pacientes.db"
    shutil.copyfile(origen_exp, copia_exp)
    shutil.copyfile(origen_pac, copia_pac)
    descartados = restablecer_estado_inicial(copia_exp)
    # Todo lo que abra "el expediente" (API, carga de detalle, agente de TX) usa la copia.
    os.environ["COPILOTO_EXPEDIENTE_DB"] = str(copia_exp)

    import uvicorn

    import patients.api as api_pacientes
    from seguridad.servidor_tls import construir_config, generar_certificado_local

    api_pacientes.DB_PATH, api_pacientes.EXPEDIENTE_PATH = copia_pac, copia_exp
    puerto = _puerto_libre()
    # SEC-02: la API solo atiende HTTPS; la demo usa un certificado autofirmado propio.
    cert, clave = generar_certificado_local(SALIDA / "certs")
    CERTIFICADO = str(cert)
    BASE_URL = f"https://127.0.0.1:{puerto}"
    config = construir_config(api_pacientes.app, "127.0.0.1", puerto, str(cert), str(clave))
    config.log_level = "warning"
    servidor = uvicorn.Server(config)
    threading.Thread(target=servidor.run, daemon=True).start()
    for _ in range(150):
        try:
            requests.get(f"{BASE_URL}/docs", timeout=1, verify=CERTIFICADO)
            break
        except requests.ConnectionError:
            time.sleep(0.2)
    else:
        raise SystemExit("La API de la demo no arrancó.")
    return descartados


def facts_tx(identificacion: str) -> dict[str, Any]:
    """Lo que TX-01 lee del expediente (copia) para ese paciente."""
    from historia_clinica.db import crear_conexion
    from tx_clinica.patient_facts import construir_facts_paciente

    conn = crear_conexion(os.environ["COPILOTO_EXPEDIENTE_DB"])
    try:
        pid = conn.execute("SELECT id FROM pacientes WHERE identificacion LIKE ?", (f"%{identificacion}",)).fetchone()[0]
        return construir_facts_paciente(conn, pid)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Recorrido HC-02
# ---------------------------------------------------------------------------

def recorrido_hc02(demo: Any, p: int, p_cea: int) -> None:
    hoy = date.today().isoformat()
    lab = {"identificacion": PACIENTE_EGFR, "nombre": f"Paciente {PACIENTE_EGFR}", "prueba": "Potasio", "valor": "7.1",
           "unidad": "mmol/L", "fecha": hoy, "hora": "07:30", "rango_referencia": "3.5-5.1"}

    titulo("HC-02 — Integración de resultados de laboratorio")
    paso("Punto de partida", f"Resumen 360 de {PACIENTE_EGFR} (id {p}): todavía sin laboratorios")
    demo.mostrar_resumen_360(api("GET", f"/pacientes/{p}/resumen-360").json())
    pausa()

    paso("HC-02 · AC1 + AC2", "Llega un resultado: se asocia al paciente y a su fecha; si es crítico, alerta")
    accion(f"registra Potasio 7.1 mmol/L, hoy 07:30, con la orden de '{PACIENTE_EGFR}' / 'Paciente {PACIENTE_EGFR}'")
    r = api("POST", f"/pacientes/{p}/laboratorios", json=lab)
    cuerpo = r.json()
    punto = api("GET", f"/pacientes/{p}/laboratorios/tendencia", prueba="potasio").json()["series"][0]["puntos"][0]
    verificar("AC1 paciente y fecha correctos", r.status_code == 201 and punto["fecha_hora"] == f"{hoy}T07:30",
              f"guardado en el paciente {p}, toma {punto['fecha_hora'].replace('T', ' ')}")
    verificar("AC2 valor crítico genera alerta", bool(cuerpo.get("alerta")),
              cuerpo["alerta"]["limite_superado"] if cuerpo.get("alerta") else "sin alerta")
    pausa()

    paso("HC-02 · Riesgo", "Doble validación: identificación + nombre")
    accion("registra un resultado con la identificación correcta pero el nombre 'Juan Perez'")
    r = api("POST", f"/pacientes/{p}/laboratorios", json={**lab, "nombre": "Juan Perez", "valor": "4.0", "hora": "09:00"})
    print(f"  {resaltar_error('RECHAZADO:')} {r.json()['detail']['errores'][0]['mensaje']}")
    n = len(api("GET", f"/pacientes/{p}/laboratorios/tendencia", prueba="potasio").json()["series"][0]["puntos"])
    verificar("Doble validación", r.status_code == 409 and n == 1, f"rechazado ({r.status_code}); sigue habiendo {n} resultado")
    pausa()

    paso("HC-02 · AC1 (interfaz de laboratorio)", "Llega un mensaje HL7 ORU^R01 desde el LIS")
    fecha_hl7 = hoy.replace("-", "")
    hl7 = "\r".join([
        f"MSH|^~\\&|LIS|HOSP|COPILOTO|ONCO|{fecha_hl7}080000||ORU^R01|DEMO-{int(time.time())}|P|2.5",
        f"PID|1||CBIO:msk_chord_2024:{PACIENTE_EGFR}^^^HOSP||{PACIENTE_EGFR}^Paciente||19700101|M",
        f"OBR|1|||CBC^Hemograma|||{fecha_hl7}0700",
        "OBX|1|NM|777-3^Plaquetas||15|10\\S\\3/uL|150-450|LL|||F",
    ])
    for linea in hl7.split("\r"):
        print(f"    {linea}")
    r = api("POST", f"/pacientes/{p}/laboratorios/hl7", json={"mensaje": hl7})
    verificar("AC1 por interfaz HL7", r.status_code == 200 and r.json().get("registros_importados") == 1,
              r.json().get("mensaje", r.text)[:120])
    pausa()

    paso("HC-02 · AC3", "Mismo marcador y mismo momento con otro valor: no se sobrescribe, se marca conflicto")
    accion("registra 'K' 4.4 mmol/L, hoy 07:30 (el mismo momento que el potasio 7.1)")
    r = api("POST", f"/pacientes/{p}/laboratorios", json={**lab, "prueba": "K", "valor": "4.4"})
    conflictos = r.json().get("conflictos") or []
    tendencia = api("GET", f"/pacientes/{p}/laboratorios/tendencia", prueba="potasio").json()
    demo.mostrar_tendencia(tendencia)
    valores = sorted(pt["valor"] for pt in tendencia["series"][0]["puntos"])
    verificar("AC3 no se sobrescribe y se marca el conflicto", valores == ["4.4", "7.1"] and bool(conflictos),
              f"se conservan {valores}; conflicto C{conflictos[0]['id'] if conflictos else '?'} pendiente de revisión")
    pausa()

    paso("HC-02 · AC2 + AC3 en el dashboard", "Resumen 360: las alertas quedan visibles")
    resumen = api("GET", f"/pacientes/{p}/resumen-360").json()
    demo.mostrar_resumen_360(resumen)
    tipos = [a["tipo"] for a in resumen["alertas_activas"]]
    verificar("AC2 alerta visible en el dashboard", tipos.count("laboratorio_critico") == 2,
              "potasio 7.1 y plaquetas 15 como [ALTA] Laboratorio crítico")
    verificar("AC3 conflicto visible para revisión", "conflicto_laboratorio" in tipos, "[MEDIA] Conflicto de laboratorio")
    pausa()

    paso("HC-02 · Revisión", "El oncólogo revisa la alerta y resuelve el conflicto (nada se borra)")
    alerta = next(a for a in api("GET", f"/pacientes/{p}/alertas-laboratorio").json() if a["prueba"] == "Potasio")
    accion(f"marca la alerta A{alerta['id']} como revisada")
    api("POST", f"/pacientes/{p}/alertas-laboratorio/{alerta['id']}/revisar", json={"revisada_por": "dra.ruiz"})
    if conflictos:
        accion(f"resuelve el conflicto C{conflictos[0]['id']}: válido el primero (la muestra B estaba hemolizada)")
        api("POST", f"/pacientes/{p}/conflictos-laboratorio/{conflictos[0]['id']}/resolver",
            json={"resolucion": "valido_a", "resuelto_por": "dra.ruiz", "nota": "Muestra B hemolizada"})
    n = len(api("GET", f"/pacientes/{p}/laboratorios/tendencia", prueba="potasio").json()["series"][0]["puntos"])
    verificar("Revisión sin borrar datos", n == 2, f"alerta revisada, conflicto resuelto y siguen los {n} resultados")
    pausa()

    paso("HC-02 · Tendencias", f"Serie histórica de CEA de {PACIENTE_CEA} (datos reales de cBioPortal)")
    tendencia = api("GET", f"/pacientes/{p_cea}/laboratorios/tendencia", prueba="CEA").json()
    puntos = tendencia["series"][0]["puntos"] if tendencia["series"] else []
    demo.mostrar_tendencia({**tendencia, "series": [{**s, "puntos": s["puntos"][-15:]} for s in tendencia["series"]]})
    nota(f"Se muestran los últimos 15 de {len(puntos)} resultados. Los marcados 'en conflicto' son dos valores "
         "distintos del mismo día en cBioPortal (sin hora, no se puede descartar que sean del mismo momento).")
    verificar("Tendencia por marcador", len(puntos) > 10, f"{len(puntos)} resultados de CEA")
    pausa()


# ---------------------------------------------------------------------------
# Recorrido HC-04
# ---------------------------------------------------------------------------

def recorrido_hc04(demo: Any, p: int) -> None:
    hoy = date.today().isoformat()
    titulo("HC-04 — Integración de biopsias y biomarcadores")

    paso("HC-04 · AC1", "La biopsia queda vinculada a su episodio diagnóstico")
    biopsias = api("GET", f"/pacientes/{p}/biopsias").json()
    biomarcadores = api("GET", f"/pacientes/{p}/biomarcadores").json()
    episodios = api("GET", f"/pacientes/{p}/episodios").json()
    for b in biopsias:
        print(f"    #{b['id']:<4} {b['fecha']}  {b['sitio']} · {b['procedimiento']} (episodio {b['episodio_id']})")
    demo._mostrar_biomarcadores(biomarcadores)
    accion("registra una biopsia nueva sin indicar el episodio (el paciente tiene uno solo)")
    r = api("POST", f"/pacientes/{p}/biopsias", json={"fecha": hoy, "sitio": "Ganglio supraclavicular",
                                                     "procedimiento": "Biopsia con aguja gruesa",
                                                     "diagnostico_histologico": "Adenocarcinoma"})
    nueva = r.json()
    verificar("AC1 biopsia importada vinculada", bool(biopsias) and biopsias[0]["episodio_id"] == episodios[0]["id"],
              f"biopsia #{biopsias[0]['id']} → episodio {episodios[0]['id']} ({episodios[0]['descripcion']})")
    verificar("AC1 biopsia nueva vinculada al guardarla", r.status_code == 201 and nueva.get("episodio_id") == episodios[0]["id"],
              f"biopsia #{nueva.get('id')} → episodio {nueva.get('episodio_id')}")
    pausa()

    paso("HC-04 · AC2", "Biomarcador accionable: información clave e insumo de TX-01")
    egfr = next(b for b in biomarcadores if b["biomarcador"] == "EGFR")
    antes = facts_tx(PACIENTE_EGFR).get("egfr_status")
    nota(f"EGFR {egfr['variante']} viene de cBioPortal: se destaca como pendiente y TX-01 todavía no lo usa "
         f"(egfr_status = {antes}).")
    accion(f"confirma el biomarcador #{egfr['biomarcador_id']} escribiendo 'detectada'")
    r = api("POST", f"/pacientes/{p}/biomarcadores/{egfr['biomarcador_id']}/confirmar",
            json={"confirmado_por": "dra.ruiz", "confirmacion": "detectada"})
    despues = facts_tx(PACIENTE_EGFR).get("egfr_status")
    demo._mostrar_biomarcadores(api("GET", f"/pacientes/{p}/biomarcadores").json())
    verificar("AC2 destacado como información clave", r.status_code == 200 and r.json()["relevancia"] == "accionable_confirmado",
              f"ACCIONABLE · {r.json().get('terapia_asociada')}")
    verificar("AC2 insumo de TX-01", antes is None and despues == "sensitizing_mutation",
              f"egfr_status: {antes} → {despues}")

    accion("registra PD-L1 TPS 60 % (22C3) en la biopsia nueva, escribiendo 60 dos veces")
    r = api("POST", f"/pacientes/{p}/biomarcadores", json={"biopsia_id": nueva.get("id"), "biomarcador": "PD-L1",
            "estado": "cuantificado", "confirmacion": "60", "metodo": "22C3", "valor": 60})
    verificar("AC2 registro manual accionable", r.status_code == 201 and facts_tx(PACIENTE_EGFR).get("pdl1_tps") == 60,
              "TX-01 recibe pdl1_tps=60")
    pausa()

    paso("HC-04 · Riesgo", "Validación estricta del formato (un resultado invertido no se puede guardar)")
    intentos = {
        "HER2 'negativo' con IHC 3+": {"biomarcador": "HER2", "estado": "negativo", "confirmacion": "negativo",
                                      "metodo": "IHC", "ihc_score": "3+"},
        "confirmación distinta": {"biomarcador": "EGFR", "estado": "detectada", "confirmacion": "no_detectada",
                                  "metodo": "NGS", "variante": "L858R"},
        "texto libre en el estado": {"biomarcador": "EGFR", "estado": "levemente positivo",
                                     "confirmacion": "levemente positivo", "metodo": "NGS"},
        "PD-L1 de 120 %": {"biomarcador": "PD-L1", "estado": "cuantificado", "confirmacion": "120",
                           "metodo": "22C3", "valor": 120},
    }
    total_antes = len(api("GET", f"/pacientes/{p}/biomarcadores").json())
    todos_rechazados = True
    for nombre, datos in intentos.items():
        r = api("POST", f"/pacientes/{p}/biomarcadores", json={"biopsia_id": nueva.get("id"), **datos})
        todos_rechazados &= r.status_code == 400
        mensaje = r.json()["detail"]["errores"][0]["mensaje"] if r.status_code == 400 else r.text[:80]
        print(f"    {resaltar_error('RECHAZADO')} {nombre}: {mensaje}")
    total_despues = len(api("GET", f"/pacientes/{p}/biomarcadores").json())
    verificar("Validación estricta", todos_rechazados and total_antes == total_despues, "los 4 se rechazan y no se guarda nada")
    pausa()

    paso("Resultado", f"Resumen 360 final de {PACIENTE_EGFR}")
    resumen = api("GET", f"/pacientes/{p}/resumen-360").json()
    demo.mostrar_resumen_360(resumen)
    clave = {b["biomarcador"]: b["confirmado"] for b in resumen["biomarcadores_clave"]}
    verificar("360 con la información clave", clave.get("EGFR") is True and "PD-L1 TPS" in clave,
              "EGFR y PD-L1 TPS CONFIRMADOS en Biomarcadores clave")
    pausa()


def pregunta_al_agente(sin_ia: bool) -> None:
    """TX-01 recibe el biomarcador confirmado: se lo pregunta al agente (GPT)."""
    paso("HC-04 · AC2 (desde TX-01)", "El agente de tratamiento usa el biomarcador confirmado")
    if sin_ia:
        nota("Omitido (--sin-ia).")
        return
    from core import llm_config

    if not llm_config.obtener_api_key():
        nota("Omitido: no hay OPENAI_API_KEY en el .env.")
        return
    from tx_clinica.agent import construir_agente
    from tx_clinica.conversacion import enviar_mensaje
    from tx_clinica.observability import vaciar_langfuse
    from tx_clinica.tools._db import obtener_conexion

    pid = obtener_conexion().execute(
        "SELECT id FROM pacientes WHERE identificacion LIKE ?", (f"%{PACIENTE_EGFR}",)).fetchone()[0]
    pregunta = f"¿Qué biomarcadores clave tiene el paciente {pid} y están confirmados? Responde en dos frases."
    print(f"  Oncólogo > {pregunta}")
    inicio = time.monotonic()
    try:
        respuesta = enviar_mensaje(construir_agente(), pregunta, f"demo-hc04-{int(time.time())}", oncologo_id=1)
        print(f"  Agente ({llm_config.obtener_modelo()}, {time.monotonic() - inicio:.0f} s) > {respuesta.texto}")
        verificar("TX-01 recibe el biomarcador confirmado", "confirm" in (respuesta.texto or "").lower(),
                  "el agente lo reporta como confirmado")
    except Exception as exc:  # noqa: BLE001 -- la demo sigue aunque falle la red
        nota(f"No se pudo consultar al agente: {type(exc).__name__}: {exc}")
    finally:
        vaciar_langfuse()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    global PAUSAR
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sin-pausa", action="store_true", help="No esperar Enter entre pasos.")
    parser.add_argument("--solo-auto", action="store_true", help="Solo el recorrido automático, sin menú al final.")
    parser.add_argument("--sin-ia", action="store_true", help="No preguntarle al agente de TX (no usa OpenAI).")
    args = parser.parse_args(argv)
    PAUSAR = not args.sin_pausa
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    if os.name == "nt":
        os.system("")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    titulo("Demo guiada · HC-02 laboratorios · HC-04 biopsias y biomarcadores")
    print("  Preparando una copia de la base real y la API de la demo...", flush=True)
    descartados = preparar()
    print(f"  API de la demo: {BASE_URL}  ·  copia de trabajo: {SALIDA}")
    print("  La base real (data/copiloto.db, patients/db/pacientes.db) no se modifica.")
    if descartados:
        print(f"  La copia parte del estado recién importado de cBioPortal: se descartaron {descartados} "
              "registro(s) manuales de pruebas anteriores.")

    import patients.demo as demo

    demo.BASE_URL, demo.VERIFICAR_TLS = BASE_URL, CERTIFICADO
    p, p_cea = paciente_id(PACIENTE_EGFR), paciente_id(PACIENTE_CEA)
    pausa()

    recorrido_hc02(demo, p, p_cea)
    recorrido_hc04(demo, p)
    pregunta_al_agente(args.sin_ia)

    titulo("Resumen de criterios de aceptación")
    for criterio, ok in verificaciones:
        print(f"  {resultado(ok)}  {criterio}")
    cumplen = sum(ok for _, ok in verificaciones)
    print(f"\n  {cumplen}/{len(verificaciones)} verificaciones cumplen.")

    if args.solo_auto:
        return 0 if cumplen == len(verificaciones) else 1

    titulo("Ahora puede usar el sistema como en la demo de pacientes")
    print(f"  Todo lo anterior quedó cargado en la copia (paciente {PACIENTE_EGFR} = id {p}, "
          f"{PACIENTE_CEA} = id {p_cea}).")
    print("  Pruebe, por ejemplo: opción 5 → registrar otro resultado (R), opción 6 → revisar la alerta de plaquetas,")
    print("  opción 7 → registrar una biopsia (B) o un biomarcador (M), opción 4 → ver el 360.")
    demo.main()
    print(f"\n  La copia de trabajo queda en {SALIDA}; la base real no se modificó.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
