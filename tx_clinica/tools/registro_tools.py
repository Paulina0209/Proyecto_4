"""Tools que GUARDAN datos en el expediente desde el chat.

Hasta ahora el agente solo podía usar los datos que le daba el oncólogo para
evaluar (``completar_datos_paciente_y_recomendar``), sin guardarlos: la
revisión de interacciones (TX-03) y el registro de la decisión (TX-04) leen
el expediente, así que el flujo se cortaba ahí.

Estas tools escriben, y por eso:

    - Están bajo aprobación humana (``middleware/human_in_the_loop.py``): el
      grafo se pausa y nada se guarda hasta que el oncólogo aprueba (o
      edita) la acción. Es una garantía estructural, no depende del prompt.
    - Validan TODO antes de escribir, después de la aprobación: variables
      que existan en ``guidelines/*/variables.yaml`` con valores permitidos.
      Si algo no es válido no se guarda nada (ni lo válido).
    - No aceptan variables de biomarcadores (``egfr_status``,
      ``her2_status``, ``pdl1_tps``...): esas pasan por HC-04, con su
      biopsia, validación estricta y doble ingreso.
    - El oncólogo que registra sale de la sesión (``config["configurable"]
      ["oncologo_id"]``), nunca de un argumento que el modelo pueda rellenar.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Optional

import yaml
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from expediente.registro import registrar_datos_clinicos
from historia_clinica.biopsias_biomarcadores import cargar_catalogo
from patients.medicacion_actual import obtener_estado_conciliacion, registrar_conciliacion
from tx_clinica.tools._db import conn_lock, obtener_conexion
from tx_clinica.tools._paths import GUIDELINES_ROOT
from tx_clinica.tools.patients_tools import ErrorPacienteNoEncontrado, obtener_paciente_o_error


@lru_cache(maxsize=1)
def definiciones_variables() -> dict[str, dict[str, Any]]:
    """``{variable: {"tipo", "valores", "minimo", "maximo"}}`` unificando
    todos los ``guidelines/*/variables.yaml`` (los valores permitidos se
    suman; los límites numéricos toman el rango más amplio declarado)."""
    definiciones: dict[str, dict[str, Any]] = {}
    for archivo in sorted(GUIDELINES_ROOT.glob("*/variables.yaml")):
        datos = yaml.safe_load(archivo.read_text(encoding="utf-8")) or {}
        for nombre, d in (datos.get("variables") or {}).items():
            entrada = definiciones.setdefault(
                nombre, {"tipo": d.get("type"), "valores": set(), "minimo": None, "maximo": None}
            )
            entrada["valores"].update(str(v) for v in d.get("allowed_values") or [])
            for clave, fuente, elegir in (("minimo", "minimum", min), ("maximo", "maximum", max)):
                if d.get(fuente) is not None:
                    actual = entrada[clave]
                    entrada[clave] = d[fuente] if actual is None else elegir(actual, d[fuente])
    return definiciones


@lru_cache(maxsize=1)
def variables_de_biomarcadores() -> frozenset[str]:
    """Variables que alimenta HC-04: no se registran sueltas por chat."""
    variables = set()
    for definicion in cargar_catalogo().values():
        variables.update(r.variable_tx for r in definicion.accionable if r.variable_tx)
        variables.update(v for v, _ in definicion.otros_tx.values())
    return frozenset(variables)


def validar_datos(datos: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """``(datos_normalizados, errores)``. Los categóricos se guardan con la
    grafía exacta de la guía; los numéricos, como número."""
    definiciones = definiciones_variables()
    biomarcadores = variables_de_biomarcadores()
    normalizados: dict[str, Any] = {}
    errores: list[str] = []
    if not datos:
        return {}, ["No se indicó ningún dato para registrar."]

    for variable, valor in datos.items():
        variable = str(variable).strip()
        if variable in biomarcadores:
            errores.append(
                f"'{variable}' es un biomarcador: se registra con su biopsia en HC-04 (validación estricta y "
                "doble ingreso), o confirmando el biomarcador pendiente; no como dato suelto."
            )
            continue
        definicion = definiciones.get(variable)
        if definicion is None:
            errores.append(f"'{variable}' no es una variable de ninguna guía (use listar_variables_requeridas).")
            continue
        tipo = definicion["tipo"]
        if valor is None or str(valor).strip() == "":
            errores.append(f"'{variable}' no tiene valor.")
        elif tipo in ("integer", "number"):
            try:
                numero = float(valor)
            except (TypeError, ValueError):
                errores.append(f"'{variable}' debe ser numérico; se recibió {valor!r}.")
                continue
            if tipo == "integer":
                if not numero.is_integer():
                    errores.append(f"'{variable}' debe ser un número entero; se recibió {valor!r}.")
                    continue
                numero = int(numero)
            if definicion["minimo"] is not None and numero < definicion["minimo"]:
                errores.append(f"'{variable}' debe ser >= {definicion['minimo']}; se recibió {numero}.")
            elif definicion["maximo"] is not None and numero > definicion["maximo"]:
                errores.append(f"'{variable}' debe ser <= {definicion['maximo']}; se recibió {numero}.")
            else:
                normalizados[variable] = numero
        elif tipo == "categorical":
            canonico = {v.lower(): v for v in definicion["valores"]}.get(str(valor).strip().lower())
            if canonico is None:
                errores.append(
                    f"'{valor}' no es un valor permitido de '{variable}' ({', '.join(sorted(definicion['valores']))})."
                )
            else:
                normalizados[variable] = canonico
        else:
            errores.append(f"'{variable}' es de tipo {tipo!r}: no se registra por chat.")
    return normalizados, errores


def _oncologo(config: Optional[RunnableConfig]) -> Optional[int]:
    return (config or {}).get("configurable", {}).get("oncologo_id")


def _error(mensaje: str, **extra: Any) -> str:
    return json.dumps({"registrado": False, "error": mensaje, **extra}, ensure_ascii=False)


_SIN_ONCOLOGO = (
    "No se pudo determinar el oncólogo autenticado (falta oncologo_id en la sesión). Es un problema de "
    "configuración, no algo que el oncólogo deba resolver en el chat: informa que no se puede guardar ahora."
)


@tool
def registrar_datos_clinicos_paciente(
    patient_id: int, datos: dict[str, Any], config: RunnableConfig = None
) -> str:
    """GUARDA en el expediente de un paciente YA REGISTRADO las variables
    clínicas que el oncólogo dio explícitamente en el chat (p. ej.
    disease_setting, molecular_pathway_status, treatment_line,
    immunotherapy_contraindication, smoking_status, clinical_m_status...).
    Úsala cuando el oncólogo pida guardarlas o cuando el siguiente paso las
    necesite guardadas (chequear_interacciones_tratamiento y
    registrar_decision_tratamiento leen SOLO lo guardado, no lo que se usó
    en completar_datos_paciente_y_recomendar).

    datos es un objeto {variable: valor} con nombres exactos y valores
    permitidos (consúltalos con listar_variables_requeridas). Pasa SOLO lo
    que el oncólogo dijo: nunca inventes, completes ni deduzcas valores.

    Antes de ejecutarse, la conversación se PAUSA para que el oncólogo
    apruebe, edite o rechace lo que se va a guardar: es intencional.
    Si algún dato no es válido no se guarda nada; explícale los errores.
    Los biomarcadores (egfr_status, alk_status, her2_status, er_status,
    pr_status, braf_v600_status, pdl1_tps) NO se registran aquí: se
    registran con su biopsia (HC-04) o confirmando el biomarcador pendiente.
    El oncólogo que registra se toma de la sesión; no lo pidas."""
    resuelto = obtener_paciente_o_error(patient_id)
    if isinstance(resuelto, ErrorPacienteNoEncontrado):
        return resuelto.a_json()
    oncologo_id = _oncologo(config)
    if not oncologo_id:
        return _error(_SIN_ONCOLOGO)

    normalizados, errores = validar_datos(datos or {})
    if errores:
        return _error("No se guardó ningún dato: hay valores inválidos.", errores=errores)

    conn = obtener_conexion()
    with conn_lock:
        ids = registrar_datos_clinicos(conn, patient_id, normalizados)
    return json.dumps(
        {
            "registrado": True,
            "paciente_id": patient_id,
            "datos_guardados": normalizados,
            "filas": ids,
            "registrado_por_oncologo_id": oncologo_id,
            "mensaje": "Datos guardados en el expediente. Ya los usan las recomendaciones, el chequeo de "
                       "interacciones y el registro de la decisión.",
        },
        ensure_ascii=False,
    )


@tool
def registrar_conciliacion_medicamentos(
    patient_id: int,
    medicamentos: Optional[list[str]] = None,
    sin_medicacion_concomitante: bool = False,
    config: RunnableConfig = None,
) -> str:
    """GUARDA la conciliación de la medicación concomitante de un paciente
    YA REGISTRADO, tal como la informó el oncólogo en el chat. Sin
    conciliación, chequear_interacciones_tratamiento no puede afirmar que
    no hay interacciones.

    - Si el oncólogo dice que el paciente toma medicamentos, pasa
      medicamentos con sus nombres tal cual los dijo.
    - Si el oncólogo dice EXPLÍCITAMENTE que no toma ninguno, pasa
      sin_medicacion_concomitante=true (y no pases medicamentos).
    Nunca supongas que no toma medicamentos porque no se mencionaron.

    La lista reemplaza a la anterior (la anterior queda con fecha de fin,
    no se borra). Antes de ejecutarse, la conversación se PAUSA para que
    el oncólogo apruebe, edite o rechace lo que se va a guardar. El
    oncólogo que registra se toma de la sesión; no lo pidas."""
    resuelto = obtener_paciente_o_error(patient_id)
    if isinstance(resuelto, ErrorPacienteNoEncontrado):
        return resuelto.a_json()
    oncologo_id = _oncologo(config)
    if not oncologo_id:
        return _error(_SIN_ONCOLOGO)

    nombres = [m.strip() for m in (medicamentos or []) if m and str(m).strip()]
    if nombres and sin_medicacion_concomitante:
        return _error("Indica medicamentos o sin_medicacion_concomitante=true, no ambos.")
    if not nombres and not sin_medicacion_concomitante:
        return _error(
            "No se guardó nada: una lista vacía no significa 'sin medicación'. Si el oncólogo confirmó que no "
            "toma ninguno, usa sin_medicacion_concomitante=true."
        )

    conn = obtener_conexion()
    with conn_lock:
        registrar_conciliacion(conn, patient_id, nombres, oncologo_id)
        estado = obtener_estado_conciliacion(conn, patient_id)
    return json.dumps(
        {
            "registrado": True,
            "paciente_id": patient_id,
            "estado_conciliacion": estado,
            "medicamentos": nombres,
            "registrado_por_oncologo_id": oncologo_id,
        },
        ensure_ascii=False,
    )
