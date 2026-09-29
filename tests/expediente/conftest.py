import pytest

from expediente.db import crear_conexion
from tests.datos_sinteticos import sembrar_datos_sinteticos


@pytest.fixture
def conn():
    connection = crear_conexion(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def conn_sembrada(conn):
    ids = sembrar_datos_sinteticos(conn)
    return conn, ids
