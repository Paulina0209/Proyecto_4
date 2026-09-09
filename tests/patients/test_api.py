import sqlite3

import pytest
from fastapi.testclient import TestClient

from patients.api import app, get_conn
from patients.repository import inicializar_schema


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test.db"

    conn_inicial = sqlite3.connect(db_path)
    inicializar_schema(conn_inicial)
    conn_inicial.close()

    def _get_conn_de_prueba():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = _get_conn_de_prueba
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _payload_base(**overrides):
    datos = dict(
        nombre_completo="María Restrepo",
        sexo="femenino",
        tipo_identificacion="cedula",
        numero_identificacion="43112233",
        contacto={"telefono": "3001234567"},
        oncologo_id=1,
    )
    datos.update(overrides)
    return datos


def test_registro_exitoso_devuelve_201_y_el_paciente_creado(client):
    respuesta = client.post("/pacientes", json=_payload_base())
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["id"] is not None
    assert cuerpo["nombre_completo"] == "María Restrepo"
    assert cuerpo["registro_completo"] is False


def test_paciente_creado_aparece_al_listar_por_oncologo(client):
    client.post("/pacientes", json=_payload_base(oncologo_id=7))
    respuesta = client.get("/pacientes", params={"oncologo_id": 7})
    assert respuesta.status_code == 200
    pacientes = respuesta.json()
    assert len(pacientes) == 1
    assert pacientes[0]["nombre_completo"] == "María Restrepo"


def test_listar_sin_oncologo_id_devuelve_422(client):
    respuesta = client.get("/pacientes")
    assert respuesta.status_code == 422


def test_campo_obligatorio_vacio_devuelve_400_con_el_campo_faltante(client):
    respuesta = client.post("/pacientes", json=_payload_base(nombre_completo=""))
    assert respuesta.status_code == 400
    campos = {e["campo"] for e in respuesta.json()["detail"]["errores"]}
    assert "nombre_completo" in campos


def test_sin_telefono_ni_email_devuelve_400(client):
    respuesta = client.post("/pacientes", json=_payload_base(contacto={}))
    assert respuesta.status_code == 400
    campos = {e["campo"] for e in respuesta.json()["detail"]["errores"]}
    assert "contacto" in campos


def test_identificacion_duplicada_devuelve_409_con_el_paciente_existente(client):
    client.post("/pacientes", json=_payload_base(numero_identificacion="99999999"))
    respuesta = client.post(
        "/pacientes",
        json=_payload_base(numero_identificacion="99999999", nombre_completo="Otra Paciente"),
    )
    assert respuesta.status_code == 409
    cuerpo = respuesta.json()["detail"]
    assert cuerpo["posible_duplicado"]["numero_identificacion"] == "99999999"


def test_corregir_el_numero_tras_el_409_si_permite_crear(client):
    client.post("/pacientes", json=_payload_base(numero_identificacion="55555555"))
    respuesta = client.post(
        "/pacientes",
        json=_payload_base(numero_identificacion="55555556", nombre_completo="Otra Paciente"),
    )
    assert respuesta.status_code == 201


def test_paciente_sin_documento_genera_identificador_temporal(client):
    respuesta = client.post(
        "/pacientes",
        json=_payload_base(tipo_identificacion="temporal", numero_identificacion=None),
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["numero_identificacion"].startswith("TEMP-")


def test_leer_paciente_por_id_devuelve_lo_que_se_creo(client):
    creado = client.post("/pacientes", json=_payload_base()).json()
    respuesta = client.get(f"/pacientes/{creado['id']}")
    assert respuesta.status_code == 200
    assert respuesta.json() == creado


def test_leer_paciente_inexistente_devuelve_404(client):
    respuesta = client.get("/pacientes/999999")
    assert respuesta.status_code == 404


def test_endpoint_de_identificador_temporal_standalone(client):
    respuesta = client.get("/identificadores-temporales/nuevo")
    assert respuesta.status_code == 200
    assert respuesta.json()["identificador_temporal"].startswith("TEMP-")


def test_registro_con_antecedentes_y_motivo_queda_completo(client):
    respuesta = client.post(
        "/pacientes",
        json=_payload_base(
            numero_identificacion="11111111",
            antecedentes={"personales": "Diabetes tipo 2", "familiares": "Madre con cáncer de mama"},
            motivo_consulta_inicial="Nódulo palpable en mama izquierda",
        ),
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["registro_completo"] is True
    
def test_email_con_formato_invalido_devuelve_400(client):
    respuesta = client.post(
        "/pacientes",
        json=_payload_base(numero_identificacion="22222222", contacto={"email": "no-es-un-email"}),
    )
    assert respuesta.status_code == 400
    campos = {e["campo"] for e in respuesta.json()["detail"]["errores"]}
    assert "email" in campos


def test_cedula_con_letras_devuelve_400(client):
    respuesta = client.post(
        "/pacientes", json=_payload_base(numero_identificacion="ABC123XYZ")
    )
    assert respuesta.status_code == 400
    campos = {e["campo"] for e in respuesta.json()["detail"]["errores"]}
    assert "numero_identificacion" in campos