import pytest

from historia_clinica_mock.adapters import (
    ConsultaNoEncontradaError,
    PacienteNoEncontradoError,
    construir_contexto_clinico,
    construir_contexto_resumen_caso,
)


def test_contexto_incluye_notas_labs_imagenes_y_biomarcadores(conn_sembrada):
    conn, ids = conn_sembrada
    context = construir_contexto_clinico(conn, ids["consulta_maria_1"])

    origenes = {segment.origin for segment in context.segments}
    assert origenes == {"consulta", "laboratorio", "imagenologia", "biomarcador"}
    assert context.consult_id == f"consulta-{ids['consulta_maria_1']}"
    assert context.patient_ref == f"paciente-{ids['paciente_maria']}"


def test_ids_de_fragmentos_trazan_a_filas_reales_de_la_base_de_datos(conn_sembrada):
    conn, ids = conn_sembrada
    context = construir_contexto_clinico(conn, ids["consulta_maria_1"])

    ids_por_origen = {s.origin: s.id for s in context.segments if s.origin != "consulta"}
    assert ids_por_origen["laboratorio"] == f"lab-{ids['lab_maria_1']}"
    assert ids_por_origen["imagenologia"] == f"imagen-{ids['imagen_maria_1']}"
    assert ids_por_origen["biomarcador"] == f"biomarcador-{ids['biomarcador_maria_1']}"


def test_consulta_sin_labs_ni_imagenes_solo_trae_fragmentos_de_notas(conn_sembrada):
    conn, ids = conn_sembrada
    context = construir_contexto_clinico(conn, ids["consulta_maria_2"])

    assert all(segment.origin == "consulta" for segment in context.segments)
    assert len(context.segments) == 3  # las tres oraciones de la nota de esa consulta


def test_consulta_inexistente_lanza_error_explicito(conn):
    with pytest.raises(ConsultaNoEncontradaError):
        construir_contexto_clinico(conn, 9999)


# ---------------------------------------------------------------------------
# construir_contexto_resumen_caso (IA-04)
# ---------------------------------------------------------------------------
def test_resumen_caso_incluye_diagnostico_estadio_y_hallazgos_de_todo_el_expediente(conn_sembrada):
    conn, ids = conn_sembrada
    contexto = construir_contexto_resumen_caso(conn, ids["paciente_maria"])

    assert contexto.patient_ref == f"paciente-{ids['paciente_maria']}"
    assert contexto.paciente_id == ids["paciente_maria"]
    assert contexto.diagnostico_principal == "Cáncer de mama triple negativo"
    assert contexto.estadio == "II"

    ids_segmentos = {s.id for s in contexto.segments}
    assert f"lab-{ids['lab_maria_1']}" in ids_segmentos
    assert f"imagen-{ids['imagen_maria_1']}" in ids_segmentos
    assert f"biomarcador-{ids['biomarcador_maria_1']}" in ids_segmentos
    # Debe incluir notas de AMBAS consultas de María, no solo la primera
    # (mismo alcance de "todo el expediente" que ya usa DX-02).
    assert any(s.id.startswith(f"consulta-{ids['consulta_maria_1']}-nota-") for s in contexto.segments)
    assert any(s.id.startswith(f"consulta-{ids['consulta_maria_2']}-nota-") for s in contexto.segments)


def test_resumen_caso_paciente_inexistente_lanza_error(conn):
    with pytest.raises(PacienteNoEncontradoError):
        construir_contexto_resumen_caso(conn, 9999)
