import pytest

from expediente.db import crear_conexion
from tests.datos_sinteticos import sembrar_datos_sinteticos


@pytest.fixture
def conn_sembrada():
    conn = crear_conexion(":memory:")
    ids = sembrar_datos_sinteticos(conn)
    yield conn, ids
    conn.close()
