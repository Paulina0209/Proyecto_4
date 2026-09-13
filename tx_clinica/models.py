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
#: aceptación #3 de TX-01: no forzar una sugerencia genérica). Esto es
#: una negativa REAL -- ningún módulo aplicaría aunque se completaran
#: todos los datos. Distinto de FALTAN_DATOS_PARA_DETERMINAR_GUIA.
SIN_GUIA_APLICABLE = (
    "No hay un módulo de guía clínica configurado que aplique claramente a este caso "
    "(enfermedad rara o presentación atípica). No se genera una sugerencia genérica."
)

#: Texto fijo para la Fase 1 de la recomendación cuando NO se pudo
#: determinar si hay guía aplicable porque falta al menos un dato clínico
#: necesario para evaluar la elegibilidad de uno o más módulos candidatos
#: -- a diferencia de SIN_GUIA_APLICABLE, aquí el sistema no sabe todavía
#: si hay guía aplicable o no. Nunca se debe reportar sin_guia_aplicable
#: en este caso: eso implicaría una negativa que el sistema no puede
#: sostener con los datos que tiene.
FALTAN_DATOS_PARA_DETERMINAR_GUIA = (
    "No se puede determinar todavía si hay una guía clínica aplicable a este caso "
    "porque falta al menos un dato clínico necesario. Complete los datos solicitados "
    "para que el sistema pueda evaluarlo."
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
    field_ids_usados: Tuple[str, ...]  # facts REALMENTE evaluados por la regla ganadora
    evidencia: Optional[TreatmentEvidenceReference]
    #: Distinto de None cuando este candidato solo aparece porque, SIN la
    #: comorbilidad registrada, calificaría como primera línea -- criterio
    #: de aceptación #2 de TX-01: "no se presenta como primera línea, O SE
    #: PRESENTA CON LA ADVERTENCIA CORRESPONDIENTE". El texto cita la
    #: variable y el valor real del paciente que causó la exclusión, nunca
    #: uno inventado.
    advertencia_comorbilidad: Optional[str] = None

    @property
    def es_primera_opcion(self) -> bool:
        return self.audit_effect == "supports_prescription" and self.advertencia_comorbilidad is None


@dataclass(frozen=True)
class ResultadoRecomendacionTratamiento:
    """Resultado completo devuelto al oncólogo para un paciente."""

    #: None cuando el caso se describió en el chat sin paciente
    #: registrado en la base de datos -- antes se usaba -1 como
    #: centinela, ambiguo con un id real mal tecleado. None es explícito.
    patient_id: Optional[int]
    module_id: Optional[str]
    generado_en: datetime
    candidatos: Tuple[RegimenCandidato, ...]
    sin_guia_aplicable: bool = False
    #: Fase 1: True cuando no se pudo determinar si hay guía aplicable
    #: por falta de datos (distinto de sin_guia_aplicable=True, que es
    #: una negativa real). Si esto es True, candidatos siempre está vacío
    #: y sin_guia_aplicable siempre es False -- son mutuamente excluyentes.
    faltan_datos_para_determinar_guia: bool = False
    #: Solo poblado cuando faltan_datos_para_determinar_guia=True.
    variables_faltantes_por_modulo: dict = field(default_factory=dict)

    disclaimer: str = field(default=DISCLAIMER, init=False)

    def esta_vacio(self) -> bool:
        return len(self.candidatos) == 0