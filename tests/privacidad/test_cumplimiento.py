"""NFR-04 — Cumplimiento normativo: un test por criterio de aceptación, más el informe."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from auditoria.models import TipoAccion
from auditoria.registro_acceso import inicializar_schema, registrar_acceso
from historia_clinica.db import crear_conexion
from privacidad import cumplimiento
from privacidad.consentimiento_ia import (
    activar_consentimiento_ia,
    registrar_consentimiento_ia,
    retirar_consentimiento_ia,
)
from privacidad.cumplimiento import Estado, evaluar_cumplimiento
from privacidad.minimizacion import (
    MARCADOR_CORREO,
    MARCADOR_DOCUMENTO,
    MARCADOR_PACIENTE,
    MARCADOR_TELEFONO,
    quitar_identificadores,
    seudonimizar_texto,
)
from seguridad.autorizacion import Accion, verificar_permiso
from seguridad.models import Rol, Usuario
from tests.datos_sinteticos import sembrar_datos_sinteticos


def _usuario(rol: Rol) -> Usuario:
    return Usuario(id=5, nombre_usuario=rol.value, rol=rol, activo=True)


# --- AC3: acceso según identidad, rol y permiso ---------------------------------


@pytest.mark.parametrize(
    ("rol", "puede"),
    [(Rol.ONCOLOGO, True), (Rol.ENFERMERIA, True), (Rol.ADMINISTRATIVO, True), (Rol.AUDITOR, False), (Rol.ADMINISTRADOR, False)],
)
def test_ac3_registrar_consentimiento_segun_rol(rol, puede):
    conn = crear_conexion()
    pid = sembrar_datos_sinteticos(conn)["paciente_maria"]
    activar_consentimiento_ia(conn, 1)
    r = registrar_consentimiento_ia(conn, 5, pid, medio="escrito", soporte="doc", usuario=_usuario(rol))
    assert r.exito is puede
    if not puede:
        assert "no tiene permiso" in r.motivo_rechazo
        r = retirar_consentimiento_ia(conn, 5, pid, usuario=_usuario(rol))
        assert not r.exito and "no tiene permiso" in r.motivo_rechazo


def test_ac3_solo_el_administrador_clinico_configura_la_politica():
    conn = crear_conexion()
    assert not activar_consentimiento_ia(conn, 1, usuario=_usuario(Rol.ONCOLOGO)).exito
    assert activar_consentimiento_ia(conn, 1, usuario=_usuario(Rol.ADMINISTRADOR_CLINICO)).exito


def test_ac3_usuario_inactivo_no_registra():
    inactivo = Usuario(id=5, nombre_usuario="x", rol=Rol.ONCOLOGO, activo=False)
    assert not verificar_permiso(inactivo, Accion.REGISTRAR_CONSENTIMIENTO_IA).permitido


# --- AC4: trazabilidad de solo inserción ---------------------------------------


def test_ac4_la_auditoria_no_se_puede_modificar_ni_borrar():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    inicializar_schema(conn)
    registrar_acceso(conn, 1, TipoAccion.VER, paciente_id=3)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE eventos_acceso SET usuario_id = 2")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM eventos_acceso")
    assert conn.execute("SELECT COUNT(*) FROM eventos_acceso").fetchone()[0] == 1


# --- AC5: solo lo necesario y autorizado llega a la IA --------------------------


def test_ac5_quitar_identificadores_recursivo():
    registro = {
        "paciente_id": 7,
        "nombre": "Ana",
        "diagnostico_principal": "Cáncer de mama",
        "contacto": {"telefono": "300"},
        "biomarcadores": [{"biomarcador": "HER2", "identificacion": "123"}],
    }
    assert quitar_identificadores(registro) == {
        "paciente_id": 7,
        "diagnostico_principal": "Cáncer de mama",
        "biomarcadores": [{"biomarcador": "HER2"}],
    }


def test_ac5_seudonimizar_texto_libre():
    texto = (
        "María Fernanda Ríos acude con su hija. La señora Ríos refiere dolor. CC 52000123. "
        "Tel. +57 300 123 4567, correo maria.rios@correo.example. Hb 12.5 g/dL el 2026-01-15, CEA 3.2."
    )
    salida = seudonimizar_texto(texto, nombre="María Fernanda Ríos (sintético)", identificaciones=["52000123"])
    for identificador in ("María", "Fernanda", "Ríos", "52000123", "300 123 4567", "maria.rios"):
        assert identificador not in salida
    for marcador in (MARCADOR_PACIENTE, MARCADOR_DOCUMENTO, MARCADOR_TELEFONO, MARCADOR_CORREO):
        assert marcador in salida
    # Los datos clínicos no se tocan.
    assert "Hb 12.5 g/dL el 2026-01-15, CEA 3.2." in salida
    assert salida.startswith(f"{MARCADOR_PACIENTE} acude")


def test_ac5_id_de_cbioportal_corto_y_largo():
    salida = seudonimizar_texto("Paciente P-0016350 (CBIO:msk_chord_2024:P-0016350).",
                                identificaciones=["CBIO:msk_chord_2024:P-0016350"])
    assert "P-0016350" not in salida


def test_ac5_la_nota_y_el_resumen_salen_sin_identificadores():
    from expediente.adapters import construir_contexto_clinico, construir_contexto_resumen_caso
    from expediente.registro import registrar_consulta
    from ia_clinica.notes.llm_client import build_user_prompt as prompt_nota
    from ia_clinica.summary.llm_client import build_user_prompt as prompt_resumen

    conn = crear_conexion()
    ids = sembrar_datos_sinteticos(conn)
    pid = ids["paciente_maria"]
    consulta = registrar_consulta(conn, pid, "Control", "María Fernanda refiere fatiga. Teléfono 3001234567. Documento SINT-0001.")
    for prompt in (prompt_nota(construir_contexto_clinico(conn, consulta)),
                   prompt_resumen(construir_contexto_resumen_caso(conn, pid))):
        assert "María" not in prompt and "Fernanda" not in prompt
        assert "3001234567" not in prompt and "SINT-0001" not in prompt
    assert f"paciente-{pid}" in prompt  # el resumen referencia al paciente por su id interno


def test_ac5_el_agente_no_recibe_el_nombre(monkeypatch):
    import tx_clinica.tools.patients_tools as pt

    conn = crear_conexion()
    pid = sembrar_datos_sinteticos(conn)["paciente_maria"]
    monkeypatch.setattr(pt, "obtener_conexion", lambda: conn)
    salida = json.loads(pt.obtener_datos_paciente.invoke({"patient_id": pid}))
    assert "nombre" not in salida and "María" not in json.dumps(salida, ensure_ascii=False)
    assert salida["paciente_id"] == pid


# --- Informe de cumplimiento -----------------------------------------------------


@pytest.fixture()
def instalacion_correcta(tmp_path, monkeypatch):
    from seguridad.servidor_tls import generar_certificado_local

    cert, clave = generar_certificado_local(tmp_path / "certs", dias=365)
    monkeypatch.setenv("COPILOTO_TLS_CERT", str(cert))
    monkeypatch.setenv("COPILOTO_TLS_KEY", str(clave))
    monkeypatch.delenv("COPILOTO_PACS_URL", raising=False)
    monkeypatch.delenv("COPILOTO_VISOR_URL", raising=False)
    conn_exp = crear_conexion()
    pid = sembrar_datos_sinteticos(conn_exp)["paciente_maria"]
    activar_consentimiento_ia(conn_exp, 1)
    registrar_consentimiento_ia(conn_exp, 1, pid, medio="escrito", soporte="doc")
    inicializar_schema(conn_exp)
    return conn_exp


def _por_nombre(informe, fragmento):
    return next(c for c in informe.controles if fragmento in c.nombre)


def test_informe_de_una_instalacion_correcta(instalacion_correcta, tmp_path):
    from documentos_clinicos.carga_documentos import cargar_documento_clinico
    from documentos_clinicos.carga_documentos import crear_conexion as crear_documentos

    conn_doc = crear_documentos()
    cargar_documento_clinico(conn_doc, instalacion_correcta, 1, "a.pdf", b"%PDF-1.4 x", "dra", tmp_path / "docs")
    informe = evaluar_cumplimiento(instalacion_correcta, instalacion_correcta, conn_doc)

    assert {c.criterio for c in informe.controles} == {"AC1", "AC2", "AC3", "AC4", "AC5"}
    assert informe.estado_general is Estado.CUMPLE, informe.a_texto()
    assert "1 de" in _por_nombre(informe, "consentimiento").detalle
    datos = json.loads(informe.a_json())
    assert datos["estado_general"] == "cumple" and len(datos["controles"]) == len(informe.controles)


def test_informe_detecta_lo_que_falta(monkeypatch, tmp_path):
    monkeypatch.delenv("COPILOTO_TLS_CERT", raising=False)
    monkeypatch.setenv("COPILOTO_PACS_URL", "http://pacs.hospital.example/dicom-web")
    conn_exp = crear_conexion()  # sin consentimiento activado

    conn_doc = sqlite3.connect(":memory:")
    conn_doc.execute("CREATE TABLE documentos_clinicos_cargados (ruta_almacenamiento TEXT)")
    viejo = tmp_path / "viejo.pdf"
    viejo.write_bytes(b"%PDF-1.4 en claro")
    conn_doc.execute("INSERT INTO documentos_clinicos_cargados VALUES (?)", (str(viejo),))

    informe = evaluar_cumplimiento(conn_exp, None, conn_doc)
    assert informe.estado_general is Estado.FALLA
    assert _por_nombre(informe, "Certificado TLS").estado is Estado.FALLA
    assert _por_nombre(informe, "Integraciones").estado is Estado.FALLA
    assert _por_nombre(informe, "consentimiento").estado is Estado.FALLA
    assert _por_nombre(informe, "Documentos").estado is Estado.FALLA
    assert _por_nombre(informe, "base de pacientes").estado is Estado.ATENCION


def test_certificado_por_vencer(instalacion_correcta):
    ahora = datetime.now(timezone.utc) + timedelta(days=350)
    assert cumplimiento.control_certificado_tls(ahora).estado is Estado.ATENCION
    assert cumplimiento.control_certificado_tls(ahora + timedelta(days=30)).estado is Estado.FALLA


def test_clave_en_archivo_es_solo_para_desarrollo(monkeypatch, tmp_path):
    from seguridad import cifrado

    clave = cifrado.generar_clave()
    monkeypatch.delenv(cifrado.ENV_CLAVE, raising=False)
    ruta = tmp_path / "clave"
    ruta.write_text(clave, encoding="ascii")
    monkeypatch.setenv(cifrado.ENV_ARCHIVO_CLAVE, str(ruta))
    assert cumplimiento.control_clave_cifrado().estado is Estado.ATENCION
    monkeypatch.setenv(cifrado.ENV_CLAVE, clave)
    assert cumplimiento.control_clave_cifrado().estado is Estado.CUMPLE


def test_cli_imprime_el_informe(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("COPILOTO_EXPEDIENTE_DB", str(tmp_path / "no_existe.db"))
    codigo = cumplimiento.main(["--json"])
    datos = json.loads(capsys.readouterr().out)
    assert codigo == (1 if datos["estado_general"] == "falla" else 0)
    assert not (tmp_path / "no_existe.db").exists()  # el informe no crea bases
