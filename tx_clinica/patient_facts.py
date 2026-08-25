"""Puente historia_clinica_mock -> dict de facts para tx_clinica.builder.

Equivalente, para tratamiento, de lo que historia_clinica_mock.adapters
ya hace para IA-02/DX-02: construye la entrada que el módulo de dominio
necesita a partir de las filas reales de la base de datos, con
trazabilidad (aquí, implícita: cada valor viene de una fila real de
datos_clinicos_estructurados/comorbilidades, no se inventa nada).

No decide nada clínico: solo empaqueta lo que ya está en la base de
datos en el formato de diccionario {variable: valor} que core.engine
espera, convirtiendo tipos según lo que variables.yaml declara (int/float
para las variables numéricas conocidas; el resto se deja como string).
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict

from historia_clinica_mock.repository import (
    comorbilidades_de_paciente,
    facts_estructurados_de_paciente,
    obtener_paciente,
)

from tx_clinica.comorbidity_mapping import MAPEO_TIPO_CONTRAINDICACION_A_VARIABLES

#: Variables que variables.yaml declara como numéricas, confirmado contra
#: las 8 guías reales (no solo las que se usaron en el primer test).
_VARIABLES_NUMERICAS = {
    "ecog_ps",
    "pdl1_tps",
    "pdl1_tc_percent",
    "pdl1_cps",
    "tumor_size_cm",
    "treatment_line",
    "age_years",
    "adjuvant_pembrolizumab_cycles_completed",
    "neoadjuvant_pembrolizumab_cycles_completed",
    "months_on_adjuvant_pembrolizumab",
    "months_on_ici",
    "weeks_since_complete_resection",
    "sentinel_node_tumor_burden_mm",
    "disease_free_interval_months",
    "cycle_number",
    "imaging_interval_months",
    "followup_months_since_nephrectomy",
}


def _convertir_tipo(variable: str, valor: str) -> Any:
    if variable in _VARIABLES_NUMERICAS:
        try:
            return int(valor)
        except ValueError:
            return float(valor)
    return valor


def construir_facts_paciente(conn: sqlite3.Connection, paciente_id: int) -> Dict[str, Any]:
    """Construye el diccionario de facts para tx_clinica.builder.

    No incluye por sí solo `prescribed_antineoplastic_drugs` ni
    `treatment_phase` reales del paciente -- esos son precisamente los
    campos que tx_clinica.builder sobrescribe de forma hipotética por
    régimen (ver core.engine.evaluate_rule_set_hypothetical).
    """
    paciente = obtener_paciente(conn, paciente_id)
    if paciente is None:
        raise ValueError(f"No existe ningún paciente con id={paciente_id}.")

    facts: Dict[str, Any] = {}

    # Los datos estructurados son la fuente principal: ya vienen en el
    # vocabulario categórico que las reglas esperan.
    for variable, valor in facts_estructurados_de_paciente(conn, paciente_id).items():
        facts[variable] = _convertir_tipo(variable, valor)

    # Comorbilidades: se expone la lista de condiciones registradas (solo
    # como referencia informativa), y se derivan los facts de contraindicación
    # de ICI a partir del JUICIO CLÍNICO explícito del oncólogo
    # (comorbilidades.tipo_contraindicacion_ici), no del nombre/código de
    # la condición -- ninguna guía especifica qué condiciones exactas
    # cuentan, así que el sistema nunca decide eso por su cuenta.
    #
    # Un dato ya presente en datos_clinicos_estructurados (fuente
    # principal, más arriba) SIEMPRE gana sobre lo derivado aquí.
    comorbilidades = comorbilidades_de_paciente(conn, paciente_id)
    condiciones_registradas = {c.condicion for c in comorbilidades} - {"ninguna_registrada"}
    facts["comorbilidades_registradas"] = sorted(condiciones_registradas)

    for c in comorbilidades:
        if not c.tipo_contraindicacion_ici:
            continue
        for variable, valor in MAPEO_TIPO_CONTRAINDICACION_A_VARIABLES.get(
            c.tipo_contraindicacion_ici, ()
        ):
            facts.setdefault(variable, valor)

    return facts