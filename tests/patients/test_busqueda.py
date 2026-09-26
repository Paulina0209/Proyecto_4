"""Pruebas de PAC-02 (búsqueda y filtros) contra los criterios de
aceptación tal cual están escritos en la historia -- la funcionalidad ya
estaba implementada en busqueda.py/api.py; esto la deja formalmente
verificada."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import patients.api as api_module
from patients.api import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "pacientes_test.db")
    monkeypatch.setattr(api_module, "DB_PATH_360", tmp_path / "resumen_360_test.db")
    with TestClient(app) as c:
        yield c


def _registrar(client, **overrides):
    payload = {
        "nombre_completo": "Juan Carlos Pérez",
        "fecha_nacimiento": "1975-03-20",
        "sexo": "masculino",
        "tipo_identificacion": "cedula",
        "numero_identificacion": "1000000",
        "contacto": {"telefono": "3000000000"},
        "oncologo_id": 1,
        "antecedentes": {},
    }
    payload.update(overrides)
    r = client.post("/pacientes", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def test_ac1_busqueda_por_nombre_parcial_encuentra_coincidencias(client):
    _registrar(client, numero_identificacion="1000001")

    # "juan perez" (parcial, sin tildes, orden distinto de palabras) debe
    # encontrar a "Juan Carlos Pérez" -- ver docstring de busqueda._normalizar.
    r = client.get("/pacientes/buscar", params={"oncologo_id": 1, "nombre": "juan perez"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["nombre_completo"] == "Juan Carlos Pérez"


def test_ac2_filtros_combinados_sin_resultados_da_mensaje_claro(client):
    _registrar(client, numero_identificacion="1000002")

    r = client.get(
        "/pacientes/buscar",
        params={"oncologo_id": 1, "nombre": "Juan", "diagnostico": "algo que no existe"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []
    # AC2: mensaje explícito, no una lista vacía sin explicación.
    assert body["mensaje"] is not None and len(body["mensaje"]) > 0


def test_regla_de_negocio_solo_ve_pacientes_de_su_propio_oncologo(client):
    _registrar(client, numero_identificacion="1000003", oncologo_id=1)
    _registrar(client, nombre_completo="Ana Torres", numero_identificacion="1000004", oncologo_id=2)

    r = client.get("/pacientes/buscar", params={"oncologo_id": 1})
    body = r.json()
    nombres = [item["nombre_completo"] for item in body["items"]]
    assert "Ana Torres" not in nombres
