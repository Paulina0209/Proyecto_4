"""Resolución de interacciones compartida entre interaction_tools.py (TX-03,
tool de consulta) y decision_tools.py (TX-04, que necesita el MISMO
chequeo antes de dejar confirmar un tratamiento).

Esto vive separado a propósito: es lógica de seguridad clínica (¿esta
combinación de fármacos es segura para este paciente?) y NO debe existir
en dos copias que puedan divergir entre "cuando el oncólogo pregunta" y
"cuando el oncólogo confirma".

El contenido de interacciones YA NO vive en guidelines/ -- vive dentro
de interacciones_farmacologicas/docs/rules_interacciones/. Este archivo
solo resuelve el módulo/régimen (eso sigue viniendo de guidelines/ real,
sin tocar) y delega todo lo de interacciones a
interacciones_farmacologicas.checker, que ya sabe dónde buscar su propio
contenido.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from interacciones_farmacologicas.checker import (
    SIN_CONTENIDO_PARA_MODULO,
    construir_chequeo_interacciones,
)
from interacciones_farmacologicas.models import ResultadoChequeoInteracciones
from patients.medicacion_actual import (
    listar_medicacion_activa,
    obtener_estado_conciliacion,
)
from tx_clinica.builder import obtener_farmacos_de_regimen
from tx_clinica.models import FALTAN_DATOS_PARA_DETERMINAR_GUIA, SIN_GUIA_APLICABLE
from tx_clinica.module_selector import seleccionar_modulo_con_diagnostico
from tx_clinica.patient_facts import construir_facts_paciente
from tx_clinica.tools._db import conn_lock, obtener_conexion
from tx_clinica.tools._paths import GUIDELINES_ROOT
from tx_clinica.tools.recommendation_tools import con_default_temporal


@dataclass
class ResolucionInteracciones:
    #: Si no es None, ya está listo para json.dumps() y devolverse tal
    #: cual desde la tool que llama -- significa que el chequeo no se
    #: pudo completar (faltan datos, sin guía, régimen inválido, o el
    #: módulo todavía no tiene contenido de interacciones cargado).
    error: Optional[dict[str, Any]] = None
    chequeo: Optional[ResultadoChequeoInteracciones] = None
    modulo_id: Optional[str] = None


def resolver_chequeo_interacciones(patient_id: int, regimen_id: str) -> ResolucionInteracciones:
    """Punto único de entrada: dado un paciente ya confirmado que existe
    y un regimen_id, resuelve el módulo, valida el régimen (ambos contra
    guidelines/ real, sin cambios), y corre el chequeo de interacciones
    completo (las 3 capas + la capa 0 de conciliación) contra el
    contenido propio de interacciones_farmacologicas."""
    conn = obtener_conexion()
    with conn_lock:
        facts = construir_facts_paciente(conn, patient_id)
        medicacion_actual = listar_medicacion_activa(conn, patient_id)
        estado_conciliacion = obtener_estado_conciliacion(conn, patient_id)

    facts = con_default_temporal(facts)
    diagnostico = seleccionar_modulo_con_diagnostico(facts, GUIDELINES_ROOT)

    if diagnostico.estado == "variables_faltantes":
        return ResolucionInteracciones(
            error={
                "requiere_mas_datos": True,
                "mensaje": FALTAN_DATOS_PARA_DETERMINAR_GUIA,
                "variables_faltantes_por_modulo": diagnostico.variables_faltantes_por_modulo,
            }
        )

    if diagnostico.estado == "ningun_modulo_aplica":
        return ResolucionInteracciones(
            error={"requiere_mas_datos": False, "sin_guia_aplicable": True, "mensaje": SIN_GUIA_APLICABLE}
        )

    module_folder = GUIDELINES_ROOT / diagnostico.modulo_id

    farmacos_regimen = obtener_farmacos_de_regimen(module_folder, regimen_id)
    if farmacos_regimen is None:
        return ResolucionInteracciones(
            modulo_id=diagnostico.modulo_id,
            error={
                "error": (
                    f"El régimen '{regimen_id}' no existe en el módulo "
                    f"{diagnostico.modulo_id} (regimens.yaml). Usa un regimen_id "
                    "que haya salido de obtener_recomendaciones_tratamiento_por_id."
                )
            },
        )

    chequeo = construir_chequeo_interacciones(
        paciente_id=patient_id,
        modulo_guia=diagnostico.modulo_id,
        regimen_propuesto_id=regimen_id,
        regimen_propuesto_drugs=farmacos_regimen,
        medicacion_actual=medicacion_actual,
        base_facts=facts,
        conciliacion_medicamentos_estado=estado_conciliacion,
    )

    if chequeo.disclaimer == SIN_CONTENIDO_PARA_MODULO:
        return ResolucionInteracciones(
            modulo_id=diagnostico.modulo_id,
            error={
                "requiere_mas_datos": False,
                "sin_guia_aplicable": False,
                "interacciones_disponibles": False,
                "mensaje": (
                    f"El módulo {diagnostico.modulo_id} todavía no tiene contenido de "
                    "interacciones farmacológicas cargado "
                    f"(interacciones_farmacologicas/docs/rules_interacciones/{diagnostico.modulo_id}.yaml "
                    "no existe). No se puede chequear automáticamente -- recomienda revisar "
                    "manualmente la ficha técnica de cada fármaco concomitante antes de confirmar."
                ),
            },
        )

    return ResolucionInteracciones(chequeo=chequeo, modulo_id=diagnostico.modulo_id)


def serializar_interaccion(i) -> dict[str, Any]:
    return {
        "interaccion_id": i.interaccion_id,
        "severidad": i.severidad,
        "audit_effect": i.audit_effect,
        "descripcion": i.descripcion,
        "recomendacion": i.recomendacion,
        "medicamento_concomitante": i.medicamento_concomitante,
        "fuente": i.fuente,
    }


def serializar_chequeo(chequeo: ResultadoChequeoInteracciones) -> dict[str, Any]:
    return {
        "requiere_mas_datos": False,
        "sin_guia_aplicable": False,
        "interacciones_disponibles": True,
        "modulo_guia": chequeo.modulo_guia,
        "regimen_evaluado": chequeo.regimen_evaluado,
        "sin_interacciones_conocidas": chequeo.sin_interacciones_conocidas,
        "requiere_conciliacion_medicamentos": chequeo.requiere_conciliacion_medicamentos,
        "advertencia_cobertura_incompleta": chequeo.advertencia_cobertura_incompleta,
        "medicamentos_no_mapeados": chequeo.medicamentos_no_mapeados,
        "interacciones": [serializar_interaccion(i) for i in chequeo.interacciones],
    }
