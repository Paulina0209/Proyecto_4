"""Observabilidad con Langfuse para el agente de guidelineUpdate.

Igual que tx_clinica/observability.py, este archivo concentra todo lo de
Langfuse: graph.py solo llama a llamar_claude() en vez de
client.messages.create(), y main.py envuelve cada modulo en
traza_modulo().

Diseño:

  - Una traza por modulo procesado (span raiz "guidelineUpdate.modulo"),
    con session_id = "guidelineUpdate-<fecha>": todos los modulos de una
    misma corrida quedan en la misma sesion.

  - NO se usa el CallbackHandler de LangChain: registraria el estado del
    grafo en cada nodo, y ese estado lleva la api_key de Anthropic y las
    imagenes en base64. En su lugar, llamar_claude() registra cada llamada
    a Claude como observacion de tipo "generation", con modelo, tokens
    (incluido prompt caching) y stop_reason.

  - Las imagenes de los slides NO se envian a Langfuse: el base64 se
    reemplaza por un marcador con el tamaño, para no inflar las trazas.

  - La observabilidad nunca debe romper el agente: si falla el registro
    en Langfuse, la llamada a Claude se hace igual.

Variables de entorno: las mismas LANGFUSE_* del .env (ver .env.example).
"""

from __future__ import annotations

import datetime
import logging
from contextlib import contextmanager, nullcontext
from typing import Any, Iterator

from langfuse import get_client, propagate_attributes

logger = logging.getLogger(__name__)


def _sin_imagenes(contenido: Any) -> Any:
    """Copia de messages/system con el base64 de las imagenes reemplazado."""
    if isinstance(contenido, list):
        return [_sin_imagenes(c) for c in contenido]
    if isinstance(contenido, dict):
        if contenido.get("type") == "image" and isinstance(contenido.get("source"), dict):
            # Sin la forma {"type": "base64", "data": ...}: Langfuse la toma
            # por un adjunto e intenta decodificar el marcador.
            fuente = contenido["source"]
            return {"type": "image", "omitida": f"{fuente.get('media_type')}, {len(fuente.get('data') or '')} caracteres base64"}
        return {k: _sin_imagenes(v) for k, v in contenido.items()}
    return contenido


def _uso(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    detalles = {
        "input": getattr(usage, "input_tokens", None),
        "output": getattr(usage, "output_tokens", None),
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
    }
    return {k: v for k, v in detalles.items() if isinstance(v, int)}


def _abrir_generacion(nombre: str, kwargs: dict[str, Any]):
    try:
        return get_client().start_as_current_observation(
            as_type="generation",
            name=nombre,
            model=kwargs.get("model"),
            model_parameters={"max_tokens": kwargs.get("max_tokens")},
            input={
                "system": _sin_imagenes(kwargs.get("system")),
                "messages": _sin_imagenes(kwargs.get("messages")),
            },
        )
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo abrir la generacion en Langfuse.", exc_info=True)
        return nullcontext(None)


def llamar_claude(client: Any, nombre: str, **kwargs: Any) -> Any:
    """client.messages.create(**kwargs) registrado en Langfuse como generation."""
    with _abrir_generacion(nombre, kwargs) as generacion:
        response = client.messages.create(**kwargs)
        if generacion is not None:
            try:
                texto = "".join(b.text for b in response.content if b.type == "text")
                generacion.update(
                    model=kwargs.get("model"),
                    output=texto,
                    usage_details=_uso(response),
                    metadata={"stop_reason": response.stop_reason},
                    level="WARNING" if response.stop_reason in ("max_tokens", "refusal") else "DEFAULT",
                )
            except Exception:  # noqa: BLE001
                logger.warning("No se pudo registrar la respuesta en Langfuse.", exc_info=True)
        return response


@contextmanager
def traza_modulo(module_id: str, session_id: str | None = None) -> Iterator[Any]:
    """Envuelve el procesamiento de UN modulo en una traza de Langfuse.

        with traza_modulo("breast_early") as span:
            resultado = app.invoke(estado)
            span.update(output=...)
    """
    session_id = session_id or f"guidelineUpdate-{datetime.date.today().isoformat()}"
    langfuse = get_client()
    with langfuse.start_as_current_observation(
        as_type="span", name="guidelineUpdate.modulo", input={"module_id": module_id}
    ) as span:
        with propagate_attributes(
            session_id=session_id,
            tags=["guidelineUpdate", module_id],
            metadata={"module_id": module_id},
        ):
            yield span


def vaciar_langfuse() -> None:
    """flush() de eventos pendientes; obligatorio antes de que termine main.run()."""
    try:
        get_client().flush()
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo hacer flush de Langfuse.", exc_info=True)
