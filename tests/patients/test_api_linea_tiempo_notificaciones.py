"""API de HC-06 (línea de tiempo) y CFG-02 (notificaciones), sobre los pacientes de datos_prueba.sql."""
from __future__ import annotations

import sqlite3

import patients.api as api_module

ONC = {"oncologo_id": 1}
MARIA = 1
DE_OTRO_ONCOLOGO = 10


# --- HC-06 ------------------------------------------------------------------


def test_la_linea_de_tiempo_viene_en_orden_cronologico_con_sus_tipos(client_con_datos):
    r = client_con_datos.get(f"/pacientes/{MARIA}/linea-tiempo", params=ONC)

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    fechas = [e["fecha"] for e in cuerpo["eventos"]]
    assert fechas == sorted(fechas)
    assert cuerpo["eventos"][0]["tipo"] == "diagnostico" and cuerpo["eventos"][0]["fecha"] == "2026-01-15"
    assert {"diagnostico", "consulta", "laboratorio"} <= {e["tipo"] for e in cuerpo["eventos"]}
    assert {"valor": "diagnostico", "etiqueta": "Diagnóstico"} in cuerpo["tipos"]


def test_la_linea_de_tiempo_filtra_por_tipo(client_con_datos):
    r = client_con_datos.get(f"/pacientes/{MARIA}/linea-tiempo", params={**ONC, "tipo": "consulta"})

    assert r.status_code == 200
    assert [e["fecha"] for e in r.json()["eventos"]] == ["2026-06-01", "2026-09-13"]


def test_un_tipo_desconocido_responde_400_con_el_formato_de_siempre(client_con_datos):
    r = client_con_datos.get(f"/pacientes/{MARIA}/linea-tiempo", params={**ONC, "tipo": "cirugias"})

    assert r.status_code == 400
    assert r.json()["detail"]["errores"][0]["campo"] == "tipo"


def test_la_linea_de_tiempo_de_un_paciente_ajeno_es_404(client_con_datos):
    assert client_con_datos.get(f"/pacientes/{DE_OTRO_ONCOLOGO}/linea-tiempo", params=ONC).status_code == 404


def test_leer_la_linea_de_tiempo_no_crea_el_expediente_y_queda_auditado(client_con_datos):
    r = client_con_datos.get(f"/pacientes/{MARIA}/linea-tiempo", params={**ONC, "usuario_id": 7})

    assert r.status_code == 200
    assert not api_module.EXPEDIENTE_PATH.exists()
    with sqlite3.connect(api_module.DB_PATH) as c:
        assert c.execute("SELECT usuario_id, paciente_id FROM eventos_acceso WHERE detalle = 'linea_tiempo'").fetchall() == [(7, MARIA)]


def test_las_fechas_aproximadas_del_expediente_se_marcan(client_con_datos):
    from historia_clinica.db import conectar_expediente

    # Un laboratorio crea al paciente en el expediente; luego llega un antecedente externo con solo mes y año.
    r = client_con_datos.post(f"/pacientes/{MARIA}/laboratorios", params=ONC, json={
        "identificacion": "91000001", "nombre": "María Gómez", "prueba": "Hemoglobina", "valor": "12.5",
        "unidad": "g/dL", "fecha": "2026-03-10"})
    assert r.status_code == 201, r.text
    conn = conectar_expediente(api_module.EXPEDIENTE_PATH)
    conn.execute("INSERT INTO antecedentes_externos (paciente_id, tipo, descripcion, fecha, fuente) "
                 "VALUES (1, 'procedimiento', 'Mastectomía', '2019-05', 'FHIR')")
    conn.commit()
    conn.close()

    eventos = client_con_datos.get(f"/pacientes/{MARIA}/linea-tiempo", params=ONC).json()["eventos"]

    primero = eventos[0]
    assert (primero["fecha"], primero["precision"], primero["fecha_aproximada"]) == ("2019-05", "mes", True)
    assert all(not e["fecha_aproximada"] for e in eventos[1:])


# --- CFG-02 -----------------------------------------------------------------


def test_la_bandeja_trae_estudios_pendientes_e_interacciones_de_mis_pacientes(client_con_datos):
    r = client_con_datos.get("/notificaciones", params=ONC)

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["no_leidas"] == len(cuerpo["notificaciones"]) == 7      # las alertas sin resolver de los pacientes del oncólogo 1
    assert {n["evento"] for n in cuerpo["notificaciones"]} == {"estudio_pendiente", "interaccion_detectada"}
    assert all(n["paciente_id"] != DE_OTRO_ONCOLOGO for n in cuerpo["notificaciones"])
    assert cuerpo["notificaciones"][0]["severidad"] == "alta"


def test_las_preferencias_se_leen_se_guardan_y_cambian_la_bandeja(client_con_datos):
    inicial = client_con_datos.get("/notificaciones/preferencias", params=ONC).json()
    assert inicial["es_por_defecto"] and [c["valor"] for c in inicial["canales"]] == ["en_aplicacion", "correo"]

    r = client_con_datos.put("/notificaciones/preferencias", params=ONC, json={"preferencias": [
        {"evento": "estudio_pendiente", "activo": False, "canales": []}]})

    assert r.status_code == 200, r.text
    assert not r.json()["es_por_defecto"]
    assert {n["evento"] for n in client_con_datos.get("/notificaciones", params=ONC).json()["notificaciones"]} == {"interaccion_detectada"}


def test_preferencias_invalidas_responden_400_sin_guardar(client_con_datos):
    r = client_con_datos.put("/notificaciones/preferencias", params=ONC, json={"preferencias": [
        {"evento": "interaccion_detectada", "activo": False, "canales": []},
        {"evento": "resultado_critico", "activo": True, "canales": []}]})

    assert r.status_code == 400
    assert r.json()["detail"]["errores"][0]["campo"] == "canales.resultado_critico"
    assert client_con_datos.get("/notificaciones/preferencias", params=ONC).json()["es_por_defecto"]


def test_marcar_como_leida(client_con_datos):
    primera = client_con_datos.get("/notificaciones", params=ONC).json()["notificaciones"][0]

    r = client_con_datos.post(f"/notificaciones/{primera['id']}/leida", params=ONC)

    assert r.status_code == 200 and r.json()["leida"]
    assert client_con_datos.get("/notificaciones", params=ONC).json()["no_leidas"] == 6
    assert client_con_datos.post(f"/notificaciones/{primera['id']}/leida", params={"oncologo_id": 2}).status_code == 404
    assert client_con_datos.post("/notificaciones/alerta-9999/leida", params=ONC).status_code == 404


def test_un_canal_desconocido_o_una_lista_vacia_responden_400(client_con_datos):
    r = client_con_datos.put("/notificaciones/preferencias", params=ONC, json={"preferencias": [
        {"evento": "estudio_pendiente", "activo": True, "canales": ["sms"]}]})
    assert r.status_code == 400 and r.json()["detail"]["errores"][0]["campo"] == "canales.estudio_pendiente"

    r = client_con_datos.put("/notificaciones/preferencias", params=ONC, json={"preferencias": []})
    assert r.status_code == 400 and r.json()["detail"]["errores"][0]["campo"] == "preferencias"


def test_las_preferencias_de_un_oncologo_no_tocan_las_de_otro(client_con_datos):
    client_con_datos.put("/notificaciones/preferencias", params=ONC, json={"preferencias": [
        {"evento": "interaccion_detectada", "activo": False, "canales": []}]})

    otro = client_con_datos.get("/notificaciones/preferencias", params={"oncologo_id": 2}).json()
    assert otro["es_por_defecto"] and all(e["activo"] for e in otro["eventos"])


def test_un_laboratorio_critico_llega_a_la_bandeja_y_sale_al_revisarlo(client_con_datos):
    r = client_con_datos.post(f"/pacientes/{MARIA}/laboratorios", params=ONC, json={
        "identificacion": "91000001", "nombre": "María Gómez", "prueba": "Potasio", "valor": "7.4",
        "unidad": "mmol/L", "fecha": "2026-03-10", "rango_referencia": "3.5-5.1"})
    assert r.status_code == 201, r.text

    bandeja = client_con_datos.get("/notificaciones", params=ONC).json()
    primera = bandeja["notificaciones"][0]
    assert (primera["evento"], primera["severidad"], primera["paciente_id"]) == ("resultado_critico", "critica", MARIA)
    assert "Potasio 7.4 mmol/L" in primera["mensaje"] and bandeja["no_leidas"] == 8

    alerta_id = int(primera["id"].removeprefix("lab-"))
    r = client_con_datos.post(f"/pacientes/{MARIA}/alertas-laboratorio/{alerta_id}/revisar", params=ONC,
                              json={"revisada_por": "dra.prueba"})
    assert r.status_code == 200, r.text
    assert all(n["evento"] != "resultado_critico" for n in client_con_datos.get("/notificaciones", params=ONC).json()["notificaciones"])


def test_la_bandeja_no_crea_el_expediente(client_con_datos):
    assert client_con_datos.get("/notificaciones", params=ONC).status_code == 200
    assert not api_module.EXPEDIENTE_PATH.exists()
