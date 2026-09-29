"""Volcado en la base de patients: los importados aparecen en PAC-02 y PAC-03."""

import pytest

from cbioportal import importar_paciente, volcar_en_modulo_pacientes
from patients import db as db_pacientes
from patients.busqueda import buscar_pacientes
from patients.models import DatosContacto, FiltrosBusqueda, Paciente, Sexo, TipoIdentificacion
from patients.registro import validar_campos_obligatorios
from patients.resumen_360 import obtener_resumen_360

from .conftest import ESTUDIO, FECHA_REFERENCIA

ONCOLOGO = 7


@pytest.fixture
def conn_pac():
    conn = db_pacientes.conectar(":memory:")
    db_pacientes.inicializar(conn)
    yield conn
    conn.close()


def _volcar(conn, conn_pac, fuente, paciente):
    return volcar_en_modulo_pacientes(conn_pac, importar_paciente(conn, fuente, ESTUDIO, paciente), FECHA_REFERENCIA, ONCOLOGO)


def test_aparece_en_la_busqueda_y_en_el_360(conn, conn_pac, fuente):
    paciente_id = _volcar(conn, conn_pac, fuente, "P-0000015")

    busqueda = buscar_pacientes(conn_pac, FiltrosBusqueda(oncologo_id=ONCOLOGO, nombre="P-0000015"))
    assert [p.id for p in busqueda.items] == [paciente_id]
    assert busqueda.items[0].tipo_identificacion is TipoIdentificacion.EXTERNO

    resumen = obtener_resumen_360(conn_pac, paciente_id, ONCOLOGO)
    assert resumen.diagnostico_principal == "Breast Invasive Ductal Carcinoma"
    assert resumen.estadio == "I"
    assert resumen.tratamiento_mas_reciente.regimen == "Capecitabine (quimioterapia)"
    assert [l.resumen for l in resumen.labs_recientes] == ["25 Units/ml", "1412 Units/ml (fuera de rango)"]
    assert resumen.imagenes_recientes[0].titulo == "TAC"


def test_estado_de_tratamiento(conn, conn_pac, fuente, cliente):
    # Paciente fallecido: ningún tratamiento queda "en curso".
    paciente_id = _volcar(conn, conn_pac, fuente, "P-0000015")
    estados = {f["regimen"]: f["estado"] for f in conn_pac.execute(
        "SELECT regimen, estado FROM tratamientos WHERE paciente_id = ?", (paciente_id,))}
    assert set(estados.values()) == {"finalizado"}

    # Vivo, con el último tratamiento hasta el final de sus datos: en curso.
    paciente_id = _volcar(conn, conn_pac, fuente, "P-0000036")
    [fila] = conn_pac.execute("SELECT estado FROM tratamientos WHERE paciente_id = ?", (paciente_id,)).fetchall()
    assert fila["estado"] == "en_tratamiento"


def test_no_duplica_ni_modifica_si_ya_existe(conn, conn_pac, fuente):
    primero = _volcar(conn, conn_pac, fuente, "P-0000015")
    conn_pac.execute("DELETE FROM tratamientos WHERE paciente_id = ?", (primero,))  # "cambio del oncólogo"
    segundo = _volcar(conn, conn_pac, fuente, "P-0000015")
    assert segundo == primero
    assert conn_pac.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0] == 1
    assert conn_pac.execute("SELECT COUNT(*) FROM tratamientos").fetchone()[0] == 0


def test_sin_estadio_si_hay_dos_primarios(conn, conn_pac, fuente):
    paciente_id = _volcar(conn, conn_pac, fuente, "P-0000012")
    resumen = obtener_resumen_360(conn_pac, paciente_id, ONCOLOGO)
    assert resumen.estadio is None and "estadio" in resumen.campos_faltantes


def test_importacion_fallida_no_vuelca_nada(conn, conn_pac, cliente, fuente):
    cliente.falla_en.add("P-0000015")
    assert _volcar(conn, conn_pac, fuente, "P-0000015") is None
    assert conn_pac.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0] == 0


def test_el_tipo_externo_no_se_puede_registrar_a_mano():
    paciente = Paciente(
        nombre_completo="Ana Pérez", fecha_nacimiento=None, sexo=Sexo.FEMENINO,
        tipo_identificacion=TipoIdentificacion.EXTERNO, numero_identificacion="CBIO:x:y",
        contacto=DatosContacto(telefono="3001234567"), oncologo_id=1,
    )
    assert any(e.campo == "tipo_identificacion" for e in validar_campos_obligatorios(paciente))
