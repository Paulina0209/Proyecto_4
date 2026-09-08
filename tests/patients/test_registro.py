import sqlite3
from datetime import date

import pytest

from patients.models import (
    Paciente,
    Sexo,
    TipoIdentificacion,
    DatosContacto,
    AntecedentesMedicos,
)
from patients.registro import registrar_paciente, generar_identificador_temporal
from patients.repository import inicializar_schema, listar_pacientes_de_oncologo


@pytest.fixture
def conn():
    conexion = sqlite3.connect(":memory:")
    conexion.row_factory = sqlite3.Row
    inicializar_schema(conexion)
    yield conexion
    conexion.close()


def _paciente_base(**overrides) -> Paciente:
    datos = dict(
        nombre_completo="María Restrepo",
        fecha_nacimiento=date(1975, 3, 12),
        sexo=Sexo.FEMENINO,
        tipo_identificacion=TipoIdentificacion.CEDULA,
        numero_identificacion="43112233",
        contacto=DatosContacto(telefono="3001234567"),
        oncologo_id=1,
    )
    datos.update(overrides)
    return Paciente(**datos)


def test_registro_exitoso_con_campos_obligatorios_completos(conn):
    resultado = registrar_paciente(conn, _paciente_base())
    assert resultado.exito
    assert resultado.paciente.id is not None
    assert resultado.errores == []


def test_paciente_registrado_aparece_en_lista_del_oncologo(conn):
    registrar_paciente(conn, _paciente_base(oncologo_id=7))
    pacientes = listar_pacientes_de_oncologo(conn, 7)
    assert len(pacientes) == 1
    assert pacientes[0].nombre_completo == "María Restrepo"


def test_campo_obligatorio_vacio_no_guarda_e_indica_cual_falta(conn):
    paciente = _paciente_base(nombre_completo="")
    resultado = registrar_paciente(conn, paciente)
    assert not resultado.exito
    campos_con_error = {e.campo for e in resultado.errores}
    assert "nombre_completo" in campos_con_error
    assert listar_pacientes_de_oncologo(conn, paciente.oncologo_id) == []


def test_sin_telefono_ni_email_no_guarda(conn):
    paciente = _paciente_base(contacto=DatosContacto())
    resultado = registrar_paciente(conn, paciente)
    assert not resultado.exito
    assert any(e.campo == "contacto" for e in resultado.errores)


def test_identificacion_duplicada_alerta_antes_de_crear(conn):
    registrar_paciente(conn, _paciente_base(numero_identificacion="99999999"))
    resultado = registrar_paciente(
        conn, _paciente_base(numero_identificacion="99999999", nombre_completo="Otra Paciente")
    )
    assert not resultado.exito
    assert resultado.posible_duplicado is not None
    assert resultado.posible_duplicado.numero_identificacion == "99999999"
    # No se creó el segundo registro
    assert len(listar_pacientes_de_oncologo(conn, 1)) == 1


def test_no_existe_via_para_forzar_un_duplicado_real(conn):
    # La regla de negocio exige ID único por institución: no hay forma
    # de guardar un segundo paciente con la misma identificación.
    registrar_paciente(conn, _paciente_base(numero_identificacion="55555555"))
    resultado = registrar_paciente(
        conn, _paciente_base(numero_identificacion="55555555", nombre_completo="Otra Paciente")
    )
    assert not resultado.exito
    assert len(listar_pacientes_de_oncologo(conn, 1)) == 1


def test_corregir_el_numero_tras_la_alerta_si_permite_guardar(conn):
    registrar_paciente(conn, _paciente_base(numero_identificacion="55555555"))
    # El oncólogo ve la alerta, confirma que fue un error de tipeo y
    # corrige el número real del nuevo paciente.
    resultado = registrar_paciente(
        conn, _paciente_base(numero_identificacion="55555556", nombre_completo="Otra Paciente")
    )
    assert resultado.exito
    assert len(listar_pacientes_de_oncologo(conn, 1)) == 2


def test_paciente_sin_documento_usa_identificador_temporal(conn):
    id_temporal = generar_identificador_temporal()
    paciente = _paciente_base(
        tipo_identificacion=TipoIdentificacion.TEMPORAL,
        numero_identificacion=id_temporal,
    )
    resultado = registrar_paciente(conn, paciente)
    assert resultado.exito
    assert resultado.paciente.numero_identificacion.startswith("TEMP-")


def test_dos_identificadores_temporales_distintos_no_chocan(conn):
    p1 = _paciente_base(
        tipo_identificacion=TipoIdentificacion.TEMPORAL,
        numero_identificacion=generar_identificador_temporal(),
    )
    p2 = _paciente_base(
        tipo_identificacion=TipoIdentificacion.TEMPORAL,
        numero_identificacion=generar_identificador_temporal(),
        nombre_completo="Otro Paciente",
    )
    assert registrar_paciente(conn, p1).exito
    assert registrar_paciente(conn, p2).exito


def test_registro_corto_sin_antecedentes_ni_motivo_queda_incompleto(conn):
    # Formulario corto: solo lo obligatorio, para completar después.
    resultado = registrar_paciente(conn, _paciente_base())
    assert resultado.exito
    assert resultado.paciente.registro_completo is False


def test_registro_con_antecedentes_y_motivo_queda_completo(conn):
    paciente = _paciente_base(
        antecedentes=AntecedentesMedicos(
            personales="Diabetes tipo 2", familiares="Madre con cáncer de mama"
        ),
        motivo_consulta_inicial="Nódulo palpable en mama izquierda",
    )
    resultado = registrar_paciente(conn, paciente)
    assert resultado.exito
    assert resultado.paciente.registro_completo is True