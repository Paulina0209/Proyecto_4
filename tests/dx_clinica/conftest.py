import pytest

from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.seed import sembrar_datos_sinteticos


@pytest.fixture
def conn_sembrada():
    conn = crear_conexion(":memory:")
    ids = sembrar_datos_sinteticos(conn)
    yield conn, ids
    conn.close()
