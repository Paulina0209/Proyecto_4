"""Modelos comunes para IA-05 — Explicabilidad de recomendaciones."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class ConfidenceLevel(str, Enum):
    """Nivel cualitativo y auditable; NO representa probabilidad clínica."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NOT_EVALUABLE = "NOT_EVALUABLE"


@dataclass(frozen=True)
class PatientFactTrace:
    """Dato del paciente usado en una recomendación, con trazabilidad a su origen."""

    fact_id: str
    value: str
    source_type: str
    date: Optional[str] = None


@dataclass(frozen=True)
class EvidenceTrace:
    """Fuente externa/guía que sustenta una recomendación."""

    module_id: str
    organization: str
    title: str
    publication_year: Optional[int]
    doi: Optional[str]
    validation_status: Optional[str]
    source_path: str


@dataclass(frozen=True)
class ClinicalExplanation:
    """Explicación verificable de una salida clínica asistida."""

    recommendation: str
    source_component: str
    rationale: str
    patient_facts: Tuple[PatientFactTrace, ...]
    evidence: Optional[EvidenceTrace]
    missing_data: Tuple[str, ...]
    confidence: ConfidenceLevel
    limitations: Tuple[str, ...]

    @property
    def has_traceable_patient_data(self) -> bool:
        return bool(self.patient_facts) and all(f.fact_id and f.source_type for f in self.patient_facts)

    @property
    def has_evidence(self) -> bool:
        return self.evidence is not None

    @property
    def explicitly_reports_uncertainty(self) -> bool:
        return self.confidence != ConfidenceLevel.HIGH or bool(self.limitations) or bool(self.missing_data)
