"""Traduce medicación concomitante (texto libre en medicacion_actual) al
vocabulario de variables de cada módulo de guidelines/ — mismo rol que
tx_clinica/comorbidity_mapping.py, aplicado a fármacos en vez de
comorbilidades.

Principio de arquitectura que se respeta aquí (igual que en
comorbidity_mapping.py): un medicamento que NO está en este catálogo en
absoluto NO se interpreta como "sin interacción" — se reporta aparte
como medicamento no mapeado (`no_mapeados`), para que el checker lo
marque como "no evaluado", nunca como "negativo".

Eso es DISTINTO de una variable que SÍ está en el catálogo pero que,
revisando toda la medicación activa del paciente, no matcheó ningún
medicamento -- ahí sí sabemos con certeza que es False, porque este
módulo recibe la lista COMPLETA de medicación activa. Antes solo se
devolvía True para las variables que matcheaban y las demás quedaban
ausentes del diccionario; el motor de reglas trata una variable ausente
como "dato desconocido" (`not_evaluable`), no como "False confirmado" --
confirmado ejecutando core/engine.py con una regla `not_equals: true`
sobre una variable que ningún medicamento del paciente activaba: quedaba
sin resolverse en vez de dar "aplicable". Ahora se devuelve False
explícito para toda variable del catálogo que no matcheó, para que el
motor sí pueda resolver reglas que dependan de una negación conocida.

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

#: Todas las variables concomitant_* que este catálogo puede llegar a
#: determinar -- se calcula una sola vez a partir de
#: MAPEO_MEDICAMENTO_A_VARIABLES, para no mantener una segunda lista a
#: mano que se pueda desincronizar si el catálogo crece.
_VARIABLES_CONOCIDAS: frozenset[str] = frozenset(
    var for variables in MAPEO_MEDICAMENTO_A_VARIABLES.values() for var in variables
)


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
    (texto libre, tal como viene de la tabla medicacion_actual) -- se
    asume COMPLETA (toda la medicación activa del paciente), no un
    subconjunto; de ahí que se pueda inferir False con certeza para las
    variables del catálogo que ningún medicamento activó (ver D7 en el
    docstring del módulo).
    """
    variables: dict[str, bool] = {var: False for var in _VARIABLES_CONOCIDAS}
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
