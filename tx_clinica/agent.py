"""Construcción del agente de tool-calling de tx_clinica.

Este archivo, a propósito, SOLO compone: modelo + tools + prompt +
middleware + create_agent. La lógica de cada tool vive en
tx_clinica/tools/ (separada por dominio), el texto del prompt vive en
tx_clinica/prompts/, y la configuración de aprobación humana vive en
tx_clinica/middleware/.

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
from tx_clinica.prompts.system_prompt import SYSTEM_PROMPT
from tx_clinica.tools import TOOLS


def construir_agente(model: str = "qwen2.5:14b-instruct-q4_K_M"):
    """Construye el agente de tool-calling sobre Ollama local.

    Devuelve un grafo compilado de LangGraph (lo que produce
    `create_agent` en langchain>=1.0), no un AgentExecutor.

    Uso normal (sin que se dispare ninguna aprobación humana):

        agente = construir_agente()
        config = {"configurable": {"thread_id": "consulta-paciente-4"}}
        resultado = agente.invoke(
            {"messages": [{"role": "user", "content": pregunta}]},
            config=config,
        )
        respuesta_texto = resultado["messages"][-1].content

    thread_id identifica la conversación -- es lo que le permite al
    checkpointer retomarla exactamente donde quedó si se pausa por
    aprobación humana. Debe ser estable durante toda la conversación con
    un mismo oncólogo/paciente, no generarse de nuevo en cada mensaje.

    Cuando el agente llama a registrar_decision_tratamiento (TX-04), la
    ejecución se PAUSA (ver tx_clinica/middleware/human_in_the_loop.py) y
    `resultado` no trae la respuesta final todavía -- hay que revisar
    `resultado["__interrupt__"]` para ver qué decisión está pendiente de
    aprobar/editar/rechazar, y reanudar con:

        from langgraph.types import Command
        resultado = agente.invoke(
            Command(resume={"decisions": [{"type": "approve"}]}),
            config=config,
        )

    (o {"type": "edit", "args": {...}} / {"type": "reject", ...} según lo
    que decida el oncólogo -- ver la doc de HumanInTheLoopMiddleware para
    la forma exacta del payload de resume, que puede variar de versión a
    versión; no se pudo probar contra un servidor Ollama real desde este
    entorno de desarrollo, así que conviene confirmar esto en el entorno
    real antes de confiar en el ejemplo tal cual).
    """
    llm = ChatOllama(model=model, temperature=0.1, num_ctx=8192)
    return create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        middleware=[construir_middleware_aprobacion_humana()],
        checkpointer=InMemorySaver(),
    )
