"""Orquestación de recomendaciones explicables para el paciente activo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from dx_clinica.builder import construir_diagnosticos_diferenciales
from historia_clinica_mock.repository import HallazgoClinico, Paciente

from .models import ClinicalExplanation
from .service import ExplanationService


@dataclass(frozen=True)
class PatientRecommendations:
    """Resultado explicable y explícitamente acotado a un paciente."""

    patient_id: int
    explanations: tuple[ClinicalExplanation, ...]
    warning: str | None = None


class PatientRecommendationService:
    """Genera las recomendaciones hoy disponibles y las pasa por IA-05.

    En el MVP actual las recomendaciones disponibles provienen de DX-02
    (diagnóstico diferencial). Este orquestador deja un único punto de
    integración para agregar más adelante tratamiento o estadificación.
    """

    def __init__(self, explanation_service: ExplanationService | None = None):
        self.explanation_service = explanation_service or ExplanationService()

    def for_patient(
        self,
        patient: Paciente,
        findings: Sequence[HallazgoClinico],
    ) -> PatientRecommendations:
        # Defensa adicional: jamás razonar con hallazgos de otro paciente.
        scoped_findings = [h for h in findings if h.paciente_id == patient.id]

        result = construir_diagnosticos_diferenciales(patient, scoped_findings)
        explanations = tuple(
            self.explanation_service.explain_differential_candidate(candidate, scoped_findings)
            for candidate in result.candidatos
        )
        return PatientRecommendations(
            patient_id=patient.id,
            explanations=explanations,
            warning=result.advertencia_sin_sustento,
        )
