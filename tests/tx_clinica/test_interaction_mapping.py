"""Pruebas de D7: mapear_medicacion_actual_a_variables ahora devuelve
False explícito para las variables del catálogo que no matchearon, no
solo True para las que sí."""
from interacciones_farmacologicas.interaction_mapping import (
    MAPEO_MEDICAMENTO_A_VARIABLES,
    mapear_medicacion_actual_a_variables,
)


def test_d7_variable_no_matcheada_es_false_explicito_no_ausente():
    variables, no_mapeados = mapear_medicacion_actual_a_variables(["rifampicina"])
    assert variables["concomitant_strong_cyp3a4_inducer"] is True  # rifampicina sí la activa
    assert variables["concomitant_qt_prolonging_agent"] is False  # NO ausente: False confirmado
    assert no_mapeados == []


def test_d7_todas_las_variables_del_catalogo_estan_presentes_sin_medicacion():
    variables, _ = mapear_medicacion_actual_a_variables([])
    todas = {v for lista in MAPEO_MEDICAMENTO_A_VARIABLES.values() for v in lista}
    assert set(variables) == todas
    assert all(v is False for v in variables.values())


def test_d7_medicamento_no_catalogado_no_afecta_las_variables_conocidas():
    variables, no_mapeados = mapear_medicacion_actual_a_variables(["suplemento_x"])
    assert no_mapeados == ["suplemento_x"]
    assert all(v is False for v in variables.values())


def test_d7_normalizacion_con_tildes_sigue_funcionando():
    variables, _ = mapear_medicacion_actual_a_variables(["Rifampicina"])
    assert variables["concomitant_strong_cyp3a4_inducer"] is True
