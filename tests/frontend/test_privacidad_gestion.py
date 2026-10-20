"""NFR-06 desde la interfaz: políticas de tratamiento de datos y solicitudes de derechos del titular (administración clínica)."""
import json

import pytest

from tests.frontend.conftest import H, iniciar_sesion

CLAVE = "Clave-Coordinacion-2026!"


@pytest.fixture()
def coordinacion(cliente, entorno, monkeypatch):
    """Una cuenta de administración clínica creada por el administrador, con la sesión iniciada."""
    monkeypatch.setenv("COPILOTO_EXPEDIENTE_DB", str(entorno.expediente_db))
    assert iniciar_sesion(cliente, "admin.demo").status_code == 200
    r = cliente.post("/api/gestion/usuarios", json={"nombre_usuario": "coord.clinica", "contrasena": CLAVE, "rol": "administrador_clinico",
                                                    "nombre_completo": "Coordinación clínica"}, headers=H)
    assert r.status_code == 200, r.text
    assert iniciar_sesion(cliente, "coord.clinica", CLAVE).status_code == 200
    return cliente


def _politica(c, **cambios):
    datos = {"codigo": "habeas_data", "nombre": "Tratamiento de datos clínicos", "jurisdiccion": "CO", "marco_normativo": "Ley 1581 de 2012",
             "finalidades": ["atencion_clinica", "asistencia_ia"], "bases_legales": ["consentimiento_informado"],
             "derechos": ["acceso", "rectificacion"], "plazo_respuesta_dias": 15, **cambios}
    return c.post("/api/gestion/privacidad/politicas", json=datos, headers=H)


def test_la_sesion_anuncia_la_pantalla_solo_a_la_administracion_clinica(coordinacion, entrar):
    assert coordinacion.get("/api/sesion").json()["configurar_privacidad"] is True
    assert entrar("dra.rios").get("/api/sesion").json()["configurar_privacidad"] is False


def test_publicar_una_politica_y_su_nueva_version(coordinacion):
    r = _politica(coordinacion)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 1 and r.json()["finalidades"][0]["codigo"] == "atencion_clinica"
    assert _politica(coordinacion, plazo_respuesta_dias=10).json()["version"] == 2
    vigentes = coordinacion.get("/api/gestion/privacidad").json()["politicas"]
    habeas = [p for p in vigentes if p["codigo"] == "habeas_data"]
    assert len(habeas) == 1 and habeas[0]["plazo_respuesta_dias"] == 10


def test_una_politica_incompleta_se_rechaza_con_el_motivo(coordinacion):
    r = _politica(coordinacion, derechos=[])
    assert r.status_code == 400 and "derechos" in r.text


def test_solicitud_de_derechos_de_punta_a_punta(coordinacion, entorno):
    import sqlite3

    _politica(coordinacion)
    with sqlite3.connect(entorno.expediente_db) as conn:
        identificacion = conn.execute("SELECT identificacion FROM pacientes ORDER BY id LIMIT 1").fetchone()[0]
    r = coordinacion.post("/api/gestion/privacidad/solicitudes", json={"identificacion": identificacion, "codigo_politica": "habeas_data",
                                                                        "tipo_derecho": "acceso", "solicitante": "La paciente",
                                                                        "descripcion": "Pide copia de sus datos."}, headers=H)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    abiertas = coordinacion.get("/api/gestion/privacidad").json()["abiertas"]
    assert [s["id"] for s in abiertas] == [sid] and abiertas[0]["identificacion"] == identificacion
    info = coordinacion.get(f"/api/gestion/privacidad/solicitudes/{sid}/informacion")
    assert info.status_code == 200 and "attachment" in info.headers["content-disposition"]
    assert json.loads(info.text)["paciente_id"]
    r = coordinacion.post(f"/api/gestion/privacidad/solicitudes/{sid}/estado", json={"estado": "atendida", "detalle": "Entregada por correo."}, headers=H)
    assert r.status_code == 200 and r.json()["estado"] == "atendida"
    datos = coordinacion.get("/api/gestion/privacidad").json()
    assert not datos["abiertas"] and datos["recientes"][0]["estado"] == "atendida"


def test_un_titular_inexistente_o_un_derecho_no_reconocido_se_explican(coordinacion):
    _politica(coordinacion)
    base = {"codigo_politica": "habeas_data", "tipo_derecho": "acceso", "solicitante": "x", "descripcion": "y"}
    r = coordinacion.post("/api/gestion/privacidad/solicitudes", json={**base, "identificacion": "NO-EXISTE"}, headers=H)
    assert r.status_code == 404 and "identificación" in r.text
    assert coordinacion.post(f"/api/gestion/privacidad/solicitudes/999/estado", json={"estado": "volando"}, headers=H).status_code == 400


@pytest.mark.parametrize("usuario", ["dra.rios", "enf.mora", "direccion", "admin.demo"])
def test_otros_roles_no_gestionan_privacidad(entrar, usuario):
    c = entrar(usuario)
    assert c.get("/api/gestion/privacidad").status_code == 403
    assert c.post("/api/gestion/privacidad/politicas", json={}, headers=H).status_code == 403


def test_escribir_exige_la_cabecera_propia(coordinacion):
    assert coordinacion.post("/api/gestion/privacidad/politicas", json={}).status_code == 403
