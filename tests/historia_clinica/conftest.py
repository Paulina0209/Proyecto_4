import pytest

from historia_clinica.db import crear_conexion
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


def insertar_paciente(conn, identificacion="EXT-1", cancer_type=None, nombre="Paciente de prueba (sintético)"):
    cur = conn.execute(
        "INSERT INTO pacientes (nombre, fecha_nacimiento, sexo, identificacion) VALUES (?, ?, ?, ?)",
        (nombre, "1970-01-01", "femenino", identificacion),
    )
    paciente_id = cur.lastrowid
    if cancer_type:
        insertar_dato(conn, paciente_id, "cancer_type", cancer_type)
    conn.commit()
    return paciente_id


def insertar_dato(conn, paciente_id, variable, valor, fecha="2026-01-01"):
    conn.execute(
        "INSERT INTO datos_clinicos_estructurados (paciente_id, fecha, variable, valor) VALUES (?, ?, ?, ?)",
        (paciente_id, fecha, variable, valor),
    )
    conn.commit()


def insertar_biomarcador(conn, paciente_id, nombre, resultado, fecha="2026-01-01"):
    conn.execute(
        "INSERT INTO biomarcadores (paciente_id, fecha, biomarcador, resultado) VALUES (?, ?, ?, ?)",
        (paciente_id, fecha, nombre, resultado),
    )
    conn.commit()


def insertar_imagen(conn, paciente_id, region, fecha="2026-01-01"):
    conn.execute(
        "INSERT INTO imagenologia (paciente_id, fecha, modalidad, region, hallazgos) VALUES (?, ?, ?, ?, ?)",
        (paciente_id, fecha, "Mamografía", region, "Lesión espiculada de 2 cm."),
    )
    conn.commit()
