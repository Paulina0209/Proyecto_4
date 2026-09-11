from datetime import date, timedelta

import pytest

from patients.models import Paciente, Sexo, TipoIdentificacion, DatosContacto, AntecedentesMedicos
from patients.validacion import validar_formato_y_longitud


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


def _campos_con_error(paciente):
    return {e.campo for e in validar_formato_y_longitud(paciente)}


def test_nombre_muy_corto_genera_error():
    assert "nombre_completo" in _campos_con_error(_paciente_base(nombre_completo="Al"))


def test_nombre_muy_largo_genera_error():
    nombre = "A" * 201
    assert "nombre_completo" in _campos_con_error(_paciente_base(nombre_completo=nombre))


def test_nombre_con_numeros_genera_error():
    assert "nombre_completo" in _campos_con_error(_paciente_base(nombre_completo="Maria123"))


def test_nombre_valido_no_genera_error():
    assert "nombre_completo" not in _campos_con_error(_paciente_base())


def test_fecha_nacimiento_futura_genera_error():
    manana = date.today() + timedelta(days=1)
    assert "fecha_nacimiento" in _campos_con_error(_paciente_base(fecha_nacimiento=manana))


def test_fecha_nacimiento_edad_excesiva_genera_error():
    hace_130_anios = date.today().replace(year=date.today().year - 130)
    assert "fecha_nacimiento" in _campos_con_error(_paciente_base(fecha_nacimiento=hace_130_anios))


def test_fecha_nacimiento_valida_no_genera_error():
    assert "fecha_nacimiento" not in _campos_con_error(_paciente_base())


@pytest.mark.parametrize("numero", ["123", "12A34567", "1234567890123456789"])
def test_cedula_con_formato_o_longitud_invalida_genera_error(numero):
    assert "numero_identificacion" in _campos_con_error(
        _paciente_base(numero_identificacion=numero)
    )


def test_pasaporte_alfanumerico_valido_no_genera_error():
    paciente = _paciente_base(
        tipo_identificacion=TipoIdentificacion.PASAPORTE, numero_identificacion="AB12345"
    )
    assert "numero_identificacion" not in _campos_con_error(paciente)


def test_temporal_sin_prefijo_genera_error():
    paciente = _paciente_base(
        tipo_identificacion=TipoIdentificacion.TEMPORAL, numero_identificacion="ABC123"
    )
    assert "numero_identificacion" in _campos_con_error(paciente)


def test_temporal_con_prefijo_valido_no_genera_error():
    paciente = _paciente_base(
        tipo_identificacion=TipoIdentificacion.TEMPORAL, numero_identificacion="TEMP-AB12CD34EF"
    )
    assert "numero_identificacion" not in _campos_con_error(paciente)


def test_telefono_con_letras_genera_error():
    paciente = _paciente_base(contacto=DatosContacto(telefono="abcdefg"))
    assert "telefono" in _campos_con_error(paciente)


def test_telefono_valido_no_genera_error():
    assert "telefono" not in _campos_con_error(_paciente_base())


def test_email_invalido_genera_error():
    paciente = _paciente_base(contacto=DatosContacto(email="no-es-un-email"))
    assert "email" in _campos_con_error(paciente)


def test_email_valido_no_genera_error():
    paciente = _paciente_base(contacto=DatosContacto(email="maria@example.com"))
    assert "email" not in _campos_con_error(paciente)


def test_direccion_muy_larga_genera_error():
    paciente = _paciente_base(contacto=DatosContacto(telefono="3001234567", direccion="A" * 301))
    assert "direccion" in _campos_con_error(paciente)


def test_antecedentes_muy_largos_genera_error():
    paciente = _paciente_base(antecedentes=AntecedentesMedicos(personales="x" * 2001))
    assert "antecedentes.personales" in _campos_con_error(paciente)


def test_motivo_consulta_muy_largo_genera_error():
    paciente = _paciente_base(motivo_consulta_inicial="x" * 1001)
    assert "motivo_consulta_inicial" in _campos_con_error(paciente)


def test_oncologo_id_no_positivo_genera_error():
    assert "oncologo_id" in _campos_con_error(_paciente_base(oncologo_id=-1))