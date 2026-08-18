"""Generador de borradores de nota clínica (IA-02).

Este es el componente central de la historia IA-02. Orquesta:

    1. la construcción del prompt a partir del ``ClinicalContext``
       (observación técnica: "la generación debe realizarse utilizando
       únicamente el contexto clínico autorizado para la consulta");
    2. la llamada al :class:`~ia_clinica.notes.llm_client.LLMClient`;
    3. la validación estricta de la respuesta contra el contexto de
       entrada, para que ninguna sección pueda contener información que
       no provenga de un fragmento real de la consulta (criterio de
       aceptación: "el contenido generado corresponde únicamente a
       información disponible en el contexto clínico proporcionado");
    4. el reemplazo de cualquier sección sin respaldo verificable por el
       marcador fijo de información faltante, nunca por texto inventado
       (criterio de aceptación: "no inventa información clínica").

El resultado siempre es un :class:`~ia_clinica.notes.models.ClinicalNoteDraft`,
que se identifica explícitamente como borrador de IA (criterio de
aceptación restante) y que este módulo no ofrece ninguna forma de
"finalizar" o marcar como nota oficial.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, Optional

from ia_clinica.notes.formats import NoteFormatSpec, get_format
from ia_clinica.notes.llm_client import LLMClient, build_system_prompt, build_user_prompt
from ia_clinica.notes.models import (
    MISSING_INFO_MARKER,
    ClinicalContext,
    ClinicalNoteDraft,
    NoteSectionDraft,
)


class GenerationError(Exception):
    """Se lanza cuando la respuesta del LLM no puede interpretarse de forma segura.

    Deliberadamente NO se intenta "adivinar" o completar una respuesta mal
    formada: es preferible fallar de forma explícita a arriesgar contenido
    no verificado en un borrador clínico.
    """


class ClinicalNoteGenerator:
    """Genera borradores de nota clínica a partir de un ``ClinicalContext``."""

    def __init__(
        self,
        llm_client: LLMClient,
        institution_formats: Optional[Dict[str, NoteFormatSpec]] = None,
        min_lexical_grounding: float = 0.35,
    ) -> None:
        self._llm_client = llm_client
        self._institution_formats = institution_formats or {}
        self._min_lexical_grounding = min_lexical_grounding

    def generate_draft(
        self,
        context: ClinicalContext,
        format_name: str = "SOAP",
        now: Optional[datetime] = None,
    ) -> ClinicalNoteDraft:
        """Genera el borrador estructurado para ``context`` en ``format_name``.

        Lanza ``ValueError`` si el contexto no tiene ninguna información
        registrada (no existe nada a partir de lo cual generar la nota) y
        ``GenerationError`` si la respuesta del LLM no puede validarse de
        forma segura contra el contexto de entrada.
        """

        if context.is_empty():
            raise ValueError(
                "No hay información registrada de la consulta: no se puede generar "
                "un borrador de nota clínica a partir de un contexto vacío."
            )

        format_spec = get_format(format_name, self._institution_formats)

        system_prompt = build_system_prompt(format_spec)
        user_prompt = build_user_prompt(context)
        raw_response = self._llm_client.complete(system_prompt, user_prompt)
        parsed_sections = self._parse_response(raw_response)

        sections = []
        traceability: Dict[str, list] = {}
        warnings: list = []

        for section_spec in format_spec.sections:
            raw_section = parsed_sections.get(section_spec.key)
            section, section_warnings = self._build_section(context, section_spec, raw_section)
            sections.append(section)
            traceability[section_spec.key] = list(section.source_span_ids)
            warnings.extend(section_warnings)

        return ClinicalNoteDraft(
            consult_id=context.consult_id,
            patient_ref=context.patient_ref,
            format_name=format_spec.name,
            generated_at=now or datetime.now(),
            sections=sections,
            traceability=traceability,
            warnings=warnings,
        )

    # -- Validación interna -------------------------------------------------

    def _parse_response(self, raw_response: str) -> Dict[str, dict]:
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise GenerationError(
                "La respuesta del modelo no es JSON válido; se descarta en vez de "
                "intentar interpretarla parcialmente."
            ) from exc

        if not isinstance(payload, dict) or "sections" not in payload:
            raise GenerationError("La respuesta del modelo no tiene la forma esperada ('sections').")

        result: Dict[str, dict] = {}
        for raw_section in payload["sections"]:
            if not isinstance(raw_section, dict) or "key" not in raw_section:
                raise GenerationError("Una sección de la respuesta del modelo no tiene 'key'.")
            result[raw_section["key"]] = raw_section
        return result

    def _build_section(self, context: ClinicalContext, section_spec, raw_section):
        warnings: list = []
        label = section_spec.label

        if raw_section is None:
            # El modelo omitió la sección por completo: se trata igual que
            # "missing", nunca se asume contenido.
            return (
                NoteSectionDraft(key=section_spec.key, label=label, content=MISSING_INFO_MARKER, status="missing"),
                warnings,
            )

        status = raw_section.get("status")
        content = (raw_section.get("content") or "").strip()
        cited_ids = raw_section.get("source_span_ids") or []

        if status == "missing" or not content:
            # Regla de negocio: nunca se inventa contenido para una sección
            # sin información suficiente, sin importar qué haya puesto el
            # modelo en 'content'.
            return (
                NoteSectionDraft(key=section_spec.key, label=label, content=MISSING_INFO_MARKER, status="missing"),
                warnings,
            )

        valid_ids = [span_id for span_id in cited_ids if context.get_segment(span_id) is not None]
        invalid_ids = [span_id for span_id in cited_ids if span_id not in valid_ids]

        if invalid_ids:
            warnings.append(
                f"Sección '{label}': se descartaron referencias a fragmentos inexistentes {invalid_ids}."
            )

        if not valid_ids:
            # Ningún fragmento real de la consulta respalda este contenido:
            # no hay forma de verificar que no sea información inventada,
            # así que se descarta y se marca como faltante, no como
            # "documentada sin fuente".
            warnings.append(
                f"Sección '{label}' descartada: el contenido propuesto no cita ningún fragmento "
                "válido de la consulta, por lo que no se puede verificar su origen."
            )
            return (
                NoteSectionDraft(key=section_spec.key, label=label, content=MISSING_INFO_MARKER, status="missing"),
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
            NoteSectionDraft(
                key=section_spec.key,
                label=label,
                content=content,
                status="documented",
                source_span_ids=valid_ids,
            ),
            warnings,
        )

    @staticmethod
    def _lexical_grounding(context: ClinicalContext, content: str, cited_ids) -> float:
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
