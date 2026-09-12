"""Modelos de datos para el resumen clínico de caso (IA-04).

Igual que ``ia_clinica.notes`` (IA-02), estos modelos son deliberadamente
independientes de cualquier proveedor de LLM concreto y de la capa de
historia clínica: reciben ya construido el :class:`CaseSummaryContext`
("todo lo disponible del expediente del paciente, autorizado para este
resumen") y no acceden a ninguna otra fuente de datos. Esto es lo que
permite sostener, de forma verificable, que el resumen "corresponde
únicamente a información disponible en el expediente del paciente" —
la misma garantía de no-alucinación que ya exige IA-02, aplicada aquí al
caso completo en vez de a una sola consulta.

Diferencia clave con IA-02: IA-02 razona sobre una *consulta puntual*
(``ClinicalContext``); IA-04 necesita "diagnóstico, estadio, tratamientos
previos y estado actual" del *caso completo*, para poder presentarlo en
junta médica o interconsulta. Por eso ``CaseSummaryContext`` combina:

    - dos campos estructurados que ya existen tal cual en el expediente
      (``diagnostico_principal``, ``estadio``) y que por lo tanto se
      trasladan directamente al resumen, sin pasar por ningún modelo de
      lenguaje (nunca hay nada que "redactar" ni que alucinar en un dato
      que ya está en una columna de la base de datos);
    - los hallazgos clínicos no estructurados de todo el expediente
      (notas de consulta, laboratorios, imagenología, biomarcadores), de
      los que sí hace falta extraer/redactar "tratamientos previos" y
      "estado actual" — ahí es donde participa el generador/LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from ia_clinica.notes.models import MISSING_INFO_MARKER, SourceSpan

#: Aviso que se antepone a todo resumen de caso generado. Igual que
#: ``AI_DRAFT_DISCLAIMER`` de IA-02/IA-03, deja explícito que este
#: documento requiere revisión del oncólogo tratante antes de
#: presentarse formalmente ante una junta médica o interconsulta.
AI_SUMMARY_DISCLAIMER = (
    "RESUMEN GENERADO AUTOMÁTICAMENTE POR IA — para junta médica / "
    "interconsulta. Requiere revisión y confirmación del oncólogo "
    "tratante antes de presentarse formalmente."
)

#: Claves de sección del resumen de caso, en el orden en que se presentan.
DIAGNOSTICO = "diagnostico"
ESTADIO = "estadio"
TRATAMIENTOS_PREVIOS = "tratamientos_previos"
ESTADO_ACTUAL = "estado_actual"

#: Etiquetas legibles de cada sección, usadas tanto en ``to_text`` como en
#: el prompt que construye ``ia_clinica.summary.llm_client``.
ETIQUETAS_SECCION: Dict[str, str] = {
    DIAGNOSTICO: "Diagnóstico",
    ESTADIO: "Estadio",
    TRATAMIENTOS_PREVIOS: "Tratamientos previos",
    ESTADO_ACTUAL: "Estado actual",
}

#: Orden fijo de presentación del resumen (independiente del orden en que
#: se construyan internamente las secciones).
ORDEN_SECCIONES = (DIAGNOSTICO, ESTADIO, TRATAMIENTOS_PREVIOS, ESTADO_ACTUAL)


@dataclass(frozen=True)
class CaseSummaryContext:
    """Información clínica de todo el expediente, autorizada para el resumen.

    Es la única fuente de verdad que el generador puede usar: ni el campo
    estructurado ``diagnostico_principal``/``estadio`` ni ningún segmento
    de ``segments`` puede provenir de otro lado que no sea el expediente
    real del paciente.
    """

    patient_ref: str
    paciente_id: int
    diagnostico_principal: Optional[str]
    estadio: Optional[str]
    segments: List[SourceSpan] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.patient_ref or not self.patient_ref.strip():
            raise ValueError("CaseSummaryContext.patient_ref no puede estar vacío.")
        ids = [s.id for s in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("Los identificadores de SourceSpan deben ser únicos dentro del contexto.")

    def is_empty(self) -> bool:
        """No hay absolutamente nada con qué construir un resumen.

        A diferencia de ``ClinicalContext.is_empty`` (IA-02), aquí no basta
        con que ``segments`` esté vacío: un paciente puede tener diagnóstico
        y estadio registrados sin ninguna nota libre asociada todavía. Solo
        se considera "vacío" cuando no hay absolutamente nada — ni datos
        estructurados ni hallazgos — a partir de lo cual generar algo.
        """

        return not self.segments and not self.diagnostico_principal and not self.estadio

    def get_segment(self, span_id: str) -> Optional[SourceSpan]:
        for segment in self.segments:
            if segment.id == span_id:
                return segment
        return None


@dataclass
class CaseSummarySection:
    """Contenido generado (o marcado como faltante) para una sección del resumen."""

    key: str
    label: str
    content: str
    status: str  # "documented" | "missing"
    source_span_ids: List[str] = field(default_factory=list)

    @property
    def is_documented(self) -> bool:
        return self.status == "documented"


@dataclass
class CaseSummary:
    """Resumen ejecutivo de caso listo para junta médica / interconsulta (IA-04).

    Nunca representa un documento definitivo: no existe (ni existirá dentro
    de este módulo) ninguna operación que lo marque como "aprobado" u
    "oficial". Esa responsabilidad, si el equipo la necesita más adelante,
    pertenecería a un flujo de revisión propio (como el de IA-03 para las
    notas), fuera del alcance de esta historia.
    """

    patient_ref: str
    paciente_id: int
    generated_at: datetime
    sections: List[CaseSummarySection]
    warnings: List[str] = field(default_factory=list)

    #: Siempre verdadero, de solo lectura por convención de este módulo
    #: (sin setter ni método "finalize"/"approve"). Ver docstring de clase.
    is_ai_generated_draft: bool = field(default=True, init=False)
    disclaimer: str = field(default=AI_SUMMARY_DISCLAIMER, init=False)

    def get_section(self, key: str) -> Optional[CaseSummarySection]:
        for section in self.sections:
            if section.key == key:
                return section
        return None

    def secciones_faltantes(self) -> List[str]:
        """Etiquetas de las secciones sin información suficiente (AC2)."""

        return [s.label for s in self.sections if s.status == "missing"]

    def tiene_informacion_incompleta(self) -> bool:
        return len(self.secciones_faltantes()) > 0

    def to_dict(self) -> dict:
        return {
            "patient_ref": self.patient_ref,
            "paciente_id": self.paciente_id,
            "generated_at": self.generated_at.isoformat(),
            "is_ai_generated_draft": self.is_ai_generated_draft,
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
            "secciones_faltantes": self.secciones_faltantes(),
            "warnings": list(self.warnings),
        }

    def to_text(self) -> str:
        """Documento estructurado, listo para presentarse en junta médica.

        Criterio de aceptación (AC2): si hay información incompleta, el
        documento debe indicarlo explícitamente. Por eso, además de que
        cada sección faltante ya lleva ``MISSING_INFO_MARKER`` como
        contenido, se añade un bloque de advertencia visible al inicio del
        documento con la lista de secciones afectadas — para que quede
        claro de un vistazo, sin tener que leer sección por sección.
        """

        lines = [
            f"*** {self.disclaimer} ***",
            "",
            "RESUMEN DE CASO PARA JUNTA MÉDICA / INTERCONSULTA",
            f"Paciente: {self.patient_ref} | Generado: {self.generated_at.isoformat()}",
            "",
        ]

        faltantes = self.secciones_faltantes()
        if faltantes:
            lines.append(
                "⚠ INFORMACIÓN INCOMPLETA — secciones sin datos suficientes en el "
                f"expediente: {', '.join(faltantes)}."
            )
            lines.append("")

        for section in self.sections:
            lines.append(f"[{section.label}]")
            lines.append(section.content)
            lines.append("")

        if self.warnings:
            lines.append("Avisos de generación:")
            for warning in self.warnings:
                lines.append(f"  - {warning}")

        return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "MISSING_INFO_MARKER",
    "AI_SUMMARY_DISCLAIMER",
    "DIAGNOSTICO",
    "ESTADIO",
    "TRATAMIENTOS_PREVIOS",
    "ESTADO_ACTUAL",
    "ETIQUETAS_SECCION",
    "ORDEN_SECCIONES",
    "CaseSummaryContext",
    "CaseSummarySection",
    "CaseSummary",
]
