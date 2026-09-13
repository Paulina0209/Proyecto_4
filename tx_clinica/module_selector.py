"""Selección del módulo de guías (guidelines/<carpeta>/) aplicable a un paciente.

No reimplementa ningún matching: reutiliza core.engine.evaluate_rule_set
sobre el eligibility.yaml de cada módulo, exactamente igual que
dx_clinica reutiliza sus propios mecanismos. La regla positiva de scope
sigue el patrón ya usado en breast_early_tnbc: conclusion.action ==
"enter_module".

Si ningún módulo aplica, se devuelve None explícitamente — nunca se
adivina el módulo "más parecido" (criterio de aceptación #3 de TX-01).

Alcance confirmado tras revisar las 9 guías reales de guidelines/:
  - 7 módulos SÍ generan sugerencias (tienen reglas positivas
    supports_prescription escritas desde estadio/biomarcadores, no solo
    auditoría de lo ya prescrito): breast_early_tnbc,
    breast_metastatic_tnbc, cutaneous_melanoma,
    nsclc_early_locally_advanced, nsclc_metastatic_non_oncogene,
    renal_cell_carcinoma_advanced_metastatic,
    renal_cell_carcinoma_localized_adjuvant, uveal_melanoma.
  - 2 módulos quedan FUERA de alcance de TX-01, documentado:
      * sclc_pembrolizumab_review: sin contenido ("Pendiente de
        completar" en clinical_matrix.md y decision_tree.md).
      * nsclc_metastatic_oncogene_addicted: su propio regimens.yaml se
        declara "audit trigger" / "This is not a pembrolizumab
        recommendation" — el módulo existe solo para auditar
        concordancia de driver routing, no para generar sugerencias.
        Ninguna de sus ~20 reglas (eligibility, exclusions, routing,
        sequencing) produce audit_effect=supports_prescription.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from core.engine import evaluate_rule_set

logger = logging.getLogger(__name__)

#: Carpetas de guidelines/ que se ignoran explícitamente para TX-01.
#: Ver docstring del módulo para la justificación de cada una.
MODULOS_FUERA_DE_ALCANCE = {
    "sclc_pembrolizumab_review",
    "nsclc_metastatic_oncogene_addicted",
}

#: ---------------------------------------------------------------------
#: Confirmado contra core/engine.py real: RuleEvaluation.status toma
#: "applicable" | "not_applicable" | "not_evaluable" (lógica de tres
#: valores True/False/None por dato faltante), y missing_fields (set[str])
#: viene poblado exactamente cuando status == "not_evaluable" -- nunca
#: cuando una condición ya dio False explícito, incluso si otra condición
#: del mismo "all" tenía un dato faltante (el motor prioriza el False:
#: ver _evaluate_condition en engine.py, "if value is False: return
#: False, set()"). Esto es justo el comportamiento que
#: seleccionar_modulo_con_diagnostico() necesita para no confundir "esta
#: regla ya sabe que no aplica" con "no se puede saber todavía".
#: ---------------------------------------------------------------------
_STATUS_APLICABLE = "applicable"
_STATUS_NO_EVALUABLE = "not_evaluable"


def _carpetas_modulo(guidelines_root: Path) -> list[Path]:
    if not guidelines_root.exists():
        return []
    return sorted(
        p for p in guidelines_root.iterdir()
        if p.is_dir() and p.name not in MODULOS_FUERA_DE_ALCANCE
    )


def seleccionar_modulo(facts: dict[str, Any], guidelines_root: Path) -> Optional[str]:
    """Devuelve el nombre de carpeta del módulo aplicable, o None si ninguno aplica.

    Sin cambios de comportamiento respecto a la versión original. Sigue
    usándose tal cual dentro de builder.py. NO distingue "no aplica" de
    "falta un dato" -- para eso usar seleccionar_modulo_con_diagnostico().
    """
    for carpeta in _carpetas_modulo(guidelines_root):
        eligibility_path = carpeta / "rules" / "eligibility.yaml"
        if not eligibility_path.exists():
            continue
        try:
            evaluaciones = evaluate_rule_set(eligibility_path, facts)
        except ValueError as error:
            # Antes esto se tragaba en silencio: un eligibility.yaml mal
            # formado se veía IDÉNTICO a "el paciente no calza en este
            # módulo", sin ningún rastro. Con esto, un YAML roto queda en
            # el log en vez de disfrazarse de "no aplica".
            logger.warning(
                "No se pudo evaluar rules/eligibility.yaml del módulo %s: %s",
                carpeta.name, error,
            )
            continue
        for evaluacion in evaluaciones:
            if evaluacion.status != _STATUS_APLICABLE:
                continue
            conclusion = evaluacion.conclusion or {}
            if conclusion.get("action") == "enter_module":
                return carpeta.name
    return None


@dataclass(frozen=True)
class ModuloSeleccionado:
    """Resultado de la Fase 1 (identificar guía) para un paciente con facts
    reales -- a diferencia de seleccionar_modulo(), SÍ distingue "ningún
    módulo aplica" de "no se pudo determinar porque falta un dato"."""

    estado: str  # "resuelto" | "variables_faltantes" | "ningun_modulo_aplica"
    modulo_id: Optional[str] = None
    #: Solo poblado si estado == "variables_faltantes": por cada módulo
    #: candidato (uno cuya regla de entrada no pudo evaluarse por dato
    #: faltante, no uno que explícitamente no aplica), qué variables
    #: faltan. Puede haber más de un módulo candidato a la vez.
    variables_faltantes_por_modulo: dict[str, list[str]] = field(default_factory=dict)


def seleccionar_modulo_con_diagnostico(
    facts: dict[str, Any], guidelines_root: Path
) -> ModuloSeleccionado:
    """Fase 1 de la recomendación de tratamiento: identificar la guía
    aplicable, distinguiendo explícitamente "no aplica" de "no se puede
    determinar todavía por falta de datos".

    No reemplaza seleccionar_modulo() (builder.py sigue usando esa, sin
    cambios) -- esta función es para la capa de tools/orquestación, donde
    si el resultado es "variables_faltantes" hay que preguntarle al
    oncólogo antes de seguir, en vez de reportar silenciosamente
    sin_guia_aplicable.
    """
    variables_faltantes_por_modulo: dict[str, list[str]] = {}

    for carpeta in _carpetas_modulo(guidelines_root):
        eligibility_path = carpeta / "rules" / "eligibility.yaml"
        if not eligibility_path.exists():
            continue
        try:
            evaluaciones = evaluate_rule_set(eligibility_path, facts)
        except ValueError as error:
            # Antes esto se tragaba en silencio: un eligibility.yaml mal
            # formado se veía IDÉNTICO a "el paciente no calza en este
            # módulo", sin ningún rastro. Con esto, un YAML roto queda en
            # el log en vez de disfrazarse de "no aplica".
            logger.warning(
                "No se pudo evaluar rules/eligibility.yaml del módulo %s: %s",
                carpeta.name, error,
            )
            continue

        for evaluacion in evaluaciones:
            conclusion = evaluacion.conclusion or {}
            if conclusion.get("action") != "enter_module":
                continue  # esta regla no es la de scope del módulo, no participa

            if evaluacion.status == _STATUS_APLICABLE:
                # Resuelto de forma limpia: se corta acá, mismo criterio
                # de "primer módulo que aplica" que la función original.
                return ModuloSeleccionado(estado="resuelto", modulo_id=carpeta.name)

            if evaluacion.status == _STATUS_NO_EVALUABLE:
                # missing_fields es un set[str] en el engine real -- sorted()
                # para que la lista mostrada al oncólogo sea determinista
                # (un set no garantiza orden de iteración estable).
                faltantes = sorted(evaluacion.missing_fields)
                if faltantes:
                    variables_faltantes_por_modulo[carpeta.name] = faltantes
            # status explícitamente "no aplica" (ni applicable ni
            # not_evaluable): este módulo se descarta sin más, es una
            # negativa real, no una ausencia de dato.

    if variables_faltantes_por_modulo:
        return ModuloSeleccionado(
            estado="variables_faltantes",
            variables_faltantes_por_modulo=variables_faltantes_por_modulo,
        )

    return ModuloSeleccionado(estado="ningun_modulo_aplica")
