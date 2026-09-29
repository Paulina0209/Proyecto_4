"""Registro de consultas y datos clínicos por el oncólogo sobre el expediente."""

from datetime import date

import pytest

from expediente.adapters import construir_contexto_clinico
from expediente.db import crear_conexion
from expediente.registro import (
    PacienteInexistenteError,
    registrar_comorbilidad,
    registrar_consulta,
    registrar_datos_clinicos,
)
from expediente.repository import comorbilidades_de_paciente, facts_estructurados_de_paciente


@pytest.fixture
def conn():
    c = crear_conexion(":memory:")
    c.execute(
        "INSERT INTO pacientes (nombre, fecha_nacimiento, sexo, identificacion) "
        "VALUES ('P-0000001', '1960-01-01', 'femenino', 'CBIO:estudio:P-0000001')"
    )
    c.commit()
    yield c
    c.close()


def test_la_consulta_registrada_es_la_entrada_de_ia02(conn):
    consulta_id = registrar_consulta(conn, 1, "Control", "Refiere tos persistente. Plan: TAC de control.",
                                     fecha=date(2026, 9, 29))

    contexto = construir_contexto_clinico(conn, consulta_id)
    assert any("tos persistente" in s.text for s in contexto.segments)


def test_el_ultimo_dato_registrado_es_el_vigente(conn):
    registrar_datos_clinicos(conn, 1, {"treatment_line": 1, "pdl1_tps": 60}, fecha=date(2026, 9, 1))
    registrar_datos_clinicos(conn, 1, {"pdl1_tps": 80}, fecha=date(2026, 9, 29))

    facts = facts_estructurados_de_paciente(conn, 1)
    assert facts["treatment_line"] == "1"
    assert facts["pdl1_tps"] == "80"


def test_comorbilidad_con_juicio_de_contraindicacion(conn):
    registrar_comorbilidad(conn, 1, "Enfermedad de Crohn activa", "moderada", "absolute")
    [c] = comorbilidades_de_paciente(conn, 1)
    assert c.tipo_contraindicacion_ici == "absolute"
    with pytest.raises(ValueError):
        registrar_comorbilidad(conn, 1, "X", tipo_contraindicacion_ici="quizas")


def test_paciente_inexistente_o_datos_vacios_se_rechazan(conn):
    with pytest.raises(PacienteInexistenteError):
        registrar_consulta(conn, 99, "Control", "Nota")
    with pytest.raises(ValueError):
        registrar_consulta(conn, 1, " ", "Nota")
    with pytest.raises(ValueError):
        registrar_datos_clinicos(conn, 1, {"pdl1_tps": ""})
