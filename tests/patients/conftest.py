"""Fixtures compartidas del módulo de pacientes. Cada prueba usa su propia
base de datos temporal, nunca patients/db/pacientes.db."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import patients.api as api_module
from patients import db


@pytest.fixture()
def conn():
    """Base en memoria con el esquema creado y sin datos."""
    conexion = db.conectar(":memory:")
    db.inicializar(conexion)
    yield conexion
    conexion.close()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """API sobre una base vacía: para pruebas que registran sus propios pacientes."""
    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "pacientes_test.db")
    monkeypatch.setattr(api_module, "SEMBRAR_DATOS_PRUEBA", False)
    with TestClient(api_module.app) as c:
        yield c


@pytest.fixture()
def client_con_datos(tmp_path, monkeypatch):
    """API con db/datos_prueba.sql cargado, como la ve la demo."""
    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "pacientes_test.db")
    with TestClient(api_module.app) as c:
        yield c
