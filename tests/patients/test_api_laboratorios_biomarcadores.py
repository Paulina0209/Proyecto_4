"""API de HC-02 (laboratorios) y HC-04 (biopsias y biomarcadores), y su
reflejo en el resumen 360. Los datos viven en el expediente clínico
(una base temporal en estas pruebas, ver conftest)."""
from __future__ import annotations

import pytest

import patients.api as api_module
from historia_clinica.db import crear_conexion
from tx_clinica.patient_facts import construir_facts_paciente

ONC = {"oncologo_id": 1}
MARIA = 1  # María Gómez, cédula 91000001, del oncólogo 1
DE_OTRO_ONCOLOGO = 10


def _lab(client, paciente_id=MARIA, **cambios):
    datos = {"identificacion": "91000001", "nombre": "María Gómez", "prueba": "Potasio", "valor": "4.2",
             "unidad": "mmol/L", "fecha": "2026-03-10", "hora": "07:30"}
    datos.update(cambios)
    return client.post(f"/pacientes/{paciente_id}/laboratorios", params=ONC, json=datos)


def _biopsia(client, paciente_id=MARIA):
    r = client.post(f"/pacientes/{paciente_id}/episodios", params=ONC,
                    json={"descripcion": "Adenocarcinoma de pulmón", "tipo_cancer": "NSCLC", "fecha_diagnostico": "2026-01-15"})
    assert r.status_code == 201, r.text
    r = client.post(f"/pacientes/{paciente_id}/biopsias", params=ONC,
                    json={"fecha": "2026-01-20", "sitio": "Lóbulo inferior derecho", "procedimiento": "Biopsia por broncoscopia"})
    assert r.status_code == 201, r.text
    return r.json()


def _resumen(client, paciente_id=MARIA):
    return client.get(f"/pacientes/{paciente_id}/resumen-360", params=ONC).json()


# --- HC-02 ------------------------------------------------------------------


def test_resultado_critico_aparece_como_alerta_en_el_360(client_con_datos):
    r = _lab(client_con_datos, valor="7.1")

    assert r.status_code == 201, r.text
    assert r.json()["alerta"]["limite_superado"] == "> 6.5 mmol/L (crítico alto)"
    resumen = _resumen(client_con_datos)
    alerta = next(a for a in resumen["alertas_activas"] if a["tipo"] == "laboratorio_critico")
    assert alerta["severidad"] == "alta"
    assert "Potasio 7.1" in alerta["descripcion"]
    assert resumen["labs_recientes"][0] == {"fecha": "2026-03-10", "resumen": "7.1 mmol/L (crítico)", "titulo": "Potasio"}


def test_la_alerta_revisada_sale_del_360(client_con_datos):
    alerta_id = _lab(client_con_datos, valor="7.1").json()["alerta"]["id"]

    r = client_con_datos.post(f"/pacientes/{MARIA}/alertas-laboratorio/{alerta_id}/revisar", params=ONC,
                              json={"revisada_por": "dra.ruiz"})

    assert r.status_code == 200 and r.json()["estado"] == "revisada"
    assert not [a for a in _resumen(client_con_datos)["alertas_activas"] if a["tipo"] == "laboratorio_critico"]
    todas = client_con_datos.get(f"/pacientes/{MARIA}/alertas-laboratorio", params={**ONC, "solo_activas": False}).json()
    assert len(todas) == 1


@pytest.mark.parametrize(
    ("cambios", "campo"),
    [({"identificacion": "91000002"}, "identificacion"), ({"nombre": "Carlos Ruiz"}, "identificacion")],
)
def test_doble_validacion_responde_409_y_no_guarda(client_con_datos, cambios, campo):
    r = _lab(client_con_datos, **cambios)

    assert r.status_code == 409
    assert r.json()["detail"]["errores"][0]["campo"] == campo
    assert client_con_datos.get(f"/pacientes/{MARIA}/laboratorios/marcadores", params=ONC).json() == []


def test_datos_invalidos_responden_400(client_con_datos):
    r = _lab(client_con_datos, rango_referencia="normal")
    assert r.status_code == 400
    assert r.json()["detail"]["errores"][0]["campo"] == "datos"


def test_conflicto_se_marca_y_se_resuelve_sin_borrar(client_con_datos):
    _lab(client_con_datos, valor="4.2")
    r = _lab(client_con_datos, valor="5.9")

    (conflicto,) = r.json()["conflictos"]
    assert {conflicto["valor_a"], conflicto["valor_b"]} == {"4.2", "5.9"}
    assert any(a["tipo"] == "conflicto_laboratorio" for a in _resumen(client_con_datos)["alertas_activas"])

    r = client_con_datos.post(
        f"/pacientes/{MARIA}/conflictos-laboratorio/{conflicto['id']}/resolver", params=ONC,
        json={"resolucion": "valido_a", "resuelto_por": "dra.ruiz", "nota": "Muestra B hemolizada"},
    )
    assert r.status_code == 200 and r.json()["estado"] == "resuelto"
    assert client_con_datos.get(f"/pacientes/{MARIA}/conflictos-laboratorio", params=ONC).json() == []
    tendencia = client_con_datos.get(f"/pacientes/{MARIA}/laboratorios/tendencia", params={**ONC, "prueba": "K"}).json()
    assert len(tendencia["series"][0]["puntos"]) == 2


def test_resolucion_invalida_es_400(client_con_datos):
    _lab(client_con_datos, valor="4.2")
    conflicto = _lab(client_con_datos, valor="5.9").json()["conflictos"][0]

    r = client_con_datos.post(f"/pacientes/{MARIA}/conflictos-laboratorio/{conflicto['id']}/resolver", params=ONC,
                              json={"resolucion": "borrar_b", "resuelto_por": "dra.ruiz"})
    assert r.status_code == 400


def test_tendencia_y_marcadores(client_con_datos):
    for fecha, valor in (("2026-01-10", "3.1"), ("2026-02-10", "5.4"), ("2026-03-10", "8.0")):
        _lab(client_con_datos, prueba="CEA", valor=valor, unidad="ng/ml", fecha=fecha, hora=None, rango_referencia="0-5.0")

    tendencia = client_con_datos.get(f"/pacientes/{MARIA}/laboratorios/tendencia", params={**ONC, "prueba": "cea"}).json()
    marcadores = client_con_datos.get(f"/pacientes/{MARIA}/laboratorios/marcadores", params=ONC).json()

    assert [p["valor_numerico"] for p in tendencia["series"][0]["puntos"]] == [3.1, 5.4, 8.0]
    assert [p["alterado"] for p in tendencia["series"][0]["puntos"]] == [False, True, True]
    assert marcadores[0]["prueba"] == "CEA" and marcadores[0]["cantidad"] == 3


def test_interfaz_hl7(client_con_datos):
    mensaje = "\r".join([
        "MSH|^~\\&|LIS|HOSP|COPILOTO|ONCO|20260310080000||ORU^R01|M1|P|2.5",
        "PID|1||91000001^^^HOSP||Gómez^María||19610514|F",
        "OBR|1|||CBC^Hemograma|||20260310073000",
        "OBX|1|NM|777-3^Plaquetas||15|10\\S\\3/uL|150-450|LL|||F",
    ])
    r = client_con_datos.post(f"/pacientes/{MARIA}/laboratorios/hl7", params=ONC, json={"mensaje": mensaje})

    assert r.status_code == 200, r.text
    assert r.json()["registros_importados"] == 1
    alertas = client_con_datos.get(f"/pacientes/{MARIA}/alertas-laboratorio", params=ONC).json()
    assert alertas[0]["prueba"] == "Plaquetas"


def test_hl7_de_otro_paciente_es_400(client_con_datos):
    mensaje = "\r".join([
        "MSH|^~\\&|LIS|HOSP|COPILOTO|ONCO|20260310080000||ORU^R01|M2|P|2.5",
        "PID|1||91000001^^^HOSP||Ruiz^Carlos||19581102|M",
        "OBX|1|NM|2823-3^Potasio||7.0|mmol/L|||||F|||20260310074500",
    ])
    r = client_con_datos.post(f"/pacientes/{MARIA}/laboratorios/hl7", params=ONC, json={"mensaje": mensaje})
    assert r.status_code == 400
    assert "no coincide" in r.json()["detail"]["errores"][0]["mensaje"]


# --- HC-04 ------------------------------------------------------------------


def test_biopsia_vinculada_y_biomarcador_clave_en_el_360(client_con_datos):
    biopsia = _biopsia(client_con_datos)

    r = client_con_datos.post(f"/pacientes/{MARIA}/biomarcadores", params=ONC, json={
        "biopsia_id": biopsia["id"], "biomarcador": "EGFR", "estado": "detectada", "confirmacion": "detectada",
        "metodo": "NGS", "variante": "L858R",
    })

    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert (cuerpo["relevancia"], cuerpo["variable_tx"], cuerpo["valor_tx"]) == (
        "accionable_confirmado", "egfr_status", "sensitizing_mutation")
    assert cuerpo["episodio_id"] == biopsia["episodio_id"]
    (clave,) = _resumen(client_con_datos)["biomarcadores_clave"]
    assert (clave["biomarcador"], clave["confirmado"]) == ("EGFR", True)

    # TX-01 lo recibe desde el expediente.
    conn = crear_conexion(str(api_module.EXPEDIENTE_PATH))
    try:
        expediente_id = conn.execute("SELECT id FROM pacientes WHERE identificacion = '91000001'").fetchone()[0]
        assert construir_facts_paciente(conn, expediente_id)["egfr_status"] == "sensitizing_mutation"
    finally:
        conn.close()


def test_biomarcador_invalido_responde_400_con_todos_los_errores(client_con_datos):
    biopsia = _biopsia(client_con_datos)

    r = client_con_datos.post(f"/pacientes/{MARIA}/biomarcadores", params=ONC, json={
        "biopsia_id": biopsia["id"], "biomarcador": "EGFR", "estado": "detectada", "confirmacion": "no_detectada",
        "metodo": "a ojo",
    })

    assert r.status_code == 400
    campos = {e["campo"] for e in r.json()["detail"]["errores"]}
    assert {"metodo", "confirmacion", "variante"} <= campos


def test_biopsia_sin_episodio_es_400(client_con_datos):
    r = client_con_datos.post(f"/pacientes/{MARIA}/biopsias", params=ONC,
                              json={"fecha": "2026-01-20", "sitio": "Pulmón", "procedimiento": "Biopsia"})
    assert r.status_code == 400
    assert r.json()["detail"]["errores"][0]["campo"] == "episodio_id"


def test_confirmar_un_pendiente_por_la_api(client_con_datos):
    _biopsia(client_con_datos)
    conn = crear_conexion(str(api_module.EXPEDIENTE_PATH))
    try:
        expediente_id = conn.execute("SELECT id FROM pacientes WHERE identificacion = '91000001'").fetchone()[0]
        conn.execute("INSERT INTO datos_clinicos_estructurados (paciente_id, fecha, variable, valor) VALUES (?, '2026-01-15', 'cancer_type', 'NSCLC')", (expediente_id,))
        conn.execute("INSERT INTO biomarcadores (paciente_id, fecha, biomarcador, resultado) VALUES (?, '2026-01-20', 'ALK', "
                     "'fusión detectada: EML4-ALK (Protein fusion: in frame) — muestra S1')", (expediente_id,))
        conn.commit()
        from historia_clinica.biopsias_biomarcadores import marcar_potencialmente_accionables

        (biomarcador_id,) = marcar_potencialmente_accionables(conn, expediente_id)
    finally:
        conn.close()

    resumen = _resumen(client_con_datos)
    assert resumen["biomarcadores_clave"][0]["confirmado"] is False
    assert any(a["tipo"] == "biomarcador_pendiente" for a in resumen["alertas_activas"])

    r = client_con_datos.post(f"/pacientes/{MARIA}/biomarcadores/{biomarcador_id}/confirmar", params=ONC,
                              json={"confirmado_por": "dra.ruiz", "confirmacion": "reordenado"})
    assert r.status_code == 200, r.text
    assert r.json()["relevancia"] == "accionable_confirmado"
    assert _resumen(client_con_datos)["biomarcadores_clave"][0]["confirmado"] is True


# --- Permisos y lectura sin expediente --------------------------------------


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [
        ("get", "/laboratorios/marcadores"),
        ("get", "/alertas-laboratorio"),
        ("get", "/conflictos-laboratorio"),
        ("get", "/biopsias"),
        ("get", "/biomarcadores"),
        ("get", "/episodios"),
    ],
)
def test_paciente_de_otro_oncologo_es_404(client_con_datos, metodo, ruta):
    r = getattr(client_con_datos, metodo)(f"/pacientes/{DE_OTRO_ONCOLOGO}{ruta}", params=ONC)
    assert r.status_code == 404


def test_registrar_para_paciente_de_otro_oncologo_es_404(client_con_datos):
    assert _lab(client_con_datos, paciente_id=DE_OTRO_ONCOLOGO).status_code == 404


def test_leer_sin_datos_no_crea_al_paciente_en_el_expediente(client_con_datos):
    assert client_con_datos.get(f"/pacientes/{MARIA}/biomarcadores", params=ONC).json() == []
    conn = crear_conexion(str(api_module.EXPEDIENTE_PATH))
    try:
        assert conn.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0] == 0
    finally:
        conn.close()


def test_el_episodio_diagnostico_completa_el_360_si_no_hay_diagnostico(client):
    r = client.post("/pacientes", json={
        "nombre_completo": "Laura Martínez", "sexo": "femenino", "tipo_identificacion": "cedula",
        "numero_identificacion": "52123456", "contacto": {"telefono": "3001234567"}, "oncologo_id": 1,
    })
    paciente_id = r.json()["id"]
    assert "diagnostico_principal" in _resumen(client, paciente_id)["campos_faltantes"]

    _biopsia(client, paciente_id)

    resumen = _resumen(client, paciente_id)
    assert resumen["diagnostico_principal"] == "Adenocarcinoma de pulmón"
    assert "diagnostico_principal" not in resumen["campos_faltantes"]
    assert "estadio" in resumen["campos_faltantes"]


def test_el_360_sin_expediente_funciona_como_antes(client_con_datos):
    resumen = _resumen(client_con_datos)
    assert resumen["biomarcadores_clave"] == []
    assert not api_module.EXPEDIENTE_PATH.exists()
