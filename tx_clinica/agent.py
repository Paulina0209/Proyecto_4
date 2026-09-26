from __future__ import annotations

from langchain.agents import create_agent
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import InMemorySaver

from tx_clinica.middleware.human_in_the_loop import construir_middleware_aprobacion_humana
from tx_clinica.observability import inicializar_langfuse
from tx_clinica.prompts.system_prompt import SYSTEM_PROMPT
from tx_clinica.tools import TOOLS


def construir_agente(model: str = "qwen2.5:14b-instruct-q4_K_M"):
    inicializar_langfuse()

    llm = ChatOllama(model=model, temperature=0.1, num_ctx=8192)
    return create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        middleware=[construir_middleware_aprobacion_humana()],
        checkpointer=InMemorySaver(),
    )
