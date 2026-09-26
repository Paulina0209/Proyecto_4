"""Prueba de Fase 1 para M6 (bug real de la barra invertida en el prompt)."""
from tx_clinica.prompts.system_prompt import SYSTEM_PROMPT


def test_m6_no_hay_bullets_fusionados():
    # Antes del fix: "...ya recibido.- PROHIBIDO inventar..." (fusionado,
    # sin separador entre dos reglas distintas).
    assert ".- PROHIBIDO" not in SYSTEM_PROMPT


def test_m6_bullets_bien_separados():
    assert "ya recibido.\n- PROHIBIDO inventar" in SYSTEM_PROMPT


def test_m6_agrega_regla_accept_vs_modify():
    assert 'tipo_decision="modify"' in SYSTEM_PROMPT
    assert "usa SIEMPRE" in SYSTEM_PROMPT
