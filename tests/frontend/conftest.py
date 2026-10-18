"""Fixtures de la interfaz web: datos SINTÉTICOS de la demostración y la pasarela real sobre ellos.

Los datos se siembran una sola vez por sesión de pruebas y cada prueba trabaja sobre su propia copia
de los archivos, así que una prueba que cambia algo (revisar una alerta, bloquear una cuenta) no afecta
a las demás. La API de pacientes se apunta a esas copias y se restaura al terminar.
"""
from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from frontend.demo import _guardar_metricas, configurar_api_de_pacientes, construir_app
from frontend.demo_datos import CLAVE_DEMO, EntornoDemo, sembrar_demo

#: Cabecera que el JavaScript propio pone en toda petición que cambia algo (defensa contra CSRF).
H = {"X-Copiloto-Solicitud": "1"}
PUERTO = 8443

# Identificadores de la demostración (ver frontend/demo_datos.py)
LUCIA, MATEO, TOMAS = 1, 2, 6          # pacientes de dra.rios
RENATA = 7                              # paciente de dr.vega: dra.rios NO debe verla
UID_ESTUDIO_LUCIA = "1.2.826.0.1.3680043.8.498.10001"


@pytest.fixture(scope="session")
def plantilla(tmp_path_factory) -> EntornoDemo:
    entorno = sembrar_demo(tmp_path_factory.mktemp("demo_plantilla"))
    _guardar_metricas(entorno.carpeta)        # las bases de métricas de la demostración, una sola vez
    return entorno


@pytest.fixture()
def entorno(plantilla: EntornoDemo, tmp_path: Path, monkeypatch) -> EntornoDemo:
    """Copia propia de las bases de la demostración, con la API de pacientes apuntando a ella."""
    from patients import api as papi

    for nombre in ("DB_PATH", "EXPEDIENTE_PATH", "PACS_FUENTE", "VISOR_PLANTILLA", "CARGADOR_DETALLE"):
        monkeypatch.setattr(papi, nombre, getattr(papi, nombre))   # al terminar, monkeypatch deja el valor original
    destino = tmp_path / "demo"
    shutil.copytree(plantilla.carpeta, destino, ignore=shutil.ignore_patterns("certs"))
    propio = dataclasses.replace(
        plantilla, carpeta=destino, usuarios_db=destino / plantilla.usuarios_db.name,
        pacientes_db=destino / plantilla.pacientes_db.name, expediente_db=destino / plantilla.expediente_db.name)
    configurar_api_de_pacientes(propio, PUERTO)
    return propio


@pytest.fixture()
def app(entorno):
    rutas = {"accesos": entorno.carpeta / "metricas_accesos.db", "expediente": entorno.carpeta / "metricas_expediente.db"}
    assert all(r.is_file() for r in rutas.values())
    return construir_app(entorno, PUERTO, metricas=rutas)


@pytest.fixture()
def cliente(app):
    """Un navegador anónimo sobre HTTPS (con el ciclo de vida de la app, que prepara la base de pacientes)."""
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def iniciar_sesion(cliente: TestClient, usuario: str, clave: str = CLAVE_DEMO):
    """Cierra cualquier sesión anterior del cliente y entra como ``usuario`` (devuelve la respuesta del login)."""
    cliente.cookies.clear()
    return cliente.post("/api/sesion", json={"usuario": usuario, "contrasena": clave}, headers=H)


@pytest.fixture()
def entrar(cliente):
    """``entrar("dra.rios")`` deja al cliente con sesión iniciada y lo devuelve."""
    def _entrar(usuario: str) -> TestClient:
        r = iniciar_sesion(cliente, usuario)
        assert r.status_code == 200, r.text
        return cliente
    return _entrar
