from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .ambiguity import AmbiguityFinding


@dataclass(frozen=True)
class ClinicalDatum:
    """A clinical fact that always preserves provenance metadata."""

    concept: str
    value: str
    observed_at: datetime
    source: str
    source_id: str
    unit: str | None = None
    #: Episodio clínico (consulta) al que pertenece el dato, p. ej. ``"consulta-3"``.
    #: ``None`` si el registro de origen no está vinculado a ninguna consulta.
    episode_id: str | None = None

    @property
    def display_value(self) -> str:
        return f"{self.value} {self.unit}" if self.unit else self.value


@dataclass
class ClinicalRecord:
    """Minimal structured clinical record used by the IA-01 MVP."""

    patient_id: str
    data: list[ClinicalDatum] = field(default_factory=list)


@dataclass(frozen=True)
class QueryResponse:
    """Safe response returned by the query service."""

    answer: str
    found: bool
    concept: str | None = None
    datum: ClinicalDatum | None = None
    #: IA-06: cuando es True, ``answer`` es una solicitud de aclaración y
    #: ``ambiguities`` describe por qué. No se entregó ningún dato clínico.
    needs_clarification: bool = False
    ambiguities: tuple[AmbiguityFinding, ...] = ()
