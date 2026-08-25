"""Agente conversacional (LangChain + Ollama local) para TX-01.

Diseño acordado explícitamente con el curso (se exige agente/tool-calling
para esta historia): el agente SIEMPRE pasa por las tools deterministas
para obtener datos del paciente y candidatos de tratamiento -- nunca lee
ni interpreta directamente el YAML de guidelines/ ni decide un régimen
por su cuenta. Las tools son wrappers delgados sobre
tx_clinica.builder/tx_clinica.patient_facts (deterministas) y devuelven
JSON estructurado; el LLM solo:
  1. decide qué paciente corresponde (por id, si el oncólogo lo da) o
     construye los facts a partir de lo que el oncólogo describió en el
     chat (si no hay un paciente registrado),
  2. llama las tools en el orden correcto,
  3. redacta una respuesta en lenguaje natural a partir de lo que las
     tools devolvieron.

Tres tools:
  - obtener_datos_paciente: lee la base de datos mock y devuelve los
    facts estructurados de un paciente ya registrado (para que el
    oncólogo pueda preguntar "¿qué datos tiene el paciente 3?").
  - obtener_recomendaciones_tratamiento_por_id: recomendación para un
    paciente YA REGISTRADO en la base de datos (busca sus facts solo,
    sin que el oncólogo tenga que repetirlos).
  - obtener_recomendaciones_tratamiento_con_datos: recomendación para un
    caso descrito directamente en el chat (sin ID de paciente, sin base
    de datos) -- el oncólogo escribe los datos clínicos y el agente los
    estructura como el objeto de facts (dict) que la tool espera.

Validación post-respuesta: cualquier regimen_id que el agente mencione en
su respuesta final debe existir en el resultado de la tool que llamó en
este turno. Si no, se descarta la respuesta (mismo principio que
generator.py de IA-02 validando source_span_ids).

NOTA DE MIGRACIÓN (langchain 1.x):
  Esta versión usa `create_agent`, la API vigente en langchain>=1.0
  (AgentExecutor y create_tool_calling_agent quedaron en el paquete
  legacy). Cambia también cómo se invoca el agente resultante:

    agente = construir_agente()
    resultado = agente.invoke({"messages": [{"role": "user", "content": pregunta}]})
    respuesta_texto = resultado["messages"][-1].content

  En vez de `agente.invoke({"input": pregunta})["output"]` como con
  AgentExecutor. Si demo_tx.py todavía usa la forma vieja, hay que
  actualizarlo también.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_ollama import ChatOllama

from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.repository import obtener_paciente
from historia_clinica_mock.seed import sembrar_datos_sinteticos
from tx_clinica.builder import construir_recomendaciones_tratamiento
from tx_clinica.patient_facts import construir_facts_paciente

GUIDELINES_ROOT = Path("guidelines")  # ajustar a la raíz real del repo


# ---------------------------------------------------------------------
# Conexión a la base de datos mock -- un módulo, una sola conexión.
#
# Nota para producción real: aquí se usa una base en memoria sembrada
# con los datos sintéticos al arrancar, porque este es un prototipo
# académico sobre historia_clinica_mock. Si el repo ya usa un archivo
# .db persistente en otra parte del proyecto, cambiar crear_conexion()
# por la ruta de ese archivo para que el agente vea los mismos pacientes
# que el resto de la aplicación.
# ---------------------------------------------------------------------
_conn: Optional[sqlite3.Connection] = None

# create_agent (LangGraph por debajo) ejecuta las tools en un pool de
# hilos, no en el hilo principal. sqlite3 por defecto revienta con
# "SQLite objects created in a thread can only be used in that same
# thread" si la conexión se usa así. check_same_thread=False le dice a
# sqlite3 que no valide eso, pero la conexión sigue sin ser segura para
# accesos concurrentes reales -- por eso además serializamos todo uso
# de _conn con este lock (una tool a la vez toca la base).
_conn_lock = threading.Lock()


def _obtener_conexion() -> sqlite3.Connection:
    global _conn
    with _conn_lock:
        if _conn is None:
            _conn = crear_conexion(":memory:", check_same_thread=False)
            sembrar_datos_sinteticos(_conn)
        return _conn


@tool
def obtener_datos_paciente(patient_id: int) -> str:
    """Devuelve, en JSON, los datos clínicos estructurados de un paciente
    YA REGISTRADO en la base de datos (identificación, diagnóstico
    principal, estadio, y todas las variables clínicas usadas por las
    guías: estadio TNM, biomarcadores, ECOG, etc.). Usa esta tool cuando
    el oncólogo pregunte qué datos tiene un paciente, o antes de generar
    una recomendación por id de paciente, para poder mencionar sus datos
    reales en la respuesta."""
    conn = _obtener_conexion()
    with _conn_lock:
        paciente = obtener_paciente(conn, patient_id)
        if paciente is None:
            return json.dumps({"error": f"No existe ningún paciente con id={patient_id}."})

        facts = construir_facts_paciente(conn, patient_id)
    return json.dumps(
        {
            "paciente_id": patient_id,
            "nombre": paciente.nombre,
            "diagnostico_principal": paciente.diagnostico_principal,
            "estadio_registrado": paciente.estadio,
            "facts_clinicos": facts,
        },
        ensure_ascii=False,
    )


def _construir_respuesta_recomendaciones(patient_id: int, facts: dict[str, Any]) -> str:
    resultado = construir_recomendaciones_tratamiento(patient_id, facts, GUIDELINES_ROOT)

    if resultado.sin_guia_aplicable:
        return json.dumps({"sin_guia_aplicable": True, "mensaje": resultado.disclaimer}, ensure_ascii=False)

    return json.dumps(
        {
            "sin_guia_aplicable": False,
            "module_id": resultado.module_id,
            "candidatos": [
                {
                    "regimen_id": c.regimen_id,
                    "fase": c.fase,
                    "farmacos": list(c.farmacos),
                    "audit_effect": c.audit_effect,
                    "rule_id_disparada": c.rule_id_disparada,
                    "evidencia": c.evidencia.resumen_citable() if c.evidencia else None,
                }
                for c in resultado.candidatos
            ],
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
    que no vengan en este resultado."""
    conn = _obtener_conexion()
    with _conn_lock:
        paciente = obtener_paciente(conn, patient_id)
        if paciente is None:
            return json.dumps({"error": f"No existe ningún paciente con id={patient_id}."})

        facts = construir_facts_paciente(conn, patient_id)
    return _construir_respuesta_recomendaciones(patient_id, facts)


@tool
def obtener_recomendaciones_tratamiento_con_datos(facts_paciente: dict[str, Any]) -> str:
    """Devuelve, en JSON, los candidatos de tratamiento para un caso
    descrito DIRECTAMENTE EN EL CHAT (sin id de paciente registrado en la
    base de datos). facts_paciente es un objeto (no un string) con las
    variables clínicas que el oncólogo mencionó (estadio, biomarcadores,
    ECOG, etc.), usando el vocabulario de variables.yaml del módulo que
    aplique. Usa esta tool cuando el oncólogo describa un caso hipotético
    o un paciente que no está en la base de datos. No completes ni
    inventes variables que el oncólogo no mencionó -- pásalas tal cual
    las dio; si falta un dato, la tool ya maneja eso mostrando el
    régimen como no evaluable en vez de asumir un valor."""
    return _construir_respuesta_recomendaciones(-1, facts_paciente)


_SYSTEM_PROMPT = """Eres un asistente que ayuda a un oncólogo a consultar datos de \
pacientes y opciones de tratamiento sugeridas por el sistema.

Reglas obligatorias:
- Si el oncólogo menciona un paciente por id o por nombre que reconoces como \
registrado, usa obtener_datos_paciente y/o obtener_recomendaciones_tratamiento_por_id \
-- nunca le pidas que repita datos que ya están en la base de datos.
- Si el oncólogo describe un caso clínico directamente en el chat (sin \
referirse a un paciente registrado), estructura lo que dijo como JSON y \
usa obtener_recomendaciones_tratamiento_con_datos. No inventes valores \
para datos que el oncólogo no mencionó.
- SIEMPRE debes llamar una de las tools de recomendación antes de sugerir \
cualquier tratamiento -- nunca respondas con conocimiento propio sobre qué \
régimen es apropiado.
- Si la tool indica sin_guia_aplicable=true, dilo explícitamente en vez de \
sugerir algo genérico. Si no hay candidatos, dilo explícitamente.
- Cita únicamente los regimen_id, fases y evidencia que la tool haya \
devuelto -- nunca menciones un régimen que no esté en la respuesta de la tool.
- Deja siempre claro que esto es apoyo a la decisión clínica, no una \
prescripción."""


def construir_agente(model: str = "qwen2.5:14b-instruct-q4_K_M"):
    """Construye el agente de tool-calling sobre Ollama local.

    Devuelve un grafo compilado de LangGraph (lo que produce
    `create_agent` en langchain>=1.0), no un AgentExecutor. Se invoca
    así:

        agente = construir_agente()
        resultado = agente.invoke(
            {"messages": [{"role": "user", "content": pregunta}]}
        )
        respuesta_texto = resultado["messages"][-1].content
    """
    llm = ChatOllama(model=model, temperature=0.1)
    tools = [
        obtener_datos_paciente,
        obtener_recomendaciones_tratamiento_por_id,
        obtener_recomendaciones_tratamiento_con_datos,
    ]
    return create_agent(model=llm, tools=tools, system_prompt=_SYSTEM_PROMPT)