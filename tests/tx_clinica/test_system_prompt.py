"""Pruebas del system prompt.

Las de M6 nacieron de un bug real: una barra invertida al final de línea dentro del
prompt fusionaba dos reglas en una sola viñeta. El prompt ahora se arma uniendo una
lista de reglas (``tx_clinica/prompts/system_prompt.py``), pero la regresión se sigue
vigilando, y la regla accept-vs-modify, que pasó a la skill, se comprueba allí.
Ver también ``test_skill_agente.py`` (reparto entre prompt y skill).
"""
import re
from pathlib import Path

from tx_clinica.prompts.system_prompt import SYSTEM_PROMPT

SKILL = Path(__file__).resolve().parents[2] / "skills" / "ruta-recomendacion-guias"


def _skill_completa() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(SKILL.rglob("*.md")))


def test_m6_no_hay_bullets_fusionados():
    # Antes del fix: "...ya recibido.- PROHIBIDO inventar..." (fusionado,
    # sin separador entre dos reglas distintas).
    assert ".- PROHIBIDO" not in SYSTEM_PROMPT
    assert re.search(r"[.:] ?- [A-ZÁÉÍÓÚ]", SYSTEM_PROMPT) is None


def test_m6_bullets_bien_separados():
    assert "\n- PROHIBIDO inventar" in SYSTEM_PROMPT


def test_m6_la_regla_accept_vs_modify_vive_en_la_skill():
    # Antes estaba en el prompt; ahora es parte del procedimiento (referencia de la skill),
    # y la tool registrar_decision_tratamiento sigue rechazando un accept con otro régimen.
    skill = _skill_completa()
    assert 'tipo_decision="modify"' in skill
    assert "Usa siempre" in skill
