"""Cliente LLM local (Ollama) para redactar el rationale de TX-01.

Mismo contrato conceptual que ia_clinica.notes.llm_client.LLMClient:
el LLM solo redacta texto a partir de datos ya estructurados y
validados por el motor determinista (tx_clinica.builder). Nunca decide
qué régimen es correcto ni qué evidencia citar — eso ya viene resuelto
en el RegimenCandidato antes de llegar aquí.

Requiere Ollama corriendo localmente (`ollama serve`, por defecto en
http://localhost:11434) y el modelo ya descargado:

    ollama pull qwen2.5:14b-instruct-q4_K_M
"""

from __future__ import annotations

from typing import Any, Mapping

import requests

from tx_clinica.models import RegimenCandidato


class LLMClient:
    """Interfaz mínima. Cualquier implementación debe respetar: nunca
    introducir un regimen_id o evidencia que no venga en el candidato."""

    def generar_rationale(self, candidato: RegimenCandidato, facts_paciente: Mapping[str, Any]) -> str:
        raise NotImplementedError


_SYSTEM_PROMPT = (
    "Redactas en español la justificación de una recomendación de tratamiento "
    "oncológico que YA fue decidida por un motor de reglas determinista. "
    "Usa EXCLUSIVAMENTE los datos que se te dan en el mensaje del usuario "
    "(régimen, fase, regla que se disparó, evidencia). "
    "No sugieras regímenes distintos al indicado. "
    "No menciones ninguna evidencia, guía, nivel o grado que no esté "
    "explícitamente en el texto que se te da. "
    "Si algo no está en los datos proporcionados, di que no está disponible "
    "en vez de inferirlo o inventarlo. "
    "Sé breve: 2-4 oraciones."
)


class LocalOllamaLLMClient(LLMClient):
    def __init__(
        self,
        model: str = "qwen2.5:14b-instruct-q4_K_M",
        base_url: str = "http://localhost:11434",
        timeout: int = 60,
    ):
        self.model = model
        self.base_url = base_url
        self.timeout = timeout

    def _build_user_prompt(self, candidato: RegimenCandidato, facts_paciente: Mapping[str, Any]) -> str:
        evidencia_texto = candidato.evidencia.resumen_citable() if candidato.evidencia else "no hay evidencia registrada"
        return (
            f"Régimen: {candidato.regimen_id}\n"
            f"Fase: {candidato.fase}\n"
            f"Fármacos incluidos: {', '.join(candidato.farmacos)}\n"
            f"Regla que se disparó: {candidato.rule_id_disparada} (archivo: {candidato.archivo_regla})\n"
            f"Efecto de auditoría: {candidato.audit_effect}\n"
            f"Evidencia: {evidencia_texto}\n"
            f"Datos del paciente considerados: "
            f"{', '.join(f'{k}={facts_paciente[k]}' for k in candidato.field_ids_usados if k in facts_paciente)}\n"
        )

    def generar_rationale(self, candidato: RegimenCandidato, facts_paciente: Mapping[str, Any]) -> str:
        prompt = self._build_user_prompt(candidato, facts_paciente)
        response = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.1},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        texto = response.json()["message"]["content"]
        _validar_sin_regimen_ajeno(texto, candidato)
        return texto


def _validar_sin_regimen_ajeno(texto_generado: str, candidato: RegimenCandidato) -> None:
    """Chequeo mínimo post-generación: el texto debe mencionar el regimen_id real.

    No es una validación exhaustiva de alucinación (eso requeriría NLI o
    similar), pero atrapa el caso más grave: que el modelo redacte sobre
    un régimen completamente distinto al que el motor determinista eligió.
    """
    if candidato.regimen_id.replace("_", " ") not in texto_generado.replace("_", " ").lower() and \
       candidato.regimen_id not in texto_generado:
        raise ValueError(
            f"El texto generado no menciona el regimen_id '{candidato.regimen_id}' esperado; "
            "se descarta para no presentar un rationale posiblemente desalineado."
        )
