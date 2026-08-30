from __future__ import annotations

import json
import sqlite3
import threading
import unicodedata
from pathlib import Path
from typing import Any, Optional

import yaml
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_ollama import ChatOllama

from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.repository import obtener_paciente
from historia_clinica_mock.seed import sembrar_datos_sinteticos
from tx_clinica.builder import construir_recomendaciones_tratamiento
from tx_clinica.models import SIN_GUIA_APLICABLE
from tx_clinica.module_selector import MODULOS_FUERA_DE_ALCANCE
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
        # SIN_GUIA_APLICABLE (mensaje específico: "no hay módulo de guía
        # que aplique a este caso") es DISTINTO de resultado.disclaimer
        # (mensaje genérico: "esto es apoyo, no prescripción"). Usar el
        # genérico aquí producía respuestas contradictorias del agente
        # ("no hay opción específica" + "estas son las opciones sugeridas").
        return json.dumps({"sin_guia_aplicable": True, "mensaje": SIN_GUIA_APLICABLE}, ensure_ascii=False)

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
                    "advertencia_comorbilidad": c.advertencia_comorbilidad,
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
    inventes variables que el oncólogo no mencionó -- si no sabes qué
    campos pedir, usa primero listar_variables_requeridas."""
    return _construir_respuesta_recomendaciones(-1, facts_paciente)


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.casefold()
    # Unifica separadores (espacio, guión, guión bajo) para que
    # "NSCLC metastatic non-oncogene" (lenguaje natural) sí compare
    # igual que "nsclc_metastatic_non_oncogene" (nombre real de carpeta).
    for separador in ("-", "_"):
        texto = texto.replace(separador, " ")
    return " ".join(texto.split())


def _leer_yaml(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as f:
        return yaml.safe_load(f)


@tool
def listar_variables_requeridas(cancer_type_o_modulo: str) -> str:
    """Devuelve, en JSON, la lista de variables clínicas (nombre y
    valores permitidos) que un módulo de guía necesita para poder
    evaluar tratamiento. Usa esta tool SIEMPRE que el oncólogo pida una
    recomendación de tratamiento sin haber dado datos clínicos
    suficientes todavía, o pregunte explícitamente qué información
    necesitas -- nunca inventes ni asumas qué campos pedir, esta tool te
    da los reales.

    cancer_type_o_modulo puede ser el tipo de cáncer en lenguaje natural
    (ej. 'cáncer de pulmón', 'melanoma') o el nombre EXACTO de la carpeta
    del módulo si ya lo conoces (ej. 'nsclc_metastatic_non_oncogene').

    IMPORTANTE: si varios módulos de guía coinciden con lo que
    escribiste (ej. 'NSCLC' coincide con 3 módulos distintos: temprano,
    metastásico sin oncogén, y metastásico con oncogén conductor), esta
    tool NO elige uno por ti -- te devuelve
    necesita_desambiguacion=true con la lista de módulos posibles y su
    alcance clínico. En ese caso, pregúntale al oncólogo cuál aplica
    (o vuelve a llamar esta tool con el nombre EXACTO de carpeta del
    módulo correcto una vez lo sepas) -- nunca asumas cuál es el
    correcto ni mezcles variables de un módulo con otro."""
    consulta = _normalizar(cancer_type_o_modulo)

    if not GUIDELINES_ROOT.exists():
        return json.dumps({"error": "No se encontró la carpeta guidelines/."})

    modulos_activos = [
        p for p in sorted(GUIDELINES_ROOT.iterdir())
        if p.is_dir() and p.name not in MODULOS_FUERA_DE_ALCANCE
    ]

    # Coincidencia EXACTA de nombre de carpeta: nunca es ambigua, se usa
    # directo aunque el texto también matchee otros módulos por substring.
    coincidencia_exacta = next((p for p in modulos_activos if _normalizar(p.name) == consulta), None)
    if coincidencia_exacta is not None:
        return _variables_de_modulo(coincidencia_exacta)

    candidatos = []
    for carpeta in modulos_activos:
        if consulta in _normalizar(carpeta.name) or _normalizar(carpeta.name) in consulta:
            candidatos.append(carpeta)
            continue
        metadata = _leer_yaml(carpeta / "metadata.yaml") or {}
        texto_metadata = _normalizar(
            str(metadata.get("name", "")) + " " + str(metadata.get("clinical_scope", ""))
        )
        if consulta and consulta in texto_metadata:
            candidatos.append(carpeta)

    if not candidatos:
        return json.dumps({
            "error": f"No se encontró ningún módulo de guía que coincida con '{cancer_type_o_modulo}'.",
            "modulos_disponibles": [p.name for p in modulos_activos],
        }, ensure_ascii=False)

    if len(candidatos) > 1:
        # Ambigüedad real: varios módulos coinciden (ej. "NSCLC" matchea
        # temprano/metastásico-sin-oncogén/metastásico-con-oncogén). No
        # se adivina cuál -- se listan todos con su alcance clínico Y un
        # resumen de evidencia (organización, año, validación, cantidad
        # de reglas positivas) para que el ONCÓLOGO decida cuál aplica,
        # o vuelva a llamar esta tool con el nombre exacto de carpeta
        # una vez lo sepa.
        opciones = []
        for carpeta in candidatos:
            metadata = _leer_yaml(carpeta / "metadata.yaml") or {}
            opciones.append({
                "modulo": carpeta.name,
                "nombre": metadata.get("name"),
                "alcance_clinico": metadata.get("clinical_scope"),
                "evidencia_del_modulo": _resumen_evidencia_modulo(carpeta, metadata),
            })
        return json.dumps({
            "necesita_desambiguacion": True,
            "modulos_posibles": opciones,
        }, ensure_ascii=False)

    return _variables_de_modulo(candidatos[0])


def _resumen_evidencia_modulo(carpeta: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    """Resumen de evidencia a nivel de módulo -- no decide nada por el
    oncólogo, solo le da contexto real (cuántas reglas hay, con qué
    respaldo) para que él elija entre módulos ambiguos con más
    información que solo el nombre."""
    source = metadata.get("source") or {}
    validation = metadata.get("validation") or {}

    total_reglas = 0
    reglas_con_soporte_positivo = 0
    niveles_evidencia_presentes: set[str] = set()

    rules_dir = carpeta / "rules"
    if rules_dir.exists():
        for archivo in sorted(rules_dir.glob("*.yaml")):
            payload = _leer_yaml(archivo) or {}
            for regla in payload.get("rules", []):
                total_reglas += 1
                conclusion = regla.get("conclusion") or {}
                if conclusion.get("audit_effect") == "supports_prescription":
                    reglas_con_soporte_positivo += 1
                nivel = ((regla.get("evidence") or {}).get("native") or {}).get("evidence_level")
                if nivel:
                    niveles_evidencia_presentes.add(str(nivel))

    return {
        "organizacion": metadata.get("organization"),
        "titulo_fuente": source.get("title"),
        "anio_publicacion": source.get("publication_year"),
        "doi": source.get("doi"),
        "estado_validacion_clinica": validation.get("clinical_validation_status"),
        "total_reglas_en_el_modulo": total_reglas,
        "reglas_con_recomendacion_positiva": reglas_con_soporte_positivo,
        "niveles_de_evidencia_presentes": sorted(niveles_evidencia_presentes),
    }


def _variables_de_modulo(carpeta: Path) -> str:
    variables_payload = _leer_yaml(carpeta / "variables.yaml") or {}
    variables = variables_payload.get("variables", {})

    resumen = {}
    for nombre, definicion in variables.items():
        if not isinstance(definicion, dict):
            continue
        entrada: dict[str, Any] = {"tipo": definicion.get("type")}
        if "allowed_values" in definicion:
            entrada["valores_permitidos"] = definicion["allowed_values"]
        resumen[nombre] = entrada

    return json.dumps(
        {"necesita_desambiguacion": False, "modulo": carpeta.name, "variables_disponibles": resumen},
        ensure_ascii=False,
    )


_SYSTEM_PROMPT = """Eres un asistente que ayuda a un oncólogo a consultar datos de \
pacientes y opciones de tratamiento sugeridas por el sistema.

Reglas obligatorias:
- Si el oncólogo menciona un paciente por id o por nombre que reconoces como \
registrado, usa obtener_datos_paciente y/o obtener_recomendaciones_tratamiento_por_id \
-- nunca le pidas que repita datos que ya están en la base de datos.
- Si el oncólogo describe un caso clínico directamente en el chat (sin \
referirse a un paciente registrado) y pide una recomendación de tratamiento, \
llama primero listar_variables_requeridas para saber el vocabulario exacto \
del módulo correspondiente. Si necesita_desambiguacion=true, pregúntale al \
oncólogo cuál de los módulos posibles aplica (usando el alcance clínico y la \
evidencia de cada uno que la tool te dio) -- nunca elijas uno por tu cuenta.
- Después de tener la lista de variables del módulo correcto, extrae DE LO \
QUE EL ONCÓLOGO YA ESCRIBIÓ todos los valores que puedas mapear directamente \
-- no le pidas que repita datos que ya dio en su mensaje original.
- PROHIBIDO inventar, adivinar o asumir un valor por defecto para CUALQUIER \
variable que el oncólogo no haya mencionado explícitamente (ej. no asumas \
histology=non_squamous, ecog_ps=0, ni ningún otro valor "típico" o "más \
común"). Si una variable relevante falta, pregúntala explícitamente por su \
nombre real y sus valores permitidos -- nunca la incluyas en el JSON de \
facts como si el oncólogo la hubiera dado.
- No le pidas al oncólogo que "confirme" datos que ya te dio con claridad en \
su mensaje original -- eso genera fricción innecesaria. Solo pregunta por \
las variables genuinamente ausentes.
- Solo cuando tengas datos suficientes (sin haber inventado ninguno), \
estructura los facts y usa obtener_recomendaciones_tratamiento_con_datos.
- SIEMPRE debes llamar una de las tools de recomendación antes de sugerir \
cualquier tratamiento -- nunca respondas con conocimiento propio sobre qué \
régimen es apropiado.
- CADA VEZ que el oncólogo describa un caso clínico y pida una recomendación, \
así se parezca a un caso anterior de esta misma conversación, DEBES volver a \
llamar la tool con los datos de ESTE mensaje -- PROHIBIDO reutilizar, copiar \
o parafrasear el resultado de una tool de un turno anterior para responder a \
un caso nuevo. Cada paciente/caso descrito es una llamada nueva, sin \
excepción, incluso si los regímenes terminan siendo los mismos.
- Si la tool indica sin_guia_aplicable=true, dilo explícitamente en vez de \
sugerir algo genérico. Si no hay candidatos, dilo explícitamente.
- Cita únicamente los regimen_id, fases y evidencia que la tool haya \
devuelto -- nunca menciones un régimen que no esté en la respuesta de la tool.
- Si un candidato trae advertencia_comorbilidad distinta de null, SIEMPRE \
menciónala explícitamente en tu respuesta y deja claro que ese régimen NO \
se presenta como primera línea sin revisión -- nunca omitas esa advertencia \
ni la presentes como si el régimen fuera una recomendación de primera línea \
normal.
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
        listar_variables_requeridas,
    ]
    return create_agent(model=llm, tools=tools, system_prompt=_SYSTEM_PROMPT)