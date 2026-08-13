"""Formatos estructurados de nota clínica.

El criterio de aceptación de IA-02 exige generar "un borrador estructurado
en formato SOAP o en el estándar configurado". Este módulo modela ambos
casos: ``SOAP_FORMAT`` es el formato por defecto, y ``get_format`` permite
resolver un formato distinto configurado por la institución sin tocar el
generador.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class NoteSectionSpec:
    """Definición de una sección esperada dentro de un formato de nota."""

    key: str
    label: str
    #: Instrucción clínica de qué tipo de información pertenece a esta
    #: sección. Se usa para construir el prompt del LLM.
    guidance: str


@dataclass(frozen=True)
class NoteFormatSpec:
    """Definición completa de un formato de nota clínica (p. ej. SOAP)."""

    name: str
    sections: Tuple[NoteSectionSpec, ...]

    def __post_init__(self) -> None:
        if not self.sections:
            raise ValueError(f"El formato '{self.name}' debe tener al menos una sección.")
        keys = [s.key for s in self.sections]
        if len(keys) != len(set(keys)):
            raise ValueError(f"El formato '{self.name}' tiene claves de sección duplicadas.")

    def section_keys(self) -> Tuple[str, ...]:
        return tuple(s.key for s in self.sections)


SOAP_FORMAT = NoteFormatSpec(
    name="SOAP",
    sections=(
        NoteSectionSpec(
            key="S",
            label="Subjetivo",
            guidance=(
                "Motivo de consulta, síntomas referidos por el paciente y "
                "antecedentes mencionados explícitamente durante la consulta."
            ),
        ),
        NoteSectionSpec(
            key="O",
            label="Objetivo",
            guidance=(
                "Hallazgos objetivos registrados en la consulta: examen "
                "físico, signos vitales, resultados de laboratorio o "
                "estudios mencionados explícitamente."
            ),
        ),
        NoteSectionSpec(
            key="A",
            label="Análisis",
            guidance=(
                "Impresión diagnóstica o evaluación clínica que el "
                "oncólogo haya expresado durante la consulta."
            ),
        ),
        NoteSectionSpec(
            key="P",
            label="Plan",
            guidance=(
                "Plan de manejo, indicaciones, estudios solicitados o "
                "seguimiento acordado según lo expresado en la consulta."
            ),
        ),
    ),
)

#: Registro de formatos disponibles por defecto. Las instituciones pueden
#: añadir o sobreescribir formatos pasando ``institution_formats`` a
#: ``get_format`` sin modificar este módulo.
_DEFAULT_FORMATS: Dict[str, NoteFormatSpec] = {SOAP_FORMAT.name: SOAP_FORMAT}


def get_format(
    name: str = "SOAP",
    institution_formats: Optional[Dict[str, NoteFormatSpec]] = None,
) -> NoteFormatSpec:
    """Resuelve un formato de nota por nombre.

    Busca primero en ``institution_formats`` (el estándar configurado por
    la institución, si existe) y luego en los formatos por defecto
    (actualmente solo SOAP). Lanza ``ValueError`` si el nombre no está
    registrado en ninguno de los dos, en vez de asumir silenciosamente un
    formato por defecto distinto al solicitado.
    """

    if institution_formats and name in institution_formats:
        return institution_formats[name]
    if name in _DEFAULT_FORMATS:
        return _DEFAULT_FORMATS[name]
    disponibles = sorted(set(_DEFAULT_FORMATS) | set(institution_formats or {}))
    raise ValueError(
        f"Formato de nota '{name}' no está configurado. Formatos disponibles: {disponibles}."
    )
