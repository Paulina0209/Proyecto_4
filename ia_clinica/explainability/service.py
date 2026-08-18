"""Servicio transversal de explicabilidad para salidas clínicas asistidas."""

from __future__ import annotations

from typing import Iterable, Mapping, Optional, Sequence

from dx_clinica.evidence import EvidenceReference
from dx_clinica.models import DiagnosticoDiferencialCandidato
from historia_clinica_mock.repository import HallazgoClinico

from .models import ClinicalExplanation, ConfidenceLevel, EvidenceTrace, PatientFactTrace


def _portable_source_path(path: str) -> str:
    """Devuelve una ruta estable dentro del repositorio, no una ruta local del equipo."""
    normalized = path.replace("\\", "/")
    marker = "/guidelines/"
    if marker in normalized:
        return "guidelines/" + normalized.split(marker, 1)[1]
    if normalized.startswith("guidelines/"):
        return normalized
    return normalized


def _evidence_trace(reference: Optional[EvidenceReference]) -> Optional[EvidenceTrace]:
    if reference is None:
        return None
    return EvidenceTrace(
        module_id=reference.module_id,
        organization=reference.organization,
        title=reference.title,
        publication_year=reference.publication_year,
        doi=reference.doi,
        validation_status=reference.clinical_validation_status,
        source_path=_portable_source_path(reference.ruta_metadata),
    )


def _confidence_and_limitations(
    patient_facts: Sequence[PatientFactTrace],
    evidence: Optional[EvidenceTrace],
    missing_data: Sequence[str],
) -> tuple[ConfidenceLevel, tuple[str, ...]]:
    limitations: list[str] = []

    # Sin datos clínicos trazables no es seguro explicar una recomendación
    # individual para ese paciente.
    if not patient_facts:
        limitations.append("No hay datos clínicos trazables del paciente que sustenten esta recomendación.")

    # IA-05 exige fuente de evidencia; si no existe, no se debe presentar
    # una sugerencia con falsa confianza.
    if evidence is None:
        limitations.append("No hay una guía o fuente de evidencia registrada para sustentar esta recomendación.")

    if missing_data:
        limitations.append(
            "Hay datos/criterios clínicos sin sustento en el expediente: " + "; ".join(missing_data)
        )

    if not patient_facts or evidence is None:
        return ConfidenceLevel.NOT_EVALUABLE, tuple(limitations)

    validation = (evidence.validation_status or "").strip().casefold()
    if validation not in {"validated", "validado", "clinically_validated", "clinical_validated"}:
        limitations.append(
            "La fuente computable usada por el prototipo no tiene validación clínica final registrada "
            f"(estado: {evidence.validation_status or 'no especificado'})."
        )
        return ConfidenceLevel.LOW, tuple(limitations)

    if missing_data:
        return ConfidenceLevel.MEDIUM, tuple(limitations)

    return ConfidenceLevel.HIGH, tuple(limitations)


class ExplanationService:
    """Construye explicaciones sin inventar datos, fuentes ni porcentajes."""

    def build(
        self,
        *,
        recommendation: str,
        source_component: str,
        rationale: str,
        patient_facts: Sequence[PatientFactTrace],
        evidence: Optional[EvidenceTrace],
        missing_data: Sequence[str] = (),
    ) -> ClinicalExplanation:
        confidence, limitations = _confidence_and_limitations(patient_facts, evidence, missing_data)
        return ClinicalExplanation(
            recommendation=recommendation,
            source_component=source_component,
            rationale=rationale,
            patient_facts=tuple(patient_facts),
            evidence=evidence,
            missing_data=tuple(missing_data),
            confidence=confidence,
            limitations=limitations,
        )

    def explain_differential_candidate(
        self,
        candidate: DiagnosticoDiferencialCandidato,
        hallazgos: Iterable[HallazgoClinico],
    ) -> ClinicalExplanation:
        """Adapta una salida DX-02 al contrato transversal de IA-05."""

        hallazgos_by_id: Mapping[str, HallazgoClinico] = {h.id: h for h in hallazgos}
        patient_facts = []
        seen_fact_ids: set[str] = set()
        for fact_id in candidate.hallazgos_ids:
            if fact_id in seen_fact_ids:
                continue
            seen_fact_ids.add(fact_id)
            hallazgo = hallazgos_by_id.get(fact_id)
            if hallazgo is None:
                # Si DX-02 referencia un id que ya no está disponible, IA-05
                # no inventa el contenido: simplemente no lo presenta como trazable.
                continue
            patient_facts.append(
                PatientFactTrace(
                    fact_id=hallazgo.id,
                    value=hallazgo.texto,
                    source_type=hallazgo.origen,
                    date=hallazgo.fecha,
                )
            )

        evidence = _evidence_trace(candidate.evidencia)
        rationale = (
            f"{candidate.resumen_sustento}. La priorización proviene de los criterios "
            "sustentados por hallazgos trazables del expediente; no representa una probabilidad clínica."
        )
        recommendation = f"Considerar como diagnóstico diferencial: {candidate.nombre}"

        return self.build(
            recommendation=recommendation,
            source_component="DX-02",
            rationale=rationale,
            patient_facts=patient_facts,
            evidence=evidence,
            missing_data=candidate.criterios_sin_sustento,
        )
