"""Observabilidad con Langfuse para el agente de tx_clinica.

Este archivo concentra TODO lo de Langfuse a propósito: agent.py, las
tools y el middleware no saben que Langfuse existe. Si mañana se cambia
de herramienta de observabilidad, solo se toca este archivo.

Diseño:

  - Cada llamada a agente.invoke() se envuelve en un span raíz
    (traza_conversacion) y dentro de él se propagan session_id / user_id /
    tags con propagate_attributes(). Se hace así, y no vía
    config["metadata"]["langfuse_session_id"], porque con agentes de
    LangGraph esos metadata a veces quedan solo en un span hijo y no en
    el trace padre (issue abierto en el repo de Langfuse).

  - session_id = thread_id: los turnos de una misma conversación quedan
    agrupados en una sola sesión en Langfuse. Una pausa de
    HumanInTheLoopMiddleware (TX-04) + su reanudación son DOS invoke(),
    o sea dos traces, pero dentro de la misma sesión.

  - La observabilidad NUNCA debe romper el agente: todo lo que hace
    escrituras a Langfuse fuera del camino crítico (scores, flush) va en
    try/except y solo deja un warning en el log.

Privacidad: los traces guardan inputs/outputs COMPLETOS de cada tool
(nombre del paciente, facts clínicos, medicación, justificaciones del
oncólogo). Ver _mascara_langfuse() y LANGFUSE_MASK_DATOS_PACIENTE. La
máscara es de mejor esfuerzo; para datos reales, la protección de verdad
es self-hosting (o la región HIPAA de Langfuse Cloud).

Variables de entorno (ver .env.example):
    LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
    LANGFUSE_TRACING_ENABLED=false     -> apaga el tracing sin tocar código
    LANGFUSE_MASK_DATOS_PACIENTE=true  -> activa la máscara de datos
"""

from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Optional, Sequence

from langfuse import Langfuse, get_client, propagate_attributes
from langfuse.langchain import CallbackHandler

logger = logging.getLogger(__name__)

TOOL_DECISION = "registrar_decision_tratamiento"

# ---------------------------------------------------------------------
# Máscara de datos del paciente
# ---------------------------------------------------------------------

#: Claves de dict cuyo valor se redacta antes de enviarse a Langfuse.
#: Hoy solo "nombre" (lo devuelve obtener_datos_paciente). Agregar aquí
#: cualquier otro campo identificador que se sume a las tools.
_CLAVES_SENSIBLES = {"nombre"}
_REDACTADO = "[REDACTADO]"


def _mascarar_valor(data: Any) -> Any:
    """Redacta recursivamente _CLAVES_SENSIBLES.

    Las tools de este proyecto devuelven json.dumps(...) (un STRING), no
    un dict, así que los strings que parecen JSON se parsean, se
    enmascaran y se vuelven a serializar.

    Limitación conocida: no puede detectar un nombre escrito en texto
    libre (por ejemplo, si el oncólogo lo teclea en el chat o el modelo
    lo repite en su respuesta).
    """
    if isinstance(data, dict):
        return {
            k: (_REDACTADO if k in _CLAVES_SENSIBLES else _mascarar_valor(v))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_mascarar_valor(v) for v in data]
    if isinstance(data, str) and data.lstrip()[:1] in ("{", "["):
        try:
            return json.dumps(_mascarar_valor(json.loads(data)), ensure_ascii=False)
        except ValueError:
            return data
    return data


def _mascara_langfuse(data: Any, **kwargs: Any) -> Any:
    try:
        return _mascarar_valor(data)
    except Exception:  # noqa: BLE001 - ante la duda, no filtrar nada sensible
        return "[ERROR_AL_ENMASCARAR]"


# ---------------------------------------------------------------------
# Inicialización
# ---------------------------------------------------------------------

_init_lock = threading.Lock()
_inicializado = False


def _env_activo(nombre: str) -> bool:
    return os.getenv(nombre, "").strip().lower() in ("1", "true", "yes", "si", "sí")


def inicializar_langfuse() -> None:
    """Idempotente. Se llama una vez al construir el agente.

    Si LANGFUSE_MASK_DATOS_PACIENTE está activo, crea el cliente con la
    función de máscara; get_client() devuelve después ese mismo cliente.
    Si no, get_client() lo crea solo a partir de las variables de entorno.
    """
    global _inicializado
    with _init_lock:
        if _inicializado:
            return
        if _env_activo("LANGFUSE_MASK_DATOS_PACIENTE"):
            Langfuse(mask=_mascara_langfuse)
        _inicializado = True


def vaciar_langfuse() -> None:
    """flush() de eventos pendientes. Obligatorio antes de que termine un
    script corto (CLI, tests); en un servidor de larga vida no hace falta."""
    try:
        get_client().flush()
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo hacer flush de Langfuse.", exc_info=True)


# ---------------------------------------------------------------------
# Traza por invocación
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class TrazaActiva:
    #: Pasar tal cual como `config=` a agente.invoke(): trae el callback
    #: de Langfuse Y el thread_id que necesita el checkpointer.
    config: dict[str, Any]
    #: Para adjuntar scores después (puede ser None si el tracing está apagado).
    trace_id: Optional[str]
    #: Span raíz: sirve para poner input/output legibles en el trace.
    span: Any


@contextmanager
def traza_conversacion(
    thread_id: str,
    oncologo_id: Optional[int] = None,
    nombre: str = "tx_clinica.turno",
    tags: Sequence[str] = (),
) -> Iterator[TrazaActiva]:
    """Envuelve UN agente.invoke() en un trace de Langfuse.

        with traza_conversacion("consulta-4", oncologo_id=1) as traza:
            resultado = agente.invoke(entrada, config=traza.config)
    """
    inicializar_langfuse()
    langfuse = get_client()

    atributos: dict[str, Any] = {
        "session_id": thread_id,
        "tags": ["tx_clinica", *tags],
    }
    if oncologo_id is not None:
        atributos["user_id"] = str(oncologo_id)

    # C3: además de ir a Langfuse (arriba), oncologo_id viaja en
    # config["configurable"] -- es de ahí de donde lo lee
    # registrar_decision_tratamiento (vía RunnableConfig inyectado),
    # nunca como argumento que el LLM pudiera rellenar por su cuenta. Sin
    # esto, la tool no podría determinar quién firma la decisión.
    configurable: dict[str, Any] = {"thread_id": thread_id}
    if oncologo_id is not None:
        configurable["oncologo_id"] = oncologo_id

    with langfuse.start_as_current_observation(as_type="span", name=nombre) as span:
        with propagate_attributes(**atributos):
            # El handler se crea DENTRO del span para colgarse de él.
            handler = CallbackHandler()
            yield TrazaActiva(
                config={
                    "callbacks": [handler],
                    "configurable": configurable,
                },
                trace_id=getattr(span, "trace_id", None),
                span=span,
            )


# ---------------------------------------------------------------------
# Scores de la decisión clínica (TX-04)
# ---------------------------------------------------------------------


def _ultimo_resultado_decision(mensajes: Sequence[Any]) -> Optional[dict[str, Any]]:
    """Busca el último ToolMessage de registrar_decision_tratamiento y
    devuelve su JSON parseado (None si no hay, o si no es JSON -- por
    ejemplo cuando el oncólogo rechazó la aprobación humana y el
    middleware devuelve un texto, no el JSON de la tool)."""
    for m in reversed(list(mensajes)):
        if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == TOOL_DECISION:
            contenido = getattr(m, "content", None)
            if isinstance(contenido, str):
                try:
                    payload = json.loads(contenido)
                except ValueError:
                    return None
                return payload if isinstance(payload, dict) else None
            return None
    return None


def registrar_scores_decision(
    trace_id: Optional[str],
    mensajes: Sequence[Any],
    aprobacion_humana: Optional[str] = None,
) -> None:
    """Adjunta al trace dos scores categóricos:

      - aprobacion_humana: approve | edit | reject (lo que el oncólogo
        decidió en la pausa de HumanInTheLoopMiddleware).
      - decision_oncologo: accept | modify | reject (tipo_decision que
        realmente quedó guardado en la base de datos).

    Llamar SOLO justo después de reanudar una pausa: si se llamara en un
    turno cualquiera, el último ToolMessage podría ser de una decisión de
    un turno anterior y se puntuaría dos veces.
    """
    if not trace_id:
        return
    try:
        langfuse = get_client()
        if aprobacion_humana:
            langfuse.create_score(
                name="aprobacion_humana",
                value=aprobacion_humana,
                trace_id=trace_id,
                data_type="CATEGORICAL",
            )
        payload = _ultimo_resultado_decision(mensajes)
        if payload and payload.get("registrado") and payload.get("tipo_decision"):
            langfuse.create_score(
                name="decision_oncologo",
                value=str(payload["tipo_decision"]),
                trace_id=trace_id,
                data_type="CATEGORICAL",
                comment=f"decision_id={payload.get('decision_id')}",
            )
    except Exception:  # noqa: BLE001
        logger.warning("No se pudieron registrar los scores en Langfuse.", exc_info=True)