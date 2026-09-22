"""Construcción del agente de tool-calling de tx_clinica.

Este archivo, a propósito, SOLO compone: modelo + tools + prompt +
middleware + create_agent. La lógica de cada tool vive en
tx_clinica/tools/ (separada por dominio), el texto del prompt vive en
tx_clinica/prompts/, la configuración de aprobación humana vive en
tx_clinica/middleware/, y todo lo de Langfuse vive en
tx_clinica/observability.py.

Desde que se agregó TX-04 (decisión final del oncólogo),
create_agent() necesita `checkpointer` -- HumanInTheLoopMiddleware
pausa/reanuda la ejecución usando la capa de persistencia de LangGraph,
y sin checkpointer no tiene dónde guardar ese estado. InMemorySaver
alcanza para este prototipo (se pierde al reiniciar el proceso); si esto
pasa a producción real, cambiar por un checkpointer persistente
(ej. el de langgraph-checkpoint-sqlite/-postgres).
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import InMemorySaver

from tx_clinica.middleware.human_in_the_loop import construir_middleware_aprobacion_humana
from tx_clinica.observability import inicializar_langfuse
from tx_clinica.prompts.system_prompt import SYSTEM_PROMPT
from tx_clinica.tools import TOOLS


def construir_agente(model: str = "qwen2.5:14b-instruct-q4_K_M"):
    """Construye el agente de tool-calling sobre Ollama local.

    Devuelve un grafo compilado de LangGraph (lo que produce
    `create_agent` en langchain>=1.0), no un AgentExecutor.

    NO invocar este grafo directamente con agente.invoke(...) a mano:
    usar tx_clinica.conversacion.enviar_mensaje() y
    reanudar_con_decisiones(), que ya se encargan de:

      - pasar `config` con el thread_id (lo que le permite al
        checkpointer retomar la conversación exactamente donde quedó si
        se pausa por aprobación humana) y el callback de Langfuse.
        thread_id debe ser estable durante toda la conversación con un
        mismo oncólogo/paciente, no generarse de nuevo en cada mensaje.
      - detectar la pausa de TX-04 (`resultado["__interrupt__"]`) y
        reanudar con la decisión del oncólogo.

    Ejemplo:

        from tx_clinica.agent import construir_agente
        from tx_clinica.conversacion import enviar_mensaje, reanudar_con_decisiones
        from tx_clinica.observability import vaciar_langfuse

        agente = construir_agente()
        r = enviar_mensaje(agente, pregunta, thread_id="consulta-paciente-4", oncologo_id=1)
        if r.esta_pausada:  # el agente llamó a registrar_decision_tratamiento
            r = reanudar_con_decisiones(
                agente, [{"type": "approve"}], thread_id="consulta-paciente-4", oncologo_id=1
            )
        print(r.texto)
        vaciar_langfuse()  # solo necesario en scripts cortos

    Para probarlo a mano sin escribir código: python -m tx_clinica.chat_cli

    La forma exacta del payload de resume de HumanInTheLoopMiddleware
    ({"type": "approve"} / {"type": "reject", "message": ...} / edit)
    puede variar de versión a versión de langchain; no se pudo probar
    contra un servidor Ollama real desde este entorno de desarrollo, así
    que conviene confirmar esto en el entorno real antes de confiar en
    los ejemplos tal cual.
    """
    inicializar_langfuse()

    llm = ChatOllama(model=model, temperature=0.1, num_ctx=8192)
    return create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        middleware=[construir_middleware_aprobacion_humana()],
        checkpointer=InMemorySaver(),
    )