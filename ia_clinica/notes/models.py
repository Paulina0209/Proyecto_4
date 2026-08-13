"""Modelos de datos para la generación de notas clínicas (IA-02).

Estos modelos son deliberadamente independientes de cualquier proveedor de
LLM concreto y de la capa de historia clínica (HC-01/02/04) o del asistente
conversacional (IA-01): reciben ya construido el "contexto clínico
autorizado para la consulta" y no acceden a ninguna otra fuente de datos.
Esto es lo que permite garantizar, de forma verificable, que "el contenido
generado corresponde únicamente a información disponible en el contexto
clínico proporcionado" (criterio de aceptación de IA-02).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

#: Patrón usado por ``ClinicalContext.from_text`` para separar un texto
#: libre (p. ej. un párrafo dictado de una sola vez) en oraciones. Se hace
#: sobre puntuación de cierre de oración seguida de espacio, y también
#: sobre saltos de línea, para no depender de que quien registra la
#: consulta la redacte ya fragmentada.
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")

#: Texto fijo usado cuando falta información para completar una sección.
#: Es intencionalmente constante e importado por el generador: así se evita
#: que cualquier variación de redacción del LLM termine "rellenando" una
#: sección con contenido que parezca información clínica real.
MISSING_INFO_MARKER = "Información no disponible en el contexto clínico proporcionado."

#: Aviso que se antepone a todo borrador generado. Ver criterio de
#: aceptación: "el resultado queda identificado explícitamente como un
#: borrador generado por IA".
AI_DRAFT_DISCLAIMER = (
    "BORRADOR GENERADO AUTOMÁTICAMENTE POR IA — no es una nota clínica "
    "definitiva. Requiere revisión, corrección si aplica y confirmación "
    "explícita del oncólogo tratante antes de formar parte del expediente "
    "oficial del paciente."
)


@dataclass(frozen=True)
class SourceSpan:
    """Un fragmento atómico y trazable de la información de la consulta.

    Puede provenir de una transcripción de la consulta, de un resumen
    dictado por el oncólogo, o de cualquier otra fuente registrada durante
    el encuentro clínico. Cada fragmento tiene un identificador único que
    el generador usa para poder citar exactamente qué parte de la consulta
    respalda cada frase del borrador (trazabilidad entrada → borrador).
    """

    id: str
    text: str
    origin: str = "transcripcion_consulta"
    timestamp: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("SourceSpan.id no puede estar vacío.")
        if not self.text or not self.text.strip():
            raise ValueError("SourceSpan.text no puede estar vacío.")


@dataclass(frozen=True)
class ClinicalContext:
    """Información clínica disponible y autorizada para una consulta.

    Es la única fuente de verdad que el generador puede usar. No contiene
    ninguna referencia a datos externos (historia previa, guías clínicas,
    conocimiento general): eso es intencional, para poder sostener el
    criterio de aceptación de IA-02 sobre no usar información fuera del
    contexto de la consulta.
    """

    consult_id: str
    patient_ref: str
    segments: List[SourceSpan] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.consult_id or not self.consult_id.strip():
            raise ValueError("ClinicalContext.consult_id no puede estar vacío.")
        if not self.patient_ref or not self.patient_ref.strip():
            raise ValueError("ClinicalContext.patient_ref no puede estar vacío.")
        ids = [s.id for s in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("Los identificadores de SourceSpan deben ser únicos dentro del contexto.")

    def is_empty(self) -> bool:
        return len(self.segments) == 0

    @classmethod
    def from_text(
        cls,
        consult_id: str,
        patient_ref: str,
        text: str,
        origin: str = "transcripcion_consulta",
        timestamp: Optional[str] = None,
    ) -> "ClinicalContext":
        """Construye un contexto a partir de un texto libre (un párrafo, un dictado).

        No es obligatorio que quien registra la consulta entregue la
        información ya separada por tema: esta función la trocea en
        oraciones automáticamente, cada una con su propio identificador de
        trazabilidad (``seg-1``, ``seg-2``, ...), para que un LLM real (o el
        cliente de referencia basado en reglas) pueda clasificar cada
        oración en la sección correcta en vez de recibir un único bloque de
        texto sin distinción interna.

        Esto es una conveniencia de segmentación, no un cambio en la regla
        de negocio: el generador sigue validando cada sección contra estos
        mismos fragmentos, así que la trazabilidad resultante es a nivel de
        oración en vez de a nivel de párrafo completo.
        """

        sentences = [s.strip() for s in _SENTENCE_SPLIT_PATTERN.split(text) if s.strip()]
        segments = [
            SourceSpan(id=f"seg-{i}", text=sentence, origin=origin, timestamp=timestamp)
            for i, sentence in enumerate(sentences, start=1)
        ]
        return cls(consult_id=consult_id, patient_ref=patient_ref, segments=segments)

    def get_segment(self, span_id: str) -> Optional[SourceSpan]:
        for segment in self.segments:
            if segment.id == span_id:
                return segment
        return None

    def full_text(self) -> str:
        return "\n".join(segment.text for segment in self.segments)


@dataclass
class NoteSectionDraft:
    """Contenido generado (o marcado como faltante) para una sección de la nota."""

    key: str
    label: str
    content: str
    status: str  # "documented" | "missing" | "ungrounded"
    source_span_ids: List[str] = field(default_factory=list)

    @property
    def is_documented(self) -> bool:
        return self.status == "documented"


@dataclass
class ClinicalNoteDraft:
    """Borrador estructurado de nota clínica generado por el agente de IA.

    Nunca representa una nota definitiva: no existe (ni existirá dentro de
    este módulo) una operación que cambie ``is_ai_generated_draft`` o
    ``status`` para marcarla como "oficial". Esa responsabilidad pertenece
    al flujo de firma/aprobación del oncólogo (fuera del alcance de IA-02).
    """

    consult_id: str
    patient_ref: str
    format_name: str
    generated_at: datetime
    sections: List[NoteSectionDraft]
    traceability: Dict[str, List[str]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    #: Siempre verdadero. Se expone como atributo (no como método) para que
    #: cualquier consumidor (UI, API, auditoría) pueda verificarlo de forma
    #: trivial, pero es de solo lectura por convención de este módulo: no se
    #: ofrece ningún setter ni método "finalize"/"sign" en esta historia.
    is_ai_generated_draft: bool = field(default=True, init=False)
    status: str = field(default="borrador_ia_no_confirmado", init=False)
    disclaimer: str = field(default=AI_DRAFT_DISCLAIMER, init=False)

    def get_section(self, key: str) -> Optional[NoteSectionDraft]:
        for section in self.sections:
            if section.key == key:
                return section
        return None

    def to_dict(self) -> dict:
        return {
            "consult_id": self.consult_id,
            "patient_ref": self.patient_ref,
            "format_name": self.format_name,
            "generated_at": self.generated_at.isoformat(),
            "is_ai_generated_draft": self.is_ai_generated_draft,
            "status": self.status,
            "disclaimer": self.disclaimer,
            "sections": [
                {
                    "key": s.key,
                    "label": s.label,
                    "content": s.content,
                    "status": s.status,
                    "source_span_ids": list(s.source_span_ids),
                }
                for s in self.sections
            ],
            "traceability": {k: list(v) for k, v in self.traceability.items()},
            "warnings": list(self.warnings),
        }

    def to_text(self) -> str:
        lines = [
            f"*** {self.disclaimer} ***",
            "",
            f"Formato: {self.format_name}",
            f"Consulta: {self.consult_id} | Paciente: {self.patient_ref}",
            f"Generado: {self.generated_at.isoformat()}",
            "",
        ]
        for section in self.sections:
            lines.append(f"[{section.label}]")
            lines.append(section.content)
            lines.append("")
        if self.warnings:
            lines.append("Avisos de generación:")
            for warning in self.warnings:
                lines.append(f"  - {warning}")
        return "\n".join(lines).rstrip() + "\n"
