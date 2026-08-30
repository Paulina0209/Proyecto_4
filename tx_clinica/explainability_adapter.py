"""Adapta un RegimenCandidato (TX-01) al contrato de IA-05 (ExplanationService).

No modifica ia_clinica.explainability (models.py/service.py) en absoluto —
ese código no es de este módulo. Este archivo es el equivalente, para
tratamiento, de lo que ia_clinica.explainability.patient_service.py ya
hace para DX-02: traduce el candidato específico del dominio a los tipos
neutros (PatientFactTrace / EvidenceTrace) que ExplanationService espera.

Nota sobre una limitación conocida del modelo de IA-05 (no se resuelve
aquí, se documenta): ClinicalExplanation solo tiene `missing_data` para
razones de incertidumbre — no distingue "falta un dato" de "hay un dato
que activó una condición de exclusión/revisión". Mientras eso no cambie
en ia_clinica.explainability, un candidato con audit_effect =
'requires_clinical_review' se comunica dentro del propio `rationale`
(texto), no se fuerza dentro de `missing_data`, para no describir mal lo
que ese campo significa.
"""

from __future__ import annotations

from typing import Any, Mapping

from ia_clinica.explainability.models import PatientFactTrace
from ia_clinica.explainability.service import ExplanationService, EvidenceTrace

from tx_clinica.models import RegimenCandidato


def _evidence_trace(candidato: RegimenCandidato) -> EvidenceTrace | None:
    ev = candidato.evidencia
    if ev is None:
        return None
    return EvidenceTrace(
        module_id=ev.module_id,
        organization=ev.organization,
        title=ev.title or "título no especificado",
        publication_year=ev.publication_year,
        doi=ev.doi,
        validation_status=ev.clinical_validation_status,
        source_path=ev.ruta_regla,
    )


def explain_treatment_candidate(
    explanation_service: ExplanationService,
    candidato: RegimenCandidato,
    facts_paciente: Mapping[str, Any],
) -> "ClinicalExplanation":  # noqa: F821 - tipo de ia_clinica.explainability.models
    patient_facts = tuple(
        PatientFactTrace(fact_id=k, value=str(v), source_type="historia_clinica_mock", date=None)
        for k, v in facts_paciente.items()
        if k in candidato.field_ids_usados
    )

    recommendation = f"Considerar régimen: {candidato.regimen_id} (fase: {candidato.fase})"

    if candidato.audit_effect == "requires_clinical_review":
        rationale = (
            f"El régimen {candidato.regimen_id} se identificó vía la regla {candidato.rule_id_disparada}, "
            "pero requiere revisión clínica antes de considerarse primera línea "
            "(ver limitaciones)."
        )
        missing_data: tuple[str, ...] = ()
    else:
        rationale = (
            f"Régimen respaldado por la regla {candidato.rule_id_disparada} "
            f"({candidato.archivo_regla}) del módulo aplicable, dado el estadio/biomarcadores del paciente."
        )
        missing_data = ()

    return explanation_service.build(
        recommendation=recommendation,
        source_component="TX-01",
        rationale=rationale,
        patient_facts=patient_facts,
        evidence=_evidence_trace(candidato),
        missing_data=missing_data,
    )
