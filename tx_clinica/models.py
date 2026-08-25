"""Modelos de datos de TX-01/TX-02 (recomendación de tratamiento + nivel de evidencia)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple

#: Aviso fijo, mismo espíritu que DX-02: esto es apoyo a la decisión, no
#: una prescripción automática ni un reemplazo del juicio clínico.
DISCLAIMER = (
    "Estas son opciones de tratamiento sugeridas según la guía clínica configurada "
    "y NO constituyen una prescripción automática. La decisión terapéutica final "
    "es siempre del oncólogo tratante."
)

#: Texto fijo cuando ningún módulo de guías aplica al caso (criterio de
#: aceptación #3 de TX-01: no forzar una sugerencia genérica).
SIN_GUIA_APLICABLE = (
    "No hay un módulo de guía clínica configurado que aplique claramente a este caso "
    "(enfermedad rara o presentación atípica). No se genera una sugerencia genérica."
)


@dataclass(frozen=True)
class TreatmentEvidenceReference:
    """TX-02: nivel de evidencia + fuente exacta de una regla concreta."""

    module_id: str
    organization: str
    title: Optional[str]
    publication_year: Optional[int]
    doi: Optional[str]
    section: Optional[str]
    module_version: Optional[str]
    clinical_validation_status: Optional[str]
    evidence_level: Optional[str]
    recommendation_grade: Optional[str]
    mcbs_score: Optional[str]
    explicit_grade_reported: bool
    ruta_metadata: str
    ruta_regla: str

    def resumen_citable(self) -> str:
        partes = [f"{self.organization} — {self.title or 'título no especificado'}"]
        if self.publication_year:
            partes.append(f"({self.publication_year})")
        grado = []
        if self.evidence_level:
            grado.append(f"nivel de evidencia {self.evidence_level}")
        if self.recommendation_grade:
            grado.append(f"grado de recomendación {self.recommendation_grade}")
        if self.mcbs_score:
            grado.append(f"ESMO-MCBS {self.mcbs_score}")
        if grado:
            partes.append("[" + ", ".join(grado) + "]")
        if not self.explicit_grade_reported:
            partes.append("(grado no reportado explícitamente en la fuente)")
        partes.append(
            f"— validación clínica: {self.clinical_validation_status or 'no especificada'}, "
            f"módulo v{self.module_version or '?'}"
        )
        return " ".join(partes)


@dataclass(frozen=True)
class RegimenCandidato:
    """Un régimen de tratamiento que el motor de reglas respaldaría para este paciente."""

    regimen_id: str
    fase: str
    farmacos: Tuple[str, ...]
    rule_id_disparada: str
    archivo_regla: str
    audit_effect: str  # "supports_prescription" | "requires_clinical_review" | ...
    field_ids_usados: Tuple[str, ...]  # facts reales del paciente usados en la evaluación
    evidencia: Optional[TreatmentEvidenceReference]

    @property
    def es_primera_opcion(self) -> bool:
        return self.audit_effect == "supports_prescription"


@dataclass(frozen=True)
class ResultadoRecomendacionTratamiento:
    """Resultado completo devuelto al oncólogo para un paciente."""

    patient_id: int
    module_id: Optional[str]
    generado_en: datetime
    candidatos: Tuple[RegimenCandidato, ...]
    sin_guia_aplicable: bool = False

    disclaimer: str = field(default=DISCLAIMER, init=False)

    def esta_vacio(self) -> bool:
        return len(self.candidatos) == 0
