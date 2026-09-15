"""Generador del resumen clínico de caso (IA-04).

Orquesta:

    1. la construcción directa de las secciones "diagnóstico" y "estadio"
       a partir del expediente estructurado del paciente (sin LLM, ver
       docstring de ``ia_clinica.summary.llm_client``);
    2. la construcción del prompt y la llamada al
       :class:`~ia_clinica.notes.llm_client.LLMClient` para las secciones
       "tratamientos previos" y "estado actual", que sí requieren redactar
       texto a partir de hallazgos no estructurados del expediente;
    3. la misma validación estricta que usa IA-02 (``ClinicalNoteGenerator``)
       para esas dos secciones: ninguna puede contener contenido que no
       cite un fragmento real del expediente (criterio de aceptación de
       IA-04, heredado del principio general de no-alucinación del
       proyecto: "no inventa información clínica");
    4. el marcado explícito de cualquier sección sin información
       suficiente — sea estructurada o derivada — con
       :data:`~ia_clinica.notes.models.MISSING_INFO_MARKER`, nunca con
       texto inventado (criterio de aceptación AC2 de IA-04: "el documento
       indica explícitamente las secciones con datos faltantes").

El resultado siempre es un :class:`~ia_clinica.summary.models.CaseSummary`,
identificado explícitamente como generado por IA, y este módulo no ofrece
ninguna forma de "finalizarlo" o marcarlo como documento oficial.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from ia_clinica.notes.llm_client import LLMClient
from ia_clinica.notes.models import MISSING_INFO_MARKER
from ia_clinica.summary.llm_client import build_system_prompt, build_user_prompt
from ia_clinica.summary.models import (
    CaseSummary,
    CaseSummaryContext,
    CaseSummarySection,
    DIAGNOSTICO,
    ESTADIO,
    ESTADO_ACTUAL,
    ETIQUETAS_SECCION,
    ORDEN_SECCIONES,
    TRATAMIENTOS_PREVIOS,
)


class CaseSummaryGenerationError(Exception):
    """Se lanza cuando la respuesta del modelo no puede interpretarse de forma segura.

    Igual que ``ia_clinica.notes.generator.GenerationError``: es preferible
    fallar de forma explícita a arriesgar contenido no verificado en un
    documento que se presentará ante una junta médica.
    """


class CaseSummaryGenerator:
    """Genera resúmenes de caso a partir de un ``CaseSummaryContext``."""

    def __init__(self, llm_client: LLMClient, min_lexical_grounding: float = 0.35) -> None:
        self._llm_client = llm_client
        self._min_lexical_grounding = min_lexical_grounding

    def generate_summary(
        self,
        context: CaseSummaryContext,
        now: Optional[datetime] = None,
    ) -> CaseSummary:
        """Genera el resumen de caso para ``context``.

        Lanza ``ValueError`` si el contexto no tiene absolutamente nada
        registrado (ni datos estructurados ni hallazgos) y
        ``CaseSummaryGenerationError`` si la respuesta del modelo no puede
        validarse de forma segura contra el expediente de entrada.
        """

        if context.is_empty():
            raise ValueError(
                "El paciente no tiene ninguna información registrada en el "
                "expediente: no se puede generar un resumen de caso a partir "
                "de un contexto vacío."
            )

        # -- Secciones estructuradas: directas del expediente, sin LLM. -----
        diagnostico_section = self._structured_section(
            context, DIAGNOSTICO, context.diagnostico_principal
        )
        estadio_section = self._structured_section(context, ESTADIO, context.estadio)

        # -- Secciones derivadas: requieren redactar a partir de hallazgos. -
        warnings: List[str] = []
        if context.segments:
            system_prompt = build_system_prompt()
            user_prompt = build_user_prompt(context)
            raw_response = self._llm_client.complete(system_prompt, user_prompt)
            parsed_sections = self._parse_response(raw_response)
        else:
            # Sin ningún hallazgo del expediente, no tiene sentido llamar al
            # modelo (no hay nada de qué extraer tratamientos/estado): se
            # marcan ambas secciones como faltantes directamente.
            parsed_sections = {}

        tratamientos_section, w1 = self._build_derived_section(
            context, TRATAMIENTOS_PREVIOS, parsed_sections.get(TRATAMIENTOS_PREVIOS)
        )
        estado_section, w2 = self._build_derived_section(
            context, ESTADO_ACTUAL, parsed_sections.get(ESTADO_ACTUAL)
        )
        warnings.extend(w1)
        warnings.extend(w2)

        secciones_por_clave = {
            DIAGNOSTICO: diagnostico_section,
            ESTADIO: estadio_section,
            TRATAMIENTOS_PREVIOS: tratamientos_section,
            ESTADO_ACTUAL: estado_section,
        }
        sections = [secciones_por_clave[key] for key in ORDEN_SECCIONES]

        return CaseSummary(
            patient_ref=context.patient_ref,
            paciente_id=context.paciente_id,
            generated_at=now or datetime.now(),
            sections=sections,
            warnings=warnings,
        )

    # -- Secciones estructuradas (diagnóstico / estadio) --------------------

    @staticmethod
    def _structured_section(
        context: CaseSummaryContext, key: str, valor: Optional[str]
    ) -> CaseSummarySection:
        label = ETIQUETAS_SECCION[key]
        if not valor or not valor.strip():
            return CaseSummarySection(key=key, label=label, content=MISSING_INFO_MARKER, status="missing")
        # Id de trazabilidad sintético: apunta al registro estructurado
        # exacto del paciente del que proviene el valor (no a un fragmento
        # de texto libre, porque no lo es).
        return CaseSummarySection(
            key=key,
            label=label,
            content=valor,
            status="documented",
            source_span_ids=[f"paciente-{context.paciente_id}-{key}"],
        )

    # -- Secciones derivadas (tratamientos previos / estado actual) ---------

    def _parse_response(self, raw_response: str) -> Dict[str, dict]:
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise CaseSummaryGenerationError(
                "La respuesta del modelo no es JSON válido; se descarta en vez de "
                "intentar interpretarla parcialmente."
            ) from exc

        if not isinstance(payload, dict) or "sections" not in payload:
            raise CaseSummaryGenerationError(
                "La respuesta del modelo no tiene la forma esperada ('sections')."
            )

        result: Dict[str, dict] = {}
        for raw_section in payload["sections"]:
            if not isinstance(raw_section, dict) or "key" not in raw_section:
                raise CaseSummaryGenerationError("Una sección de la respuesta del modelo no tiene 'key'.")
            result[raw_section["key"]] = raw_section
        return result

    def _build_derived_section(
        self, context: CaseSummaryContext, key: str, raw_section: Optional[dict]
    ) -> Tuple[CaseSummarySection, List[str]]:
        warnings: List[str] = []
        label = ETIQUETAS_SECCION[key]

        if raw_section is None:
            return (
                CaseSummarySection(key=key, label=label, content=MISSING_INFO_MARKER, status="missing"),
                warnings,
            )

        status = raw_section.get("status")
        content = (raw_section.get("content") or "").strip()
        cited_ids = raw_section.get("source_span_ids") or []

        if status == "missing" or not content:
            return (
                CaseSummarySection(key=key, label=label, content=MISSING_INFO_MARKER, status="missing"),
                warnings,
            )

        valid_ids = [span_id for span_id in cited_ids if context.get_segment(span_id) is not None]
        invalid_ids = [span_id for span_id in cited_ids if span_id not in valid_ids]

        if invalid_ids:
            warnings.append(
                f"Sección '{label}': se descartaron referencias a fragmentos inexistentes {invalid_ids}."
            )

        if not valid_ids:
            warnings.append(
                f"Sección '{label}' descartada: el contenido propuesto no cita ningún fragmento "
                "válido del expediente, por lo que no se puede verificar su origen."
            )
            return (
                CaseSummarySection(key=key, label=label, content=MISSING_INFO_MARKER, status="missing"),
                warnings,
            )

        grounding_score = self._lexical_grounding(context, content, valid_ids)
        if grounding_score < self._min_lexical_grounding:
            warnings.append(
                f"Sección '{label}': el contenido generado comparte poco vocabulario "
                f"con los fragmentos citados (cobertura léxica {grounding_score:.0%}); "
                "se conserva para revisión, pero requiere verificación manual reforzada."
            )

        return (
            CaseSummarySection(
                key=key,
                label=label,
                content=content,
                status="documented",
                source_span_ids=valid_ids,
            ),
            warnings,
        )

    @staticmethod
    def _lexical_grounding(context: CaseSummaryContext, content: str, cited_ids) -> float:
        def significant_tokens(text: str) -> set:
            return {
                token
                for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split()
                if len(token) >= 4
            }

        content_tokens = significant_tokens(content)
        if not content_tokens:
            return 1.0

        source_text = " ".join(context.get_segment(span_id).text for span_id in cited_ids)
        source_tokens = significant_tokens(source_text)

        covered = content_tokens & source_tokens
        return len(covered) / len(content_tokens)


__all__ = ["CaseSummaryGenerator", "CaseSummaryGenerationError"]
