"""Tests de ensamblaje de tx_clinica/tools/__init__.py y
tx_clinica/middleware/human_in_the_loop.py.

No invoca el LLM ni construye el agente completo (create_agent con un
LLM real no se puede probar sin llamar a la API de OpenAI) -- esto
solo confirma que la LISTA de tools está bien armada y que la
configuración del middleware apunta a la tool correcta. Ver el plan de
continuidad para lo que sigue pendiente de probar contra el modelo real.
"""

from __future__ import annotations

from tx_clinica.middleware.human_in_the_loop import (
    TOOLS_QUE_REQUIEREN_APROBACION_HUMANA,
    construir_middleware_aprobacion_humana,
)
from tx_clinica.tools import TOOLS


TOOLS_DE_LECTURA = {
    "obtener_datos_paciente",
    "obtener_recomendaciones_tratamiento_por_id",
    "completar_datos_paciente_y_recomendar",
    "obtener_recomendaciones_tratamiento_con_datos",
    "listar_variables_requeridas",
    "consultar_medicacion_actual",
    "chequear_interacciones_tratamiento",
}
TOOLS_QUE_ESCRIBEN = {
    "registrar_decision_tratamiento",
    "registrar_datos_clinicos_paciente",
    "registrar_conciliacion_medicamentos",
}


def test_tools_trae_las_10_tools_esperadas():
    assert {t.name for t in TOOLS} == TOOLS_DE_LECTURA | TOOLS_QUE_ESCRIBEN


def test_todas_las_tools_tienen_docstring_no_vacio():
    """El LLM decide cuándo llamar cada tool a partir de su descripción
    -- una tool sin docstring (o con uno vacío) es invisible para el
    modelo, o peor, ambigua."""
    for t in TOOLS:
        assert t.description and len(t.description.strip()) > 20, f"{t.name} sin descripción útil"


def test_toda_tool_que_escribe_requiere_aprobacion_y_ninguna_de_lectura():
    """Todo lo que escribe en el expediente pasa por aprobación humana; las
    tools de solo lectura NUNCA -- eso sería fricción sin beneficio."""
    assert set(TOOLS_QUE_REQUIEREN_APROBACION_HUMANA) == TOOLS_QUE_ESCRIBEN
    assert all(v is True for v in TOOLS_QUE_REQUIEREN_APROBACION_HUMANA.values())
    assert not TOOLS_DE_LECTURA & set(TOOLS_QUE_REQUIEREN_APROBACION_HUMANA)


def test_middleware_se_construye_sin_error():
    middleware = construir_middleware_aprobacion_humana()
    assert middleware is not None
