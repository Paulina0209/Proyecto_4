"""TX-01 recibe los biomarcadores clave de HC-04 en `obtener_datos_paciente`."""

import json
from datetime import date

import pytest

from historia_clinica.biopsias_biomarcadores import (
    marcar_potencialmente_accionables,
    registrar_biomarcador,
    registrar_biopsia,
    registrar_episodio,
)
from historia_clinica.db import crear_conexion
from tx_clinica.tools import patients_tools


@pytest.fixture
def conn(monkeypatch):
    conexion = crear_conexion(":memory:")
    monkeypatch.setattr(patients_tools, "obtener_conexion", lambda: conexion)
    yield conexion
    conexion.close()


def _paciente(conn):
    cursor = conn.execute(
        "INSERT INTO pacientes (nombre, fecha_nacimiento, sexo, identificacion) VALUES ('Paciente Prueba', '1960-01-01', 'otro', 'X-1')"
    )
    conn.commit()
    return cursor.lastrowid


def _datos(paciente_id):
    return json.loads(patients_tools.obtener_datos_paciente.invoke({"patient_id": paciente_id}))


def test_biomarcador_confirmado_llega_como_fact_y_como_clave(conn):
    paciente_id = _paciente(conn)
    registrar_episodio(conn, paciente_id, "Adenocarcinoma de pulmón", "NSCLC")
    biopsia = registrar_biopsia(conn, paciente_id, fecha=date(2026, 1, 20), sitio="Pulmón", procedimiento="Biopsia")
    registrar_biomarcador(conn, paciente_id, biopsia_id=biopsia.id, biomarcador="EGFR", estado="detectada",
                          confirmacion="detectada", metodo="NGS", variante="L858R")

    datos = _datos(paciente_id)

    assert datos["facts_clinicos"]["egfr_status"] == "sensitizing_mutation"
    (clave,) = datos["biomarcadores_clave"]
    assert (clave["biomarcador"], clave["confirmado"], clave["variable_tratamiento"]) == ("EGFR", True, "egfr_status")


def test_pendiente_aparece_sin_confirmar_y_sin_fact(conn):
    paciente_id = _paciente(conn)
    conn.execute("INSERT INTO datos_clinicos_estructurados (paciente_id, fecha, variable, valor) VALUES (?, '2026-01-01', 'cancer_type', 'NSCLC')", (paciente_id,))
    conn.execute("INSERT INTO biomarcadores (paciente_id, fecha, biomarcador, resultado) VALUES (?, '2026-01-20', 'ALK', "
                 "'fusión detectada: EML4-ALK (Protein fusion: in frame) — muestra S1')", (paciente_id,))
    conn.commit()
    marcar_potencialmente_accionables(conn, paciente_id)

    datos = _datos(paciente_id)

    assert datos["biomarcadores_clave"][0]["confirmado"] is False
    assert "alk_status" not in datos["facts_clinicos"]


def test_paciente_sin_biomarcadores(conn):
    assert _datos(_paciente(conn))["biomarcadores_clave"] == []
