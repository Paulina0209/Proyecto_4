"""Tools de recomendación de tratamiento (TX-01/TX-02).

Estructura en dos fases, para AMBOS caminos (paciente registrado y caso
descrito en el chat):

  Fase 1 -- identificar la guía aplicable, distinguiendo explícitamente
            "ningún módulo aplica" (negativa real) de "no se puede
            determinar porque falta un dato clínico" (module_selector.
            seleccionar_modulo_con_diagnostico).
  Fase 2 -- si falta algo, se le pide al oncólogo (nunca se completa
            en silencio ni se reporta sin_guia_aplicable por error);
            si no falta nada, se generan los candidatos de tratamiento.

`_diagnosticar_y_recomendar()` es la función compartida: devuelve un
dict de error (requiere_mas_datos/sin_guia_aplicable) O el
ResultadoRecomendacionTratamiento ya resuelto (con los RegimenCandidato
reales, no solo su versión serializada a JSON) -- tools/decision_tools.py
(TX-04) la reutiliza tal cual para saber cuál es el régimen sugerido y
cuáles son los candidatos válidos para "modify", en vez de tener que
volver a parsear el JSON de esta tool.
"""

from __future__ import annotations

import json
from typing import Any, Optional, Union

from langchain_core.tools import tool

from tx_clinica.builder import construir_recomendaciones_tratamiento
from tx_clinica.models import (
    FALTAN_DATOS_PARA_DETERMINAR_GUIA,
    SIN_GUIA_APLICABLE,
    ResultadoRecomendacionTratamiento,
)
from tx_clinica.module_selector import seleccionar_modulo_con_diagnostico
from tx_clinica.patient_facts import construir_facts_paciente
from tx_clinica.tools._db import conn_lock, obtener_conexion
from tx_clinica.tools._paths import GUIDELINES_ROOT
from tx_clinica.tools.patients_tools import ErrorPacienteNoEncontrado, obtener_paciente_o_error


def con_default_temporal(facts: dict[str, Any]) -> dict[str, Any]:
    # guideline_temporal_applicability es una determinación administrativa
    # (¿la versión de la guía vigente en la fecha de prescripción es la que
    # está codificada en este módulo?), no un dato clínico del paciente.
    # No tiene sentido pedírselo al oncólogo en el chat, así que el
    # orquestador lo asume "applicable" por defecto salvo que alguien
    # (backend, integración con el repo de guías, etc.) lo pise
    # explícitamente. No se muta el dict del caller.
    return {"guideline_temporal_applicability": "applicable", **facts}


def serializar_candidato(c) -> dict[str, Any]:
    """Compartido con decision_tools.py, para que el snapshot de
    auditoría de TX-04 tenga EXACTAMENTE la misma forma que lo que esta
    tool ya le muestra al oncólogo."""
    return {
        "regimen_id": c.regimen_id,
        "fase": c.fase,
        "farmacos": list(c.farmacos),
        "audit_effect": c.audit_effect,
        "rule_id_disparada": c.rule_id_disparada,
        "evidencia": c.evidencia.resumen_citable() if c.evidencia else None,
        "advertencia_comorbilidad": c.advertencia_comorbilidad,
    }


def _diagnosticar_y_recomendar(
    patient_id: Optional[int], facts: dict[str, Any]
) -> Union[dict[str, Any], ResultadoRecomendacionTratamiento]:
    """Fase 1 + Fase 2. Devuelve un dict de error listo para json.dumps
    (requiere_mas_datos=true o sin_guia_aplicable=true) o el
    ResultadoRecomendacionTratamiento ya resuelto."""
    facts = con_default_temporal(facts)
    diagnostico = seleccionar_modulo_con_diagnostico(facts, GUIDELINES_ROOT)

    if diagnostico.estado == "variables_faltantes":
        return {
            "requiere_mas_datos": True,
            "sin_guia_aplicable": False,
            "mensaje": FALTAN_DATOS_PARA_DETERMINAR_GUIA,
            "variables_faltantes_por_modulo": diagnostico.variables_faltantes_por_modulo,
        }

    if diagnostico.estado == "ningun_modulo_aplica":
        return {"requiere_mas_datos": False, "sin_guia_aplicable": True, "mensaje": SIN_GUIA_APLICABLE}

    # diagnostico.estado == "resuelto". construir_recomendaciones_tratamiento
    # vuelve a resolver el módulo internamente (seleccionar_modulo, sin
    # diagnóstico) -- redundante pero determinista y barato; se deja así
    # a propósito para no tocar builder.py más de lo necesario.
    return construir_recomendaciones_tratamiento(patient_id, facts, GUIDELINES_ROOT)


def _recomendar_con_diagnostico_previo(patient_id: Optional[int], facts: dict[str, Any]) -> str:
    resultado = _diagnosticar_y_recomendar(patient_id, facts)

    if isinstance(resultado, dict):
        return json.dumps(resultado, ensure_ascii=False)

    return json.dumps(
        {
            "requiere_mas_datos": False,
            "sin_guia_aplicable": False,
            "module_id": resultado.module_id,
            "candidatos": [serializar_candidato(c) for c in resultado.candidatos],
        },
        ensure_ascii=False,
    )


@tool
def obtener_recomendaciones_tratamiento_por_id(patient_id: int) -> str:
    """Devuelve, en JSON, los candidatos de tratamiento que el motor
    determinista respalda para un paciente YA REGISTRADO en la base de
    datos (busca sus datos clínicos automáticamente, no hace falta
    describirlos). Usa esta tool cuando el oncólogo dé un id o nombre de
    paciente que ya está en el sistema. Esta tool es la ÚNICA fuente
    válida de qué régimen sugerir: no inventes régimenes ni evidencia
    que no vengan en este resultado.

    Si la respuesta trae requiere_mas_datos=true, NO reportes
    sin_guia_aplicable -- significa que todavía no se puede saber si hay
    guía aplicable porque falta un dato clínico del paciente
    (variables_faltantes_por_modulo trae exactamente cuáles). Pregúntale
    esos datos al oncólogo y, con su respuesta, usa
    completar_datos_paciente_y_recomendar -- nunca esta misma tool de
    nuevo (volvería a faltar el mismo dato, porque la base de datos no
    cambió)."""
    resuelto = obtener_paciente_o_error(patient_id)
    if isinstance(resuelto, ErrorPacienteNoEncontrado):
        return resuelto.a_json()

    conn = obtener_conexion()
    with conn_lock:
        facts = construir_facts_paciente(conn, patient_id)
    return _recomendar_con_diagnostico_previo(patient_id, facts)


@tool
def completar_datos_paciente_y_recomendar(patient_id: int, variables_adicionales: dict[str, Any]) -> str:
    """Usa esta tool DESPUÉS de que obtener_recomendaciones_tratamiento_por_id
    haya devuelto requiere_mas_datos=true y el oncólogo haya respondido
    las variables que se le preguntaron. variables_adicionales es un
    objeto (no un string) con SOLO esas variables -- nombre exacto tal
    como se pidieron, valor que dio el oncólogo. No inventes ni asumas
    ninguna variable que el oncólogo no haya mencionado explícitamente.

    Esta tool combina esos valores con los datos YA REGISTRADOS del
    paciente (los nuevos valores ganan si hay conflicto) y vuelve a
    intentar la Fase 1 + Fase 2 completas -- puede volver a pedir más
    datos si lo que se dio todavía no alcanza."""
    resuelto = obtener_paciente_o_error(patient_id)
    if isinstance(resuelto, ErrorPacienteNoEncontrado):
        return resuelto.a_json()

    conn = obtener_conexion()
    with conn_lock:
        facts = construir_facts_paciente(conn, patient_id)
    facts = {**facts, **variables_adicionales}
    return _recomendar_con_diagnostico_previo(patient_id, facts)


@tool
def obtener_recomendaciones_tratamiento_con_datos(facts_paciente: dict[str, Any]) -> str:
    """Devuelve, en JSON, los candidatos de tratamiento para un caso
    descrito DIRECTAMENTE EN EL CHAT (sin id de paciente registrado en la
    base de datos). facts_paciente es un objeto (no un string) con las
    variables clínicas que el oncólogo mencionó (estadio, biomarcadores,
    ECOG, etc.), usando el vocabulario de variables.yaml del módulo que
    aplique. Usa esta tool cuando el oncólogo describa un caso hipotético
    o un paciente que no está en la base de datos. No completes ni
    inventes variables que el oncólogo no mencionó -- si no sabes qué
    campos pedir, usa primero listar_variables_requeridas.

    Aun así, si la respuesta trae requiere_mas_datos=true, puede haber
    quedado sin cubrir algún dato obligatorio -- pregúntalo y vuelve a
    llamar esta misma tool con los facts completos (aquí no aplica
    completar_datos_paciente_y_recomendar, esa es solo para pacientes
    registrados)."""
    return _recomendar_con_diagnostico_previo(None, facts_paciente)
