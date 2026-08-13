from historia_clinica_mock.repository import (
    biomarcadores_de_consulta,
    imagenologia_de_consulta,
    laboratorios_de_consulta,
    listar_consultas,
    obtener_consulta,
    obtener_paciente,
)


def test_obtener_paciente(conn_sembrada):
    conn, ids = conn_sembrada
    paciente = obtener_paciente(conn, ids["paciente_maria"])
    assert paciente is not None
    assert paciente.identificacion == "SINT-0001"
    assert paciente.diagnostico_principal == "Cáncer de mama triple negativo"


def test_obtener_paciente_inexistente_devuelve_none(conn):
    assert obtener_paciente(conn, 9999) is None


def test_listar_consultas_de_un_paciente(conn_sembrada):
    conn, ids = conn_sembrada
    consultas = listar_consultas(conn, ids["paciente_maria"])
    assert [c.id for c in consultas] == [ids["consulta_maria_1"], ids["consulta_maria_2"]]


def test_obtener_consulta_por_id(conn_sembrada):
    conn, ids = conn_sembrada
    consulta = obtener_consulta(conn, ids["consulta_carlos_1"])
    assert consulta is not None
    assert "tos persistente" in consulta.notas_libres


def test_laboratorios_de_consulta_solo_devuelve_los_vinculados(conn_sembrada):
    conn, ids = conn_sembrada
    labs_c1 = laboratorios_de_consulta(conn, ids["consulta_maria_1"])
    labs_c2 = laboratorios_de_consulta(conn, ids["consulta_maria_2"])
    assert len(labs_c1) == 1
    assert labs_c1[0].prueba == "Hemograma - neutrófilos"
    assert labs_c2 == []


def test_imagenologia_de_consulta(conn_sembrada):
    conn, ids = conn_sembrada
    imagenes = imagenologia_de_consulta(conn, ids["consulta_maria_1"])
    assert len(imagenes) == 1
    assert imagenes[0].modalidad == "Ecografía"


def test_biomarcadores_de_consulta(conn_sembrada):
    conn, ids = conn_sembrada
    biomarcadores = biomarcadores_de_consulta(conn, ids["consulta_carlos_1"])
    assert len(biomarcadores) == 1
    assert biomarcadores[0].biomarcador == "EGFR"
    assert biomarcadores[0].resultado == "positivo (exón 19)"
