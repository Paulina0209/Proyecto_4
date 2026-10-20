"""HC-06 y CFG-02 a través de la pasarela: se activan solas, con la identidad de la sesión y sus permisos."""
from __future__ import annotations

import pytest

from tests.frontend.conftest import H, LUCIA, RENATA


def test_las_capacidades_anuncian_las_dos_historias(entrar):
    ext = entrar("dra.rios").get("/api/clinica/capacidades").json()["extensiones"]

    assert ext["linea_tiempo"]["disponible"] and ext["linea_tiempo"]["ruta"] == "/pacientes/{id}/linea-tiempo"
    n = ext["notificaciones"]
    assert n["disponible"] and n["preferencias"] and n["guardar_preferencias"] and n["marcar_leida"]


def test_la_linea_de_tiempo_de_la_demo_marca_las_fechas_aproximadas(entrar):
    c = entrar("dra.rios")
    eventos = c.get(f"/api/pacientes/{LUCIA}/linea-tiempo").json()["eventos"]

    assert [e["precision"] for e in eventos[:2]] == ["anio", "mes"] and all(e["fecha_aproximada"] for e in eventos[:2])
    assert [e["fecha"] for e in eventos] == sorted(e["fecha"] for e in eventos)
    assert c.get(f"/api/pacientes/{LUCIA}/linea-tiempo?tipo=biopsia").json()["eventos"][0]["tipo"] == "biopsia"
    assert c.get(f"/api/pacientes/{RENATA}/linea-tiempo").status_code == 404


def test_la_bandeja_es_la_de_la_sesion_aunque_el_navegador_pida_otra(entrar):
    c = entrar("dra.rios")
    propias = c.get("/api/notificaciones?oncologo_id=3").json()["notificaciones"]

    assert {n["evento"] for n in propias} == {"resultado_critico", "estudio_pendiente", "interaccion_detectada"}
    assert {n["paciente"] for n in propias} <= {"Lucía Herrera Posada", "Mateo Quintero Ruiz"}
    assert entrar("dr.vega").get("/api/notificaciones").json()["notificaciones"] == []


def test_guardar_preferencias_exige_la_cabecera_propia_y_son_de_quien_inicia_sesion(entrar):
    c = entrar("dra.rios")
    cuerpo = {"preferencias": [{"evento": "resultado_critico", "activo": False, "canales": []}]}

    assert c.put("/api/notificaciones/preferencias", json=cuerpo).status_code == 403            # CSRF
    r = c.put("/api/notificaciones/preferencias?oncologo_id=3", json=cuerpo, headers=H)

    assert r.status_code == 200, r.text
    assert all(n["evento"] != "resultado_critico" for n in c.get("/api/notificaciones").json()["notificaciones"])
    assert entrar("dr.vega").get("/api/notificaciones/preferencias").json()["es_por_defecto"]


def test_marcar_leida_desde_la_interfaz(entrar):
    c = entrar("dra.rios")
    primera = c.get("/api/notificaciones").json()["notificaciones"][0]

    assert c.post(f"/api/notificaciones/{primera['id']}/leida", json={}).status_code == 403     # CSRF
    assert c.post(f"/api/notificaciones/{primera['id']}/leida", json={}, headers=H).json()["leida"]


@pytest.mark.parametrize("usuario", ["enf.mora", "direccion", "admin.demo"])
def test_los_roles_sin_pacientes_no_ven_notificaciones_ni_lineas_de_tiempo(entrar, usuario):
    c = entrar(usuario)
    assert c.get("/api/notificaciones").status_code == 403
    assert c.get(f"/api/pacientes/{LUCIA}/linea-tiempo").status_code == 403


def test_sin_sesion_no_hay_nada(cliente):
    assert cliente.get("/api/notificaciones").status_code == 401
    assert cliente.get(f"/api/pacientes/{LUCIA}/linea-tiempo").status_code == 401


def test_las_preferencias_avisan_que_el_correo_aun_no_se_envia(entrar):
    prefs = entrar("dra.rios").get("/api/notificaciones/preferencias").json()

    correo = next(c for c in prefs["canales"] if c["valor"] == "correo")
    assert correo["disponible"] is False and correo["nota"]
    assert [e["evento"] for e in prefs["eventos"]] == ["resultado_critico", "estudio_pendiente", "interaccion_detectada"]


def test_marcar_leida_baja_el_contador_y_la_deja_al_final(entrar):
    c = entrar("dra.rios")
    antes = c.get("/api/notificaciones").json()
    primera = antes["notificaciones"][0]

    c.post(f"/api/notificaciones/{primera['id']}/leida", json={}, headers=H)

    despues = c.get("/api/notificaciones").json()
    assert despues["no_leidas"] == antes["no_leidas"] - 1
    assert despues["notificaciones"][-1]["id"] == primera["id"] and despues["notificaciones"][-1]["leida"]


def test_revisar_el_potasio_critico_en_laboratorios_lo_saca_de_la_bandeja(entrar):
    c = entrar("dra.rios")
    critica = next(n for n in c.get("/api/notificaciones").json()["notificaciones"] if n["evento"] == "resultado_critico")
    alerta_id = critica["id"].removeprefix("lab-")

    r = c.post(f"/api/pacientes/{critica['paciente_id']}/alertas-laboratorio/{alerta_id}/revisar",
               json={"revisada_por": "dra.rios"}, headers=H)

    assert r.status_code == 200, r.text
    assert all(n["evento"] != "resultado_critico" for n in c.get("/api/notificaciones").json()["notificaciones"])
