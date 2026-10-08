"""Fixtures compartidas del módulo de pacientes. Cada prueba usa su propia
base de datos temporal, nunca patients/db/pacientes.db."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import patients.api as api_module
from patients import db


DATOS_PRUEBA = Path(__file__).resolve().parent / "datos_prueba.sql"


def cargar_datos_prueba(conexion) -> None:
    """Pacientes de ejemplo solo para las pruebas (la API ya no los carga)."""
    conexion.executescript(DATOS_PRUEBA.read_text(encoding="utf-8"))
    conexion.commit()


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
    monkeypatch.setattr(api_module, "EXPEDIENTE_PATH", tmp_path / "expediente_test.db")
    with TestClient(api_module.app) as c:
        yield c


@pytest.fixture()
def client_con_datos(tmp_path, monkeypatch):
    """API con los pacientes de ejemplo de tests/patients/datos_prueba.sql."""
    ruta = tmp_path / "pacientes_test.db"
    conexion = db.conectar(ruta)
    db.inicializar(conexion)
    cargar_datos_prueba(conexion)
    conexion.close()
    monkeypatch.setattr(api_module, "DB_PATH", ruta)
    monkeypatch.setattr(api_module, "EXPEDIENTE_PATH", tmp_path / "expediente_test.db")
    with TestClient(api_module.app) as c:
        yield c
