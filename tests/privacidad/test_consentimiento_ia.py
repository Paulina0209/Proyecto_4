"""SEC-03 — Consentimiento informado y privacidad.

AC1: dado un paciente nuevo, cuando se crea su historia clínica, el sistema
exige registrar el consentimiento informado antes de habilitar las
funciones de IA sobre sus datos.

AC2: dado que un paciente retira el consentimiento, cuando se registra el
retiro, las funciones de IA dejan de aplicarse a su historia clínica, sin
borrar la historia existente.
"""
from __future__ import annotations

import json

import pytest

from auditoria.models import TipoAccion
from auditoria.registro_acceso import obtener_eventos_de_paciente
from clinical_query import NaturalLanguageClinicalQueryService, SQLiteClinicalRepository
from estadificacion.builder import proponer_estadificacion
from expediente.adapters import (
    construir_contexto_clinico,
    construir_contexto_resumen_caso,
    obtener_hallazgos_de_paciente,
)
from historia_clinica.db import crear_conexion
from privacidad.consentimiento_ia import (
    ConsentimientoIARequerido,
    activar_consentimiento_ia,
    consentimiento_ia_activo,
    estado_consentimiento_ia,
    exigir_consentimiento_ia,
    main,
    registrar_consentimiento_ia,
    retirar_consentimiento_ia,
)
from privacidad.tratamiento_datos import historial_autorizaciones
from tests.datos_sinteticos import sembrar_datos_sinteticos

USUARIO = 7


@pytest.fixture()
def conn():
    conexion = crear_conexion()
    yield conexion
    conexion.close()


@pytest.fixture()
def ids(conn):
    return sembrar_datos_sinteticos(conn)


@pytest.fixture()
def activo(conn, ids):
    assert activar_consentimiento_ia(conn, 1).exito
    return ids


def _otorgar(conn, pid):
    r = registrar_consentimiento_ia(conn, USUARIO, pid, medio="escrito", soporte="consentimiento-firmado-001.pdf")
    assert r.exito, r.motivo_rechazo
    return r


def _funciones_ia(conn, ids):
    """Cada función de IA sobre el paciente María. Devuelve los nombres de las que se negaron."""
    pid = ids["paciente_maria"]
    negadas = []
    for nombre, funcion in (
        ("IA-02 nota", lambda: construir_contexto_clinico(conn, ids["consulta_maria_1"])),
        ("IA-04 resumen", lambda: construir_contexto_resumen_caso(conn, pid)),
        ("DX-02 hallazgos", lambda: obtener_hallazgos_de_paciente(conn, pid)),
        ("EST-01 propuesta", lambda: proponer_estadificacion(conn, pid)),
    ):
        try:
            funcion()
        except ConsentimientoIARequerido:
            negadas.append(nombre)
    respuesta = NaturalLanguageClinicalQueryService(SQLiteClinicalRepository(conn)).ask(str(pid), "¿Cuál es el HER2?")
    if "consentimiento" in respuesta.answer:
        assert not respuesta.found and respuesta.datum is None
        negadas.append("IA-01 consulta")
    return negadas


TODAS = ["IA-02 nota", "IA-04 resumen", "DX-02 hallazgos", "EST-01 propuesta", "IA-01 consulta"]


# --- Activación ---------------------------------------------------------------


def test_sin_activar_no_se_exige(conn, ids):
    assert not consentimiento_ia_activo(conn)
    estado = estado_consentimiento_ia(conn, ids["paciente_maria"])
    assert not estado.exigido and estado.ia_habilitada and estado.etiqueta == "no exigido"
    assert _funciones_ia(conn, ids) == []


def test_activar_es_idempotente(conn):
    primera = activar_consentimiento_ia(conn, 1).registro
    segunda = activar_consentimiento_ia(conn, 1).registro
    assert primera.id == segunda.id and primera.version == 1


def test_no_se_registra_consentimiento_sin_activar(conn, ids):
    r = registrar_consentimiento_ia(conn, USUARIO, ids["paciente_maria"], medio="escrito", soporte="x")
    assert not r.exito and "activado" in r.motivo_rechazo


# --- AC1 ----------------------------------------------------------------------


def test_ac1_paciente_sin_consentimiento_no_recibe_ia(conn, activo):
    estado = estado_consentimiento_ia(conn, activo["paciente_maria"])
    assert estado.exigido and not estado.ia_habilitada and estado.etiqueta == "pendiente"
    assert _funciones_ia(conn, activo) == TODAS


def test_ac1_el_mensaje_explica_que_falta(conn, activo):
    with pytest.raises(ConsentimientoIARequerido, match="consentimiento informado"):
        exigir_consentimiento_ia(conn, activo["paciente_maria"])


def test_ac1_consentimiento_exige_evidencia(conn, activo):
    r = registrar_consentimiento_ia(conn, USUARIO, activo["paciente_maria"], medio="escrito", soporte="")
    assert not r.exito and "evidencia" in r.motivo_rechazo
    assert not estado_consentimiento_ia(conn, activo["paciente_maria"]).ia_habilitada


def test_ac1_con_consentimiento_se_habilita_la_ia(conn, activo):
    _otorgar(conn, activo["paciente_maria"])
    estado = estado_consentimiento_ia(conn, activo["paciente_maria"])
    assert estado.ia_habilitada and estado.etiqueta == "otorgada"
    assert estado.ultimo_registro.evidencia_ref == "consentimiento-firmado-001.pdf"
    assert _funciones_ia(conn, activo) == []


def test_ac1_consentimiento_de_un_paciente_no_habilita_a_otro(conn, activo):
    _otorgar(conn, activo["paciente_maria"])
    otro = conn.execute("SELECT id FROM pacientes WHERE id != ? LIMIT 1", (activo["paciente_maria"],)).fetchone()[0]
    with pytest.raises(ConsentimientoIARequerido):
        exigir_consentimiento_ia(conn, otro)


def test_ac1_paciente_que_no_otorga_queda_sin_ia(conn, activo):
    pid = activo["paciente_maria"]
    assert registrar_consentimiento_ia(conn, USUARIO, pid, medio="escrito", soporte="x", otorgado=False).exito
    estado = estado_consentimiento_ia(conn, pid)
    assert not estado.ia_habilitada and estado.etiqueta == "denegada" and "rechazó" in estado.motivo


# --- AC2 ----------------------------------------------------------------------


def _conteos(conn, pid):
    return {
        tabla: conn.execute(f"SELECT COUNT(*) FROM {tabla} WHERE paciente_id = ?", (pid,)).fetchone()[0]
        for tabla in ("consultas", "laboratorios", "imagenologia", "biomarcadores")
    }


def test_ac2_retiro_apaga_la_ia_sin_borrar_la_historia(conn, activo):
    pid = activo["paciente_maria"]
    _otorgar(conn, pid)
    antes = _conteos(conn, pid)
    assert sum(antes.values()) > 0

    r = retirar_consentimiento_ia(conn, USUARIO, pid, medio="escrito", soporte="retiro-002.pdf")
    assert r.exito, r.motivo_rechazo

    estado = estado_consentimiento_ia(conn, pid)
    assert not estado.ia_habilitada and estado.etiqueta == "revocada" and "retiró" in estado.motivo
    assert _funciones_ia(conn, activo) == TODAS
    assert _conteos(conn, pid) == antes  # la historia clínica sigue completa
    assert conn.execute("SELECT nombre FROM pacientes WHERE id = ?", (pid,)).fetchone() is not None


def test_ac2_el_consentimiento_anterior_se_conserva_como_evidencia(conn, activo):
    pid = activo["paciente_maria"]
    _otorgar(conn, pid)
    retirar_consentimiento_ia(conn, USUARIO, pid)
    assert [a.estado.value for a in historial_autorizaciones(conn, pid)] == ["revocada", "otorgada"]
    with pytest.raises(Exception, match="append-only"):
        conn.execute("DELETE FROM autorizaciones_tratamiento")


def test_ac2_no_se_retira_lo_que_no_se_otorgo(conn, activo):
    r = retirar_consentimiento_ia(conn, USUARIO, activo["paciente_maria"])
    assert not r.exito


def test_ac2_se_puede_volver_a_otorgar(conn, activo):
    pid = activo["paciente_maria"]
    _otorgar(conn, pid)
    retirar_consentimiento_ia(conn, USUARIO, pid)
    _otorgar(conn, pid)
    assert estado_consentimiento_ia(conn, pid).ia_habilitada


def test_cada_paso_queda_en_la_auditoria(conn, activo):
    pid = activo["paciente_maria"]
    _otorgar(conn, pid)
    retirar_consentimiento_ia(conn, USUARIO, pid)
    eventos = sorted(
        (e for e in obtener_eventos_de_paciente(conn, pid) if e.accion is TipoAccion.REGISTRAR_AUTORIZACION),
        key=lambda e: e.id,
    )
    assert len(eventos) == 2 and all(e.usuario_id == USUARIO for e in eventos)
    assert "otorgada" in eventos[0].detalle and "revocada" in eventos[1].detalle


# --- Agente de tratamiento (TX) ----------------------------------------------


@pytest.fixture()
def agente_sobre(conn, monkeypatch):
    import tx_clinica.tools.patients_tools as pt

    monkeypatch.setattr(pt, "obtener_conexion", lambda: conn)
    return pt


def test_agente_no_recibe_datos_sin_consentimiento(agente_sobre, conn, activo):
    pid = activo["paciente_maria"]
    salida = json.loads(agente_sobre.obtener_datos_paciente.invoke({"patient_id": pid}))
    assert salida["error"] == "consentimiento_ia_requerido"
    assert "facts_clinicos" not in salida and "diagnostico_principal" not in salida

    _otorgar(conn, pid)
    salida = json.loads(agente_sobre.obtener_datos_paciente.invoke({"patient_id": pid}))
    assert "error" not in salida and salida["diagnostico_principal"]


def test_las_tools_del_agente_comparten_el_control(agente_sobre, activo):
    from tx_clinica.tools.patients_tools import ERRORES_PACIENTE, ErrorConsentimientoIA

    resuelto = agente_sobre.obtener_paciente_o_error(activo["paciente_maria"])
    assert isinstance(resuelto, ErrorConsentimientoIA) and isinstance(resuelto, ERRORES_PACIENTE)


# --- API HTTP -----------------------------------------------------------------

ONC = {"oncologo_id": 1}
NUEVO = {
    "nombre_completo": "Ana Torres",
    "fecha_nacimiento": "1980-05-01",
    "sexo": "femenino",
    "tipo_identificacion": "cedula",
    "numero_identificacion": "52000123",
    "contacto": {"telefono": "3001234567"},
    "oncologo_id": 1,
    "antecedentes": {},
    "motivo_consulta_inicial": "Nódulo mamario",
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import patients.api as api

    monkeypatch.setattr(api, "DB_PATH", tmp_path / "pacientes.db")
    monkeypatch.setattr(api, "EXPEDIENTE_PATH", tmp_path / "expediente.db")
    with TestClient(api.app, base_url="https://testserver") as c:
        yield c


def test_api_paciente_nuevo_queda_pendiente_y_sin_ia(client, tmp_path):
    r = client.post("/pacientes", json=NUEVO)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    estado = client.get(f"/pacientes/{pid}/consentimiento-ia", params=ONC).json()
    assert estado["estado"] == "pendiente" and estado["exigido"] and not estado["ia_habilitada"]

    # Al registrarle un dato entra al expediente, pero la IA sigue cerrada.
    lab = {"identificacion": "52000123", "nombre": "Ana Torres", "prueba": "Hemoglobina", "valor": "12.5",
           "unidad": "g/dL", "fecha": "2026-03-10", "hora": "07:30"}
    assert client.post(f"/pacientes/{pid}/laboratorios", params=ONC, json=lab).status_code == 201
    conn_exp = crear_conexion(str(tmp_path / "expediente.db"))
    exp_id = conn_exp.execute("SELECT id FROM pacientes WHERE identificacion = '52000123'").fetchone()[0]
    with pytest.raises(ConsentimientoIARequerido):
        obtener_hallazgos_de_paciente(conn_exp, exp_id)
    conn_exp.close()


def test_api_otorgar_y_retirar(client, tmp_path):
    pid = client.post("/pacientes", json=NUEVO).json()["id"]

    sin_soporte = client.post(f"/pacientes/{pid}/consentimiento-ia", params=ONC, json={"medio": "escrito", "soporte": ""})
    assert sin_soporte.status_code == 400

    r = client.post(f"/pacientes/{pid}/consentimiento-ia", params=ONC,
                    json={"medio": "escrito", "soporte": "consentimiento-52000123.pdf"})
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "otorgada" and r.json()["ia_habilitada"]
    assert r.json()["soporte"] == "consentimiento-52000123.pdf"

    r = client.post(f"/pacientes/{pid}/consentimiento-ia/retiro", params=ONC, json={})
    assert r.status_code == 200 and r.json()["estado"] == "revocada" and not r.json()["ia_habilitada"]

    # El paciente y su historia siguen ahí.
    assert client.get(f"/pacientes/{pid}", params=ONC).status_code == 200


def test_api_solo_el_oncologo_del_paciente(client):
    pid = client.post("/pacientes", json=NUEVO).json()["id"]
    r = client.post(f"/pacientes/{pid}/consentimiento-ia", params={"oncologo_id": 99},
                    json={"medio": "escrito", "soporte": "x"})
    assert r.status_code == 404


def test_api_retiro_sin_historia_responde_404(client):
    pid = client.post("/pacientes", json=NUEVO).json()["id"]
    assert client.post(f"/pacientes/{pid}/consentimiento-ia/retiro", params=ONC, json={}).status_code == 404


# --- Línea de comandos --------------------------------------------------------


def test_cli_otorgar_estado_retirar(tmp_path, monkeypatch, capsys):
    ruta = tmp_path / "expediente.db"
    monkeypatch.setenv("COPILOTO_EXPEDIENTE_DB", str(ruta))
    conexion = crear_conexion(str(ruta))
    pid = sembrar_datos_sinteticos(conexion)["paciente_maria"]
    conexion.commit()
    conexion.close()

    assert main(["activar"]) == 0
    assert main(["estado", str(pid)]) == 0
    assert "pendiente" in capsys.readouterr().out
    assert main(["otorgar", str(pid), "--medio", "escrito", "--soporte", "doc-1"]) == 0
    assert main(["estado", str(pid)]) == 0
    assert "otorgada" in capsys.readouterr().out
    assert main(["retirar", str(pid)]) == 0
    assert main(["retirar", str(pid)]) == 1  # ya no hay nada otorgado que retirar
