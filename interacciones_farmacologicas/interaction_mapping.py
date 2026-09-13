"""Traduce medicación concomitante (texto libre en medicacion_actual) al
vocabulario de variables de cada módulo de guidelines/ — mismo rol que
tx_clinica/comorbidity_mapping.py, aplicado a fármacos en vez de
comorbilidades.

Principio de arquitectura que se respeta aquí (igual que en
comorbidity_mapping.py): lo que NO está en este mapeo NO se interpreta
como "sin interacción" — se reporta aparte como medicamento no mapeado,
para que el checker lo marque como "no evaluado" y no como "negativo".

Este catálogo es deliberadamente pequeño (ejemplo de arranque). Crece con
uso real, igual que el mapeo de comorbilidades.
"""
from __future__ import annotations

import unicodedata

# medicamento normalizado -> variables concomitant_* que activa
MAPEO_MEDICAMENTO_A_VARIABLES: dict[str, list[str]] = {
    "warfarina": ["concomitant_anticoagulant_vka"],
    "acenocumarol": ["concomitant_anticoagulant_vka"],
    "fluconazol": ["concomitant_strong_cyp3a4_inhibitor"],
    "itraconazol": ["concomitant_strong_cyp3a4_inhibitor"],
    "claritromicina": ["concomitant_strong_cyp3a4_inhibitor"],
    "ketoconazol": ["concomitant_strong_cyp3a4_inhibitor"],
    "amiodarona": ["concomitant_qt_prolonging_agent"],
    "citalopram": ["concomitant_qt_prolonging_agent"],
    "ondansetron": ["concomitant_qt_prolonging_agent"],
    "fenitoina": ["concomitant_strong_cyp3a4_inducer"],
    "rifampicina": ["concomitant_strong_cyp3a4_inducer"],
    "carbamazepina": ["concomitant_strong_cyp3a4_inducer"],
}


def _normalizar(texto: str) -> str:
    texto = texto.strip().lower()
    texto = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return texto


def mapear_medicacion_actual_a_variables(
    medicacion_actual: list[str],
) -> tuple[dict[str, bool], list[str]]:
    """Devuelve (variables_activadas, medicamentos_no_mapeados).

    `medicacion_actual` es una lista de nombres de medicamentos activos
    (texto libre, tal como viene de la tabla medicacion_actual).
    """
    variables: dict[str, bool] = {}
    no_mapeados: list[str] = []

    for medicamento in medicacion_actual:
        clave = _normalizar(medicamento)
        variables_del_medicamento = MAPEO_MEDICAMENTO_A_VARIABLES.get(clave)
        if variables_del_medicamento is None:
            no_mapeados.append(medicamento)
            continue
        for var in variables_del_medicamento:
            variables[var] = True

    return variables, no_mapeados
