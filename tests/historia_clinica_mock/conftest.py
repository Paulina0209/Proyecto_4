import pytest

from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.seed import sembrar_datos_sinteticos


@pytest.fixture
def conn():
    connection = crear_conexion(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def conn_sembrada(conn):
    ids = sembrar_datos_sinteticos(conn)
    return conn, ids
