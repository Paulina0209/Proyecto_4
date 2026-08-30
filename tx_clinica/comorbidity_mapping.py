from __future__ import annotations

from typing import Dict, Tuple

MAPEO_TIPO_CONTRAINDICACION_A_VARIABLES: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "immediate": (
        ("major_comorbidity_precluding_ici", "yes"),
        ("immunotherapy_contraindication", "yes"),
        ("immune_checkpoint_inhibitor_contraindication", "yes"),
        ("immune_checkpoint_inhibitor_toxicity_risk", "excessive"),
        ("ici_suitability", "immediate_contraindication"),
    ),
    "absolute": (
        ("major_comorbidity_precluding_ici", "yes"),
        ("immunotherapy_contraindication", "yes"),
        ("immune_checkpoint_inhibitor_contraindication", "yes"),
        ("immune_checkpoint_inhibitor_toxicity_risk", "excessive"),
        ("ici_suitability", "absolute_contraindication"),
    ),
}