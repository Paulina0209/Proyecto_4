import json

from ia_clinica.summary.llm_client import (
    CLAVES_SECCION_DERIVADA,
    RuleBasedSummaryLLMClient,
    build_system_prompt,
    build_user_prompt,
)
from ia_clinica.summary.models import ESTADO_ACTUAL, TRATAMIENTOS_PREVIOS


def test_system_prompt_solo_pide_las_dos_secciones_derivadas():
    prompt = build_system_prompt()
    assert TRATAMIENTOS_PREVIOS in prompt
    assert ESTADO_ACTUAL in prompt
    assert CLAVES_SECCION_DERIVADA == (TRATAMIENTOS_PREVIOS, ESTADO_ACTUAL)


def test_system_prompt_prohibe_redactar_diagnostico_y_estadio():
    prompt = build_system_prompt()
    assert "NO redactes diagnóstico ni estadio" in prompt


def test_user_prompt_incluye_fragmentos_y_datos_estructurados(contexto_completo):
    user_prompt = build_user_prompt(contexto_completo)
    payload = json.loads(user_prompt)

    assert payload["diagnostico_principal"] == contexto_completo.diagnostico_principal
    assert payload["estadio"] == contexto_completo.estadio
    assert len(payload["fragments"]) == len(contexto_completo.segments)
    assert {"id", "origin", "text"} <= set(payload["fragments"][0].keys())


class TestRuleBasedSummaryLLMClient:
    def test_clasifica_tratamiento_y_estado_por_palabras_clave(self, contexto_completo):
        cliente = RuleBasedSummaryLLMClient()
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(contexto_completo)

        raw = cliente.complete(system_prompt, user_prompt)
        payload = json.loads(raw)
        secciones = {s["key"]: s for s in payload["sections"]}

        assert set(secciones) == set(CLAVES_SECCION_DERIVADA)
        assert secciones[TRATAMIENTOS_PREVIOS]["status"] == "documented"
        assert "quimioterapia" in secciones[TRATAMIENTOS_PREVIOS]["content"].lower()
        assert secciones[ESTADO_ACTUAL]["status"] == "documented"

    def test_sin_fragmentos_relevantes_marca_missing(self):
        cliente = RuleBasedSummaryLLMClient()
        user_prompt = json.dumps(
            {
                "patient_ref": "paciente-1",
                "diagnostico_principal": "X",
                "estadio": "I",
                "fragments": [{"id": "seg-1", "origin": "consulta", "text": "Paciente asintomático hoy."}],
            }
        )

        raw = cliente.complete(build_system_prompt(), user_prompt)
        payload = json.loads(raw)
        secciones = {s["key"]: s for s in payload["sections"]}

        assert secciones[TRATAMIENTOS_PREVIOS]["status"] == "missing"

    def test_salida_siempre_cita_los_fragmentos_que_usa(self, contexto_completo):
        cliente = RuleBasedSummaryLLMClient()
        raw = cliente.complete(build_system_prompt(), build_user_prompt(contexto_completo))
        payload = json.loads(raw)

        for seccion in payload["sections"]:
            if seccion["status"] == "documented":
                assert len(seccion["source_span_ids"]) > 0
