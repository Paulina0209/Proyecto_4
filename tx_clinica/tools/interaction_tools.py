"""Tools de TX-03 (interacciones/contraindicaciones farmacológicas).

Envoltura delgada sobre tx_clinica.tools._interaction_shared -- la
resolución real (módulo, régimen, chequeo de las 3 capas + capa 0 de
conciliación) vive ahí, compartida con decision_tools.py (TX-04), para
que la lógica de seguridad no exista en dos copias.
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from patients.medicacion_actual import (
    listar_medicacion_activa,
    obtener_estado_conciliacion,
)
from tx_clinica.tools._db import conn_lock, obtener_conexion
from tx_clinica.tools._interaction_shared import resolver_chequeo_interacciones, serializar_chequeo
from tx_clinica.tools.patients_tools import ErrorPacienteNoEncontrado, obtener_paciente_o_error


@tool
def consultar_medicacion_actual(patient_id: int) -> str:
    """Devuelve, en JSON, la medicación concomitante ACTIVA registrada
    para un paciente YA REGISTRADO (no incluye el tratamiento oncológico
    en sí, solo medicación acompañante: anticoagulantes, antifúngicos,
    etc.), junto con el estado de conciliación (si alguna vez se revisó
    o nunca se ha hecho). Usa esta tool cuando el oncólogo pregunte
    directamente qué está tomando un paciente, sin estar chequeando un
    régimen todavía -- para eso usa chequear_interacciones_tratamiento
    en su lugar."""
    resuelto = obtener_paciente_o_error(patient_id)
    if isinstance(resuelto, ErrorPacienteNoEncontrado):
        return resuelto.a_json()

    conn = obtener_conexion()
    with conn_lock:
        medicacion = listar_medicacion_activa(conn, patient_id)
        estado_conciliacion = obtener_estado_conciliacion(conn, patient_id)

    return json.dumps(
        {
            "paciente_id": patient_id,
            "medicacion_activa": medicacion,
            "estado_conciliacion": estado_conciliacion,
            "nota": (
                "estado_conciliacion='no_realizada' significa que nadie ha revisado "
                "la medicación concomitante de este paciente todavía -- una lista "
                "vacía en ese caso NO significa 'no toma nada más', significa "
                "'no se sabe'."
            ),
        },
        ensure_ascii=False,
    )


@tool
def chequear_interacciones_tratamiento(patient_id: int, regimen_id: str) -> str:
    """Devuelve, en JSON, las interacciones/contraindicaciones
    farmacológicas detectadas entre un régimen candidato (ver
    regimen_id de obtener_recomendaciones_tratamiento_por_id) y la
    medicación concomitante ACTUAL de un paciente YA REGISTRADO. SIEMPRE
    debes llamar esta tool antes de que el oncólogo confirme o modifique
    un tratamiento -- nunca asumas que no hay interacciones solo porque
    no se mencionaron.

    Si sin_interacciones_conocidas=true, no hay nada que reportar (no
    generes una alerta igual, eso sería fatiga de alertas innecesaria).
    Si requiere_conciliacion_medicamentos=true, dile al oncólogo que la
    medicación concomitante de este paciente nunca se ha revisado --
    NO digas "sin interacciones" en ese caso, aunque la lista esté vacía.
    Si interacciones_disponibles=false, este módulo de guía todavía no
    tiene contenido de interacciones cargado -- dilo explícitamente,
    no lo trates como "sin interacciones".
    Si cualquier interacción trae audit_effect="blocks_confirmation",
    dile al oncólogo que ese régimen NO se puede confirmar tal cual.
    Si trae audit_effect="requires_justification", se puede continuar
    pero el oncólogo debe justificar explícitamente por qué -- esa
    justificación se registra después, al confirmar el tratamiento con
    registrar_decision_tratamiento."""
    resuelto = obtener_paciente_o_error(patient_id)
    if isinstance(resuelto, ErrorPacienteNoEncontrado):
        return resuelto.a_json()

    resolucion = resolver_chequeo_interacciones(patient_id, regimen_id)
    if resolucion.error is not None:
        return json.dumps(resolucion.error, ensure_ascii=False)

    return json.dumps(serializar_chequeo(resolucion.chequeo), ensure_ascii=False)
