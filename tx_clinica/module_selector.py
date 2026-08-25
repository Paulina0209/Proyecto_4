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

from pathlib import Path
from typing import Any, Optional

from core.engine import evaluate_rule_set

#: Carpetas de guidelines/ que se ignoran explícitamente para TX-01.
#: Ver docstring del módulo para la justificación de cada una.
MODULOS_FUERA_DE_ALCANCE = {
    "sclc_pembrolizumab_review",
    "nsclc_metastatic_oncogene_addicted",
}


def _carpetas_modulo(guidelines_root: Path) -> list[Path]:
    if not guidelines_root.exists():
        return []
    return sorted(
        p for p in guidelines_root.iterdir()
        if p.is_dir() and p.name not in MODULOS_FUERA_DE_ALCANCE
    )


def seleccionar_modulo(facts: dict[str, Any], guidelines_root: Path) -> Optional[str]:
    """Devuelve el nombre de carpeta del módulo aplicable, o None si ninguno aplica.

    Las reglas de cada módulo viven en una subcarpeta ``rules/`` (ej.
    ``guidelines/breast_early_tnbc/rules/eligibility.yaml``), confirmado
    contra la estructura real del repo — no sueltas en la carpeta del
    módulo.
    """
    for carpeta in _carpetas_modulo(guidelines_root):
        eligibility_path = carpeta / "rules" / "eligibility.yaml"
        if not eligibility_path.exists():
            continue
        try:
            evaluaciones = evaluate_rule_set(eligibility_path, facts)
        except ValueError:
            continue
        for evaluacion in evaluaciones:
            if evaluacion.status != "applicable":
                continue
            conclusion = evaluacion.conclusion or {}
            if conclusion.get("action") == "enter_module":
                return carpeta.name
    return None