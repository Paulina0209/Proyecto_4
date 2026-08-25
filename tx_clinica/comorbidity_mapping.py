"""Mapeo explícito: tipo de contraindicación de ICI (juicio del oncólogo,
registrado en comorbilidades.tipo_contraindicacion_ici) -> variable(s)
de regla que ese juicio activa en cada módulo.

Por qué esto y no un mapeo por nombre/código de enfermedad: ninguna de
las 8 guías ESMO revisadas especifica qué condiciones médicas exactas
cuentan como "comorbilidad que contraindica ICI" -- cada una deja la
variable como un booleano/categórico abierto (major_comorbidity_
precluding_ici, ici_suitability, etc.) sin dar una lista de qué la
activa. Es, en la práctica clínica real, juicio caso por caso del
oncólogo -- no una tabla codificable.

Por eso este mapeo no traduce "Lupus" o "M32.9" a una variable: eso
requeriría que el sistema decidiera, por su cuenta, qué tan grave o
activa está una enfermedad, sin que ninguna guía lo respalde. En vez de
eso, el oncólogo declara directamente su propio juicio clínico
(tipo_contraindicacion_ici), y este mapeo solo traduce ESE juicio ya
tomado al vocabulario de cada módulo -- es re-etiquetado, no inferencia
clínica.

Dos categorías, tomadas del único lugar donde una guía sí distingue
matices (cutaneous_melanoma, variable ici_suitability):
  - "immediate": contraindicación temporal/reevaluable
    (ESMO-MEL-CUT-EXC-007 y equivalente)
  - "absolute": contraindicación permanente
    (ESMO-MEL-CUT-EXC-008 y equivalente)

Para los módulos cuya variable es binaria (yes/no), ambas categorías se
traducen igual ("yes") -- la distinción immediate/absolute solo importa
donde la guía la modela (melanoma, RCC).
"""

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