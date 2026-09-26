"""Pruebas de la pasada de correcciones sobre patients/ (D2, D4, D5, D6, D8).

Usa un archivo SQLite temporal real por prueba (no :memory: -- api.py abre
una conexión NUEVA por request via get_conn(), así que :memory: perdería
los datos entre requests) y TestClient con el lifespan real de la app, para
probar la inicialización de esquema tal cual ocurre en producción.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

import patients.api as api_module
from patients.api import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "pacientes_test.db")
    with TestClient(app) as c:
        yield c


def _paciente_payload(**overrides):
    base = {
        "nombre_completo": "Ana Pérez",
        "fecha_nacimiento": "1980-05-10",
        "sexo": "femenino",
        "tipo_identificacion": "cedula",
        "numero_identificacion": "1234567",
        "contacto": {"telefono": "3000000000"},
        "oncologo_id": 1,
        "antecedentes": {},
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------- D8

def test_d8_error_de_validacion_pydantic_usa_el_mismo_formato_que_los_400_propios(client):
    r = client.post("/pacientes", json=_paciente_payload(sexo="no_es_un_sexo_valido"))
    assert r.status_code == 400, r.text
    errores = r.json()["detail"]["errores"]
    assert any(e["campo"] == "sexo" for e in errores)


def test_d8_fecha_malformada_tambien_usa_el_formato_propio(client):
    r = client.post("/pacientes", json=_paciente_payload(fecha_nacimiento="no-es-una-fecha"))
    assert r.status_code == 400, r.text
    assert "errores" in r.json()["detail"]


def test_campo_obligatorio_faltante_sigue_devolviendo_400_como_antes(client):
    r = client.post("/pacientes", json=_paciente_payload(nombre_completo=""))
    assert r.status_code == 400, r.text
    errores = r.json()["detail"]["errores"]
    assert any(e["campo"] == "nombre_completo" for e in errores)


# --------------------------------------------------------------------- D4

def test_d4_duplicado_del_mismo_oncologo_revela_el_detalle(client):
    client.post("/pacientes", json=_paciente_payload(oncologo_id=1))
    r = client.post("/pacientes", json=_paciente_payload(oncologo_id=1))
    assert r.status_code == 409
    assert r.json()["detail"]["posible_duplicado"] is not None


def test_d4_duplicado_de_otro_oncologo_no_revela_datos(client):
    client.post("/pacientes", json=_paciente_payload(oncologo_id=1))
    r = client.post("/pacientes", json=_paciente_payload(oncologo_id=2))
    assert r.status_code == 409
    detalle = r.json()["detail"]
    assert detalle.get("posible_duplicado") is None
    assert "nombre_completo" not in str(detalle)
    assert "telefono" not in str(detalle)


# --------------------------------------------------------------------- D2

def test_d2_leer_paciente_de_otro_oncologo_da_404(client):
    creado = client.post("/pacientes", json=_paciente_payload(oncologo_id=1)).json()
    r = client.get(f"/pacientes/{creado['id']}", params={"oncologo_id": 999})
    assert r.status_code == 404


def test_d2_leer_paciente_propio_funciona(client):
    creado = client.post("/pacientes", json=_paciente_payload(oncologo_id=1)).json()
    r = client.get(f"/pacientes/{creado['id']}", params={"oncologo_id": 1})
    assert r.status_code == 200
    assert r.json()["id"] == creado["id"]


def test_d2_id_inexistente_da_404(client):
    r = client.get("/pacientes/999999", params={"oncologo_id": 1})
    assert r.status_code == 404


# --------------------------------------------------------------------- D6

def test_d6_condicion_de_carrera_no_revienta_con_500(client, monkeypatch, tmp_path):
    """Simula la carrera: la verificación de duplicado (buscar_por_identificacion)
    dice que no hay nada la PRIMERA vez que se consulta (ventana de la
    carrera), pero para cuando el INSERT corre la fila YA existe de verdad
    -- antes esto propagaba sqlite3.IntegrityError como un 500 crudo. La
    re-consulta que hace el except (después de capturar el error) debe
    seguir funcionando normal -- por eso solo se fuerza None en la
    PRIMERA llamada, no en todas."""
    # Paso 1: registra un paciente normalmente.
    r1 = client.post("/pacientes", json=_paciente_payload(numero_identificacion="9999999"))
    assert r1.status_code == 201

    # Paso 2: la próxima llamada a buscar_por_identificacion dice "no hay
    # duplicado" UNA sola vez (simula la ventana de la carrera); las
    # siguientes (la re-consulta del except) usan el comportamiento real.
    import patients.registro as registro_module

    real_buscar = registro_module.buscar_por_identificacion
    llamadas = {"n": 0}

    def _buscar_simulando_carrera(conn, tipo, numero):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            return None
        return real_buscar(conn, tipo, numero)

    monkeypatch.setattr(registro_module, "buscar_por_identificacion", _buscar_simulando_carrera)

    r2 = client.post("/pacientes", json=_paciente_payload(numero_identificacion="9999999"))
    assert r2.status_code == 409, f"esperaba 409 (duplicado detectado en el INSERT), llegó {r2.status_code}: {r2.text}"
    assert r2.json()["detail"]["posible_duplicado"] is not None


def test_d5_endpoint_de_identificador_temporal_no_existe_y_demo_ya_no_lo_llama():
    """D5: api.py nunca definió /identificadores-temporales/nuevo; el fix
    real fue quitar esa llamada de demo.py, no agregar el endpoint (el
    servidor ya genera el identificador solo). Se confirma que ninguna
    ruta de la API lo expone (para no reintroducirlo por error) y que
    demo.py ya no referencia la función que lo llamaba."""
    rutas = {r.path for r in api_module.app.routes}
    assert "/identificadores-temporales/nuevo" not in rutas

    import patients.demo as demo_module

    assert not hasattr(demo_module, "generar_identificador_temporal_api")


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
