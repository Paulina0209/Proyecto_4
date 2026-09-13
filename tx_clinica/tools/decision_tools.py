"""Tool de TX-04 (decisión final del oncólogo).

Reutiliza, sin reimplementar nada:
  - tx_clinica.tools.recommendation_tools._diagnosticar_y_recomendar
    (Fase 1 + Fase 2 de TX-01, la misma que ya usan las otras tools de
    recomendación)
  - tx_clinica.tools._interaction_shared.resolver_chequeo_interacciones
    (TX-03, la misma que usa chequear_interacciones_tratamiento)
  - decision_clinica.registro.registrar_decision_tratamiento (la
    orquestación de los 3 caminos accept/modify/reject + el gate de
    AUD-02, ver decision_clinica/registro.py)

Esta tool NO decide nada por el oncólogo -- solo recalcula, de forma
determinista, lo que hace falta para poder registrar su decisión
(cuál era el régimen sugerido, si el régimen final que dio es uno de
los candidatos válidos, si hay interacciones que exigen justificación).
"""

from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import tool

from clinical_decision.registro import registrar_decision_tratamiento as _registrar
from tx_clinica.patient_facts import construir_facts_paciente
from tx_clinica.tools._db import conn_lock, obtener_conexion
from tx_clinica.tools._interaction_shared import resolver_chequeo_interacciones
from tx_clinica.tools.patients_tools import ErrorPacienteNoEncontrado, obtener_paciente_o_error
from tx_clinica.tools.recommendation_tools import _diagnosticar_y_recomendar, serializar_candidato

_TIPOS_VALIDOS = ("accept", "modify", "reject")


@tool
def registrar_decision_tratamiento(
    patient_id: int,
    oncologo_id: int,
    tipo_decision: str,
    regimen_final_id: Optional[str] = None,
    motivo_rechazo: Optional[str] = None,
    textos_justificacion: Optional[dict[str, str]] = None,
) -> str:
    """Registra la decisión FINAL y OFICIAL del oncólogo sobre el
    tratamiento de un paciente YA REGISTRADO -- deja constancia de que
    la responsabilidad clínica es del médico, no del sistema. Llama esta
    tool solo cuando el oncólogo exprese una decisión explícita, nunca la
    infieras ni la registres tú por iniciativa propia.

    tipo_decision debe ser exactamente uno de:
      - "accept": acepta el régimen que el sistema sugirió tal cual. No
        pases regimen_final_id -- se toma automáticamente el sugerido.
      - "modify": el oncólogo eligió un régimen DISTINTO al sugerido.
        regimen_final_id es OBLIGATORIO y debe ser uno de los regimen_id
        que ya salieron como candidatos de
        obtener_recomendaciones_tratamiento_por_id para este mismo
        paciente -- no un régimen arbitrario que el oncólogo mencione de
        forma libre (limitación conocida de esta historia).
      - "reject": el oncólogo rechaza la recomendación. motivo_rechazo es
        OBLIGATORIO (el juicio clínico del oncólogo, en sus palabras, no
        una que tú inventes). Rechazar NUNCA bloquea nada -- siempre se
        registra si el motivo no está vacío.

    Para "accept"/"modify": esta tool corre automáticamente el chequeo de
    interacciones del régimen final. Si trae una interacción con
    audit_effect="requires_justification", NO llames esta tool todavía
    con textos_justificacion inventado -- primero pregúntale al
    oncólogo por qué decide continuar pese a la alerta, y pasa su
    respuesta textual tal cual en textos_justificacion (clave =
    interaccion_id que te dio chequear_interacciones_tratamiento). Si
    hay una interacción con audit_effect="blocks_confirmation", esta
    tool va a rechazar el registro sin importar qué justificación se dé
    -- avísale al oncólogo que ese régimen no se puede confirmar así.

    Si registrado=false, lee motivo_rechazo de la respuesta y explícaselo
    al oncólogo -- no reintentes solo con textos distintos sin que el
    oncólogo haya dado la información que falta."""
    resuelto = obtener_paciente_o_error(patient_id)
    if isinstance(resuelto, ErrorPacienteNoEncontrado):
        return resuelto.a_json()

    if tipo_decision not in _TIPOS_VALIDOS:
        return json.dumps(
            {"error": f"tipo_decision inválido: {tipo_decision!r}. Debe ser uno de {_TIPOS_VALIDOS}."},
            ensure_ascii=False,
        )

    conn = obtener_conexion()
    with conn_lock:
        facts = construir_facts_paciente(conn, patient_id)

    resultado_recomendacion = _diagnosticar_y_recomendar(patient_id, facts)

    chequeo_interacciones = None
    regimenes_candidatos_ids: list[str] = []
    regimen_sugerido_id: Optional[str] = None

    if isinstance(resultado_recomendacion, dict):
        # Fase 1 de TX-01 no se resolvió (falta un dato o no hay guía
        # aplicable). Solo "reject" puede proceder así -- no se puede
        # aceptar ni modificar un régimen que nunca llegó a calcularse.
        if tipo_decision != "reject":
            return json.dumps(
                {
                    "error": (
                        "No hay una recomendación resuelta para este paciente todavía "
                        "-- usa obtener_recomendaciones_tratamiento_por_id primero. No "
                        "se puede 'accept' ni 'modify' sin eso."
                    ),
                    **resultado_recomendacion,
                },
                ensure_ascii=False,
            )
        snapshot = {"estado_diagnostico": resultado_recomendacion}
    else:
        candidatos = resultado_recomendacion.candidatos
        regimenes_candidatos_ids = [c.regimen_id for c in candidatos]
        sugerido = next(
            (c for c in candidatos if c.es_primera_opcion),
            candidatos[0] if candidatos else None,
        )
        regimen_sugerido_id = sugerido.regimen_id if sugerido else None
        snapshot = {
            "module_id": resultado_recomendacion.module_id,
            "candidatos": [serializar_candidato(c) for c in candidatos],
        }

        if tipo_decision in ("accept", "modify"):
            regimen_a_confirmar = regimen_sugerido_id if tipo_decision == "accept" else regimen_final_id
            if not regimen_a_confirmar:
                return json.dumps(
                    {"error": "Falta regimen_final_id para 'modify'."}, ensure_ascii=False
                )
            resolucion = resolver_chequeo_interacciones(patient_id, regimen_a_confirmar)
            if resolucion.error is not None:
                # El chequeo de interacciones no se pudo completar (faltan
                # datos, sin guía, régimen inválido, o módulo sin
                # interactions.yaml todavía) -- no se puede registrar
                # accept/modify sin esto resuelto.
                return json.dumps(resolucion.error, ensure_ascii=False)
            chequeo_interacciones = resolucion.chequeo

    conn = obtener_conexion()
    with conn_lock:
        resultado = _registrar(
            conn,
            paciente_id=patient_id,
            oncologo_id=oncologo_id,
            tipo_decision=tipo_decision,
            recomendacion_ia_snapshot=snapshot,
            regimenes_candidatos_ids=regimenes_candidatos_ids,
            regimen_sugerido_id=regimen_sugerido_id,
            regimen_final_id=regimen_final_id,
            motivo_rechazo=motivo_rechazo,
            chequeo_interacciones=chequeo_interacciones,
            textos_justificacion=textos_justificacion,
        )

    if not resultado.exito:
        return json.dumps(
            {"registrado": False, "motivo_rechazo": resultado.motivo_rechazo}, ensure_ascii=False
        )

    d = resultado.decision
    return json.dumps(
        {
            "registrado": True,
            "decision_id": d.id,
            "tipo_decision": d.tipo_decision,
            "regimen_sugerido_id": d.regimen_sugerido_id,
            "regimen_final_id": d.regimen_final_id,
            "motivo_rechazo": d.motivo_rechazo,
            "justificaciones_ids": d.justificaciones_ids,
        },
        ensure_ascii=False,
    )
