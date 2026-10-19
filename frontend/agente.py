"""Conversaciones con el agente de tratamiento (GPT + herramientas + aprobación humana) desde la interfaz.

Cada conversación es de un médico sobre UN paciente (``hilo``). El agente usa las
mismas tools que en ``demo_tx.py``, con dos garantías extra:

    - ``PACIENTES_PERMITIDOS``: mientras responde, las tools solo atienden al
      paciente abierto. Si el modelo pide otro id, la tool contesta que no existe.
    - Lo que el agente quiera guardar (datos, conciliación o la decisión final)
      se detiene hasta que el médico lo aprueba o lo rechaza en la pantalla
      (HumanInTheLoopMiddleware de ``tx_clinica``).

El agente se construye una sola vez por proceso; el estado de cada conversación
lo guarda su checkpointer, por ``thread_id``.
"""

from __future__ import annotations

import contextlib
import io
import os
import secrets
import threading
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from seguridad.models import Usuario


def _texto(mensaje: Any) -> Optional[str]:
    from tx_clinica.conversacion import _texto_de

    return _texto_de(mensaje)


class ConversacionesAgente:
    def __init__(self) -> None:
        self._agente = None
        self._cerrojo = threading.Lock()
        #: hilo -> (usuario_id, paciente_id)
        self._duenos: Dict[str, tuple] = {}

    def _construir(self):
        with self._cerrojo:
            if self._agente is None:
                from core import llm_config

                if not llm_config.obtener_api_key():
                    raise HTTPException(status_code=503, detail=(
                        "El asistente de tratamiento necesita la llave de OpenAI (OPENAI_API_KEY en el .env)."))
                os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false" if not os.environ.get("LANGFUSE_PUBLIC_KEY") else "true")
                from tx_clinica.agent import construir_agente

                with contextlib.redirect_stderr(io.StringIO()):
                    self._agente = construir_agente()
            return self._agente

    def _respuesta(self, hilo: str, respuesta) -> dict:
        herramientas: List[str] = []
        for m in respuesta.mensajes:
            for llamada in getattr(m, "tool_calls", None) or []:
                if llamada.get("name") not in herramientas:
                    herramientas.append(llamada.get("name"))
        pendientes = []
        for interrupcion in respuesta.pendientes_aprobacion:
            valor = getattr(interrupcion, "value", None) or {}
            for accion in valor.get("action_requests", []) if isinstance(valor, dict) else []:
                pendientes.append({"herramienta": accion.get("name"), "argumentos": accion.get("args") or accion.get("arguments"),
                                   "descripcion": accion.get("description")})
        return {"hilo": hilo, "texto": respuesta.texto, "pendientes": pendientes, "herramientas": herramientas}

    def _verificar(self, hilo: str, usuario: Usuario, paciente_id: int) -> None:
        if self._duenos.get(hilo) != (usuario.id, paciente_id):
            raise HTTPException(status_code=404, detail="Esa conversación no existe.")

    @contextlib.contextmanager
    def _solo_este_paciente(self, expediente_id: int):
        from tx_clinica.tools.patients_tools import PACIENTES_PERMITIDOS

        marca = PACIENTES_PERMITIDOS.set(frozenset({expediente_id}))
        try:
            yield
        finally:
            PACIENTES_PERMITIDOS.reset(marca)

    def enviar(self, usuario: Usuario, paciente_id: int, expediente_id: int, mensaje: str, hilo: Optional[str]) -> dict:
        from tx_clinica.conversacion import enviar_mensaje

        agente = self._construir()
        if hilo:
            self._verificar(hilo, usuario, paciente_id)
            texto = mensaje
        else:
            hilo = secrets.token_urlsafe(12)
            self._duenos[hilo] = (usuario.id, paciente_id)
            # Primer mensaje: el agente identifica al paciente por su id del expediente.
            texto = f"[Paciente activo: id {expediente_id}] {mensaje}"
        with self._solo_este_paciente(expediente_id), contextlib.redirect_stderr(io.StringIO()):
            respuesta = enviar_mensaje(agente, texto, hilo, usuario.id)
        return self._respuesta(hilo, respuesta)

    def decidir(self, usuario: Usuario, paciente_id: int, expediente_id: int, hilo: str, aprobar: bool, motivo: Optional[str]) -> dict:
        from tx_clinica.conversacion import reanudar_con_decisiones

        self._verificar(hilo, usuario, paciente_id)
        agente = self._construir()
        decision = {"type": "approve"} if aprobar else {"type": "reject", "message": motivo or "El médico rechazó la acción."}
        estado = agente.get_state({"configurable": {"thread_id": hilo}})
        pendientes = sum(len((getattr(i, "value", None) or {}).get("action_requests", [])) for i in (estado.interrupts or ()))
        with self._solo_este_paciente(expediente_id), contextlib.redirect_stderr(io.StringIO()):
            respuesta = reanudar_con_decisiones(agente, [decision] * max(1, pendientes), hilo, usuario.id)
        return self._respuesta(hilo, respuesta)
