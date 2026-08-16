"""Modelos de datos del resultado de diagnóstico diferencial (DX-02)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

from dx_clinica.evidence import EvidenceReference

#: Aviso fijo que acompaña todo resultado. Ver regla de negocio de DX-02:
#: "La lista generada no constituye un diagnóstico definitivo y no
#: reemplaza el juicio clínico del médico."
DISCLAIMER = (
    "Este resultado es apoyo a la decisión clínica (posibles diagnósticos "
    "diferenciales a considerar según la información disponible) y NO "
    "constituye un diagnóstico definitivo. La decisión diagnóstica final "
    "es siempre del oncólogo tratante."
)

#: Texto fijo usado cuando ninguna alternativa del catálogo tiene sustento
#: real en los hallazgos del paciente. Nunca se fuerza una lista vacía a
#: mostrar candidatos sin respaldo verificable.
SIN_SUSTENTO_SUFICIENTE = (
    "No hay suficiente información clínica registrada en el expediente para "
    "sustentar ninguna alternativa diagnóstica del catálogo disponible."
)


@dataclass(frozen=True)
class CriterioEvaluado:
    """Un criterio clínico de un perfil diagnóstico, ya evaluado contra el expediente."""

    id: str
    descripcion: str
    hallazgos_ids: Tuple[str, ...]


@dataclass(frozen=True)
class DiagnosticoDiferencialCandidato:
    """Una alternativa diagnóstica sustentada por al menos un hallazgo real."""

    perfil_id: str
    nombre: str
    orden: int  # posición 1-based dentro de la lista priorizada (nunca un porcentaje)
    criterios_sustentados: Tuple[CriterioEvaluado, ...]
    criterios_sin_sustento: Tuple[str, ...]  # descripciones de lo que falta para reforzar esta alternativa
    evidencia: Optional[EvidenceReference]

    @property
    def hallazgos_ids(self) -> List[str]:
        ids: List[str] = []
        for criterio in self.criterios_sustentados:
            ids.extend(criterio.hallazgos_ids)
        return ids

    @property
    def resumen_sustento(self) -> str:
        return f"{len(self.criterios_sustentados)} de {len(self.criterios_sustentados) + len(self.criterios_sin_sustento)} criterios clínicos sustentados"


@dataclass(frozen=True)
class ResultadoDiagnosticoDiferencial:
    """Resultado completo devuelto al oncólogo para un paciente."""

    paciente_id: int
    generado_en: datetime
    candidatos: Tuple[DiagnosticoDiferencialCandidato, ...]
    advertencia_sin_sustento: Optional[str] = None

    es_apoyo_a_decision_clinica: bool = field(default=True, init=False)
    disclaimer: str = field(default=DISCLAIMER, init=False)

    def esta_vacio(self) -> bool:
        return len(self.candidatos) == 0
