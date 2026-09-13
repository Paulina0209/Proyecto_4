"""Tests de ensamblaje de tx_clinica/tools/__init__.py y
tx_clinica/middleware/human_in_the_loop.py.

No invoca Ollama ni construye el agente completo (create_agent con un
LLM real no se puede probar sin un servidor Ollama corriendo) -- esto
solo confirma que la LISTA de tools está bien armada y que la
configuración del middleware apunta a la tool correcta. Ver el plan de
continuidad para lo que sigue pendiente de probar contra Ollama real.
"""

from __future__ import annotations

from tx_clinica.middleware.human_in_the_loop import (
    TOOLS_QUE_REQUIEREN_APROBACION_HUMANA,
    construir_middleware_aprobacion_humana,
)
from tx_clinica.tools import TOOLS


def test_tools_trae_las_8_tools_esperadas():
    nombres = {t.name for t in TOOLS}
    assert nombres == {
        "obtener_datos_paciente",
        "obtener_recomendaciones_tratamiento_por_id",
        "completar_datos_paciente_y_recomendar",
        "obtener_recomendaciones_tratamiento_con_datos",
        "listar_variables_requeridas",
        "consultar_medicacion_actual",
        "chequear_interacciones_tratamiento",
        "registrar_decision_tratamiento",
    }


def test_todas_las_tools_tienen_docstring_no_vacio():
    """El LLM decide cuándo llamar cada tool a partir de su descripción
    -- una tool sin docstring (o con uno vacío) es invisible para el
    modelo, o peor, ambigua."""
    for t in TOOLS:
        assert t.description and len(t.description.strip()) > 20, f"{t.name} sin descripción útil"


def test_solo_registrar_decision_tratamiento_requiere_aprobacion_humana():
    """Las tools de solo lectura NUNCA deben quedar bajo aprobación
    humana -- eso sería fricción sin ningún beneficio de seguridad."""
    assert set(TOOLS_QUE_REQUIEREN_APROBACION_HUMANA.keys()) == {"registrar_decision_tratamiento"}
    assert TOOLS_QUE_REQUIEREN_APROBACION_HUMANA["registrar_decision_tratamiento"] is True


def test_middleware_se_construye_sin_error():
    middleware = construir_middleware_aprobacion_humana()
    assert middleware is not None
