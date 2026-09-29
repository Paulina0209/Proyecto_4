"""Índice del estudio completo + detalle bajo demanda al abrir el paciente."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

import patients.api as api_module
from cbioportal import CargadorDetalle, importar_indice
from historia_clinica.db import crear_conexion
from historia_clinica.integracion_externa import listar_sincronizaciones
from patients import db as db_pacientes
from patients.busqueda import buscar_pacientes
from patients.models import FiltrosBusqueda
from patients.resumen_360 import obtener_resumen_360

from .conftest import ESTUDIO, FECHA_REFERENCIA, ClienteFalso

ONCOLOGO = 3


@pytest.fixture
def ruta_expediente(tmp_path):
    return str(tmp_path / "expediente.db")


@pytest.fixture
def conn(ruta_expediente):
    connection = crear_conexion(ruta_expediente)
    yield connection
    connection.close()


@pytest.fixture
def conn_pac():
    connection = db_pacientes.conectar(":memory:")
    db_pacientes.inicializar(connection)
    yield connection
    connection.close()


def _indice(conn, conn_pac, cliente, **kwargs):
    kwargs.setdefault("fecha_referencia", FECHA_REFERENCIA)
    return importar_indice(conn, conn_pac, cliente, ESTUDIO, ONCOLOGO, **kwargs)


def _id_pac(conn_pac, paciente):
    return conn_pac.execute(
        "SELECT id FROM pacientes WHERE numero_identificacion = ?", (f"CBIO:{ESTUDIO}:{paciente}",)
    ).fetchone()[0]


def _contar(conn, sql, *params):
    return conn.execute(sql, params).fetchone()[0]


# --- Índice ---------------------------------------------------------------------


def test_indice_crea_a_todos_con_datos_basicos_sin_pedir_detalle(conn, conn_pac, cliente):
    r = _indice(conn, conn_pac, cliente)

    assert (r.pacientes, r.nuevos_en_expediente, r.nuevos_en_modulo_pacientes) == (3, 3, 3)
    assert cliente.llamadas == []  # ninguna llamada por paciente
    assert _contar(conn, "SELECT COUNT(*) FROM sincronizaciones_externas") == 0
    assert _contar(conn, "SELECT COUNT(*) FROM laboratorios") == 0

    fila = conn.execute("SELECT * FROM pacientes WHERE identificacion = ?", (f"CBIO:{ESTUDIO}:P-0000015",)).fetchone()
    assert (fila["sexo"], fila["fecha_nacimiento"], fila["diagnostico_principal"], fila["estadio"]) == (
        "femenino", "1981-01-01", "Breast Invasive Ductal Carcinoma", None)


def test_indice_se_puede_buscar_en_pac02(conn, conn_pac, cliente):
    _indice(conn, conn_pac, cliente)
    resultado = buscar_pacientes(conn_pac, FiltrosBusqueda(oncologo_id=ONCOLOGO, diagnostico="adenocarcinoma"))
    assert sorted(p.numero_identificacion for p in resultado.items) == [
        f"CBIO:{ESTUDIO}:P-0000012", f"CBIO:{ESTUDIO}:P-0000036"]


def test_seleccion_por_tipo_incluye_pacientes_con_varios_canceres(conn, conn_pac, cliente):
    r = _indice(conn, conn_pac, cliente, tipos=["Breast Cancer"])
    assert r.pacientes == 2  # P-0000015 y P-0000012 (mama y pulmón)
    assert _indice(conn, conn_pac, ClienteFalso(), tipos=["Breast Cancer"], por_tipo=1).pacientes == 1


def test_reejecutar_no_duplica_y_conserva_la_fecha_de_referencia(conn, conn_pac, cliente):
    _indice(conn, conn_pac, cliente)
    r = _indice(conn, conn_pac, cliente, fecha_referencia=date(2030, 1, 1))
    assert (r.nuevos_en_expediente, r.nuevos_en_modulo_pacientes) == (0, 0)
    assert r.fecha_referencia == FECHA_REFERENCIA
    assert _contar(conn_pac, "SELECT COUNT(*) FROM pacientes") == 3


# --- Detalle bajo demanda ----------------------------------------------------------


def test_abrir_un_paciente_trae_su_detalle_una_sola_vez(conn, conn_pac, cliente, ruta_expediente):
    _indice(conn, conn_pac, cliente)
    cargador = CargadorDetalle.desde_ruta(ruta_expediente, cliente)
    paciente_id = _id_pac(conn_pac, "P-0000015")

    antes = obtener_resumen_360(conn_pac, paciente_id, ONCOLOGO)
    assert antes.estadio is None and antes.tratamiento_mas_reciente is None and not antes.labs_recientes

    r = cargador.asegurar_detalle(conn_pac, paciente_id)
    assert r.sincronizacion.exito and not r.paciente_nuevo  # usó la fila que creó el índice

    despues = obtener_resumen_360(conn_pac, paciente_id, ONCOLOGO)
    assert despues.estadio == "I"
    assert despues.tratamiento_mas_reciente.regimen == "Capecitabine (quimioterapia)"
    assert despues.labs_recientes[0].fecha == "2026-09-29"  # misma fecha de referencia del índice
    assert _contar(conn_pac, "SELECT COUNT(*) FROM diagnosticos WHERE paciente_id = ?", paciente_id) == 1

    llamadas = len(cliente.llamadas)
    assert cargador.asegurar_detalle(conn_pac, paciente_id) is None
    assert len(cliente.llamadas) == llamadas


def test_detalle_usa_la_fecha_de_referencia_guardada(conn, conn_pac, cliente, ruta_expediente):
    _indice(conn, conn_pac, cliente, fecha_referencia=date(2025, 1, 31))
    CargadorDetalle.desde_ruta(ruta_expediente, cliente).asegurar_detalle(conn_pac, _id_pac(conn_pac, "P-0000015"))
    ultima = _contar(conn, "SELECT MAX(fecha) FROM laboratorios")
    assert ultima == "2025-01-31"


def test_si_la_api_falla_se_muestra_lo_basico_y_se_reintenta_al_abrir_de_nuevo(conn, conn_pac, cliente, ruta_expediente):
    _indice(conn, conn_pac, cliente)
    cargador = CargadorDetalle.desde_ruta(ruta_expediente, cliente)
    paciente_id = _id_pac(conn_pac, "P-0000015")

    cliente.falla_en.add("P-0000015")
    r = cargador.asegurar_detalle(conn_pac, paciente_id)
    assert not r.sincronizacion.exito
    resumen = obtener_resumen_360(conn_pac, paciente_id, ONCOLOGO)
    assert resumen.diagnostico_principal == "Breast Invasive Ductal Carcinoma"  # lo del índice sigue ahí

    cliente.falla_en.clear()
    assert cargador.asegurar_detalle(conn_pac, paciente_id).sincronizacion.exito
    historia_id = _contar(conn, "SELECT id FROM pacientes WHERE identificacion = ?", f"CBIO:{ESTUDIO}:P-0000015")
    assert [s.estado for s in listar_sincronizaciones(conn, historia_id)] == ["exitosa", "fallida"]


def test_pacientes_propios_no_se_tocan(conn, conn_pac, cliente, ruta_expediente):
    conn_pac.execute(
        "INSERT INTO pacientes (nombre_completo, sexo, tipo_identificacion, numero_identificacion, oncologo_id, "
        "fecha_registro) VALUES ('Ana Pérez', 'femenino', 'cedula', '1234567', 3, '2026-01-01')"
    )
    assert CargadorDetalle.desde_ruta(ruta_expediente, cliente).asegurar_detalle(conn_pac, 1) is None
    assert cliente.llamadas == []


def test_precargar_con_el_modo_completo_completa_pacientes_del_indice(conn, conn_pac, cliente):
    from cbioportal import FuenteCBioPortal, importar_paciente, volcar_en_modulo_pacientes

    _indice(conn, conn_pac, cliente)
    r = importar_paciente(conn, FuenteCBioPortal(cliente, FECHA_REFERENCIA), ESTUDIO, "P-0000015")
    paciente_id = volcar_en_modulo_pacientes(conn_pac, r, FECHA_REFERENCIA, ONCOLOGO)

    assert paciente_id == _id_pac(conn_pac, "P-0000015")
    tratamientos = _contar(conn_pac, "SELECT COUNT(*) FROM tratamientos WHERE paciente_id = ?", paciente_id)
    assert tratamientos > 0
    volcar_en_modulo_pacientes(conn_pac, r, FECHA_REFERENCIA, ONCOLOGO)  # segunda vez: no duplica
    assert _contar(conn_pac, "SELECT COUNT(*) FROM tratamientos WHERE paciente_id = ?", paciente_id) == tratamientos


# --- Por la API HTTP (PAC-02/PAC-03) ------------------------------------------------


@pytest.fixture
def api(tmp_path, monkeypatch, conn, cliente, ruta_expediente):
    ruta_pac = tmp_path / "pacientes.db"
    conn_pac = db_pacientes.conectar(ruta_pac)
    db_pacientes.inicializar(conn_pac)
    _indice(conn, conn_pac, cliente)
    conn_pac.close()
    monkeypatch.setattr(api_module, "DB_PATH", ruta_pac)
    monkeypatch.setattr(api_module, "SEMBRAR_DATOS_PRUEBA", False)
    monkeypatch.setattr(api_module, "CARGADOR_DETALLE", CargadorDetalle.desde_ruta(ruta_expediente, cliente))
    with TestClient(api_module.app) as c:
        yield c


def test_api_buscar_y_abrir_el_360_carga_el_detalle(api, cliente):
    busqueda = api.get("/pacientes/buscar", params={"oncologo_id": ONCOLOGO, "nombre": "P-0000015"}).json()
    [paciente] = busqueda["items"]
    assert cliente.llamadas == []  # buscar no trae detalle

    resumen = api.get(f"/pacientes/{paciente['id']}/resumen-360", params={"oncologo_id": ONCOLOGO}).json()
    assert resumen["estadio"] == "I"
    assert resumen["tratamiento_mas_reciente"]["regimen"] == "Capecitabine (quimioterapia)"


def test_api_no_carga_detalle_de_pacientes_de_otro_oncologo(api, cliente):
    respuesta = api.get("/pacientes/1/resumen-360", params={"oncologo_id": ONCOLOGO + 1})
    assert respuesta.status_code == 404
    assert cliente.llamadas == []


def test_api_con_la_fuente_caida_el_360_responde_igual(api, cliente):
    cliente.falla_en.update({"P-0000015", "P-0000036", "P-0000012"})
    respuesta = api.get("/pacientes/1/resumen-360", params={"oncologo_id": ONCOLOGO})
    assert respuesta.status_code == 200
    assert respuesta.json()["diagnostico_principal"]
