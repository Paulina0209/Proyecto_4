import pytest

from historia_clinica_mock.adapters import PacienteNoEncontradoError, obtener_hallazgos_de_paciente


def test_incluye_hallazgos_de_todas_las_consultas_del_paciente(conn_sembrada):
    conn, ids = conn_sembrada
    hallazgos = obtener_hallazgos_de_paciente(conn, ids["paciente_maria"])

    ids_encontrados = {h.id for h in hallazgos}
    # Debe incluir notas de AMBAS consultas de María (no solo la primera).
    assert f"lab-{ids['lab_maria_1']}" in ids_encontrados
    assert f"imagen-{ids['imagen_maria_1']}" in ids_encontrados
    assert f"biomarcador-{ids['biomarcador_maria_1']}" in ids_encontrados
    assert any(h.id.startswith(f"consulta-{ids['consulta_maria_1']}-nota-") for h in hallazgos)
    assert any(h.id.startswith(f"consulta-{ids['consulta_maria_2']}-nota-") for h in hallazgos)


def test_no_mezcla_hallazgos_de_otro_paciente(conn_sembrada):
    conn, ids = conn_sembrada
    hallazgos_maria = obtener_hallazgos_de_paciente(conn, ids["paciente_maria"])
    assert all(h.paciente_id == ids["paciente_maria"] for h in hallazgos_maria)
    assert not any("EGFR" in h.texto for h in hallazgos_maria)


def test_paciente_inexistente_lanza_error(conn):
    with pytest.raises(PacienteNoEncontradoError):
        obtener_hallazgos_de_paciente(conn, 9999)
