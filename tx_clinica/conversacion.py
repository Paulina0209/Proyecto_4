
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from langgraph.types import Command

from tx_clinica.observability import registrar_scores_decision, traza_conversacion


@dataclass
class RespuestaAgente:
    #: Texto final para el oncólogo. None si el grafo quedó pausado.
    texto: Optional[str]
    #: Lista de Interrupt de LangGraph pendientes de resolver. Vacía si
    #: no hay nada pendiente.
    pendientes_aprobacion: list[Any] = field(default_factory=list)
    trace_id: Optional[str] = None
    #: Historial COMPLETO de mensajes de la conversación (estado del
    #: checkpointer) después de este paso. Sirve para depurar: ver qué
    #: tools llamó el modelo y con qué argumentos.
    mensajes: list[Any] = field(default_factory=list)

    @property
    def esta_pausada(self) -> bool:
        return bool(self.pendientes_aprobacion)


def _armar_respuesta(resultado: dict[str, Any], trace_id: Optional[str]) -> RespuestaAgente:
    mensajes = list(resultado.get("messages") or [])
    pendientes = list(resultado.get("__interrupt__") or [])
    if pendientes:
        return RespuestaAgente(
            texto=None, pendientes_aprobacion=pendientes, trace_id=trace_id, mensajes=mensajes
        )

    return RespuestaAgente(texto=_texto_de(mensajes[-1]) if mensajes else None, trace_id=trace_id, mensajes=mensajes)


def _texto_de(mensaje: Any) -> Optional[str]:
    """Texto plano del mensaje. Con modelos que responden por la API de
    Responses (p. ej. gpt-6-luna), ``content`` es una lista de bloques
    (``[{"type": "text", "text": ...}]``), no un str: ``.text`` los une."""
    texto = getattr(mensaje, "text", None)
    if isinstance(texto, str):
        return str(texto) or None  # .text es una subclase de str (TextAccessor)
    contenido = getattr(mensaje, "content", None)
    return contenido if isinstance(contenido, str) else None


def enviar_mensaje(
    agente: Any,
    texto: str,
    thread_id: str,
    oncologo_id: Optional[int] = None,
) -> RespuestaAgente:
    with traza_conversacion(thread_id, oncologo_id, nombre="tx_clinica.mensaje") as traza:
        traza.span.update(input=texto)
        resultado = agente.invoke(
            {"messages": [{"role": "user", "content": texto}]},
            config=traza.config,
        )
        respuesta = _armar_respuesta(resultado, traza.trace_id)
        traza.span.update(
            output=respuesta.texto if not respuesta.esta_pausada else {"pausado_por_aprobacion_humana": True}
        )
    return respuesta


def reanudar_con_decisiones(
    agente: Any,
    decisiones: Sequence[dict[str, Any]],
    thread_id: str,
    oncologo_id: Optional[int] = None,
) -> RespuestaAgente:
    """Reanuda una pausa de HumanInTheLoopMiddleware.

    `decisiones` lleva UNA entrada por cada acción pendiente, en el mismo
    orden (normalmente es una sola: registrar_decision_tratamiento):

        [{"type": "approve"}]
        [{"type": "reject", "message": "motivo"}]

    (La forma exacta del payload de "edit" varía entre versiones de
    langchain -- ver la nota de agent.py; no se incluye aquí.)
    """
    decisiones = list(decisiones)
    with traza_conversacion(thread_id, oncologo_id, nombre="tx_clinica.reanudar") as traza:
        traza.span.update(input={"decisiones_hitl": decisiones})
        resultado = agente.invoke(
            Command(resume={"decisions": decisiones}),
            config=traza.config,
        )
        respuesta = _armar_respuesta(resultado, traza.trace_id)
        traza.span.update(
            output=respuesta.texto if not respuesta.esta_pausada else {"pausado_por_aprobacion_humana": True}
        )

        # Justo después de reanudar es seguro puntuar: el último
        # ToolMessage de registrar_decision_tratamiento es de ESTA pausa.
        tipos = [d.get("type") for d in decisiones if d.get("type")]
        registrar_scores_decision(
            traza.trace_id,
            resultado.get("messages") or [],
            aprobacion_humana=tipos[0] if len(tipos) == 1 else ",".join(tipos) or None,
        )
    return respuesta
