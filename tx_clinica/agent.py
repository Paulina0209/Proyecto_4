from __future__ import annotations

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from core import llm_config
from tx_clinica.middleware.human_in_the_loop import construir_middleware_aprobacion_humana
from tx_clinica.observability import inicializar_langfuse
from tx_clinica.prompts.system_prompt import SYSTEM_PROMPT
from tx_clinica.tools import TOOLS


def construir_agente(model: str | None = None):
    """Agente de TX con un modelo GPT (llave y modelo en el .env, ver core.llm_config)."""
    inicializar_langfuse()

    api_key = llm_config.obtener_api_key()
    if not api_key:
        raise RuntimeError(
            "No hay llave de OpenAI configurada. Agrega OPENAI_API_KEY al "
            "archivo .env de la raíz del repositorio (ver .env.example)."
        )
    llm = ChatOpenAI(
        model=model or llm_config.obtener_modelo(),
        api_key=api_key,
        timeout=llm_config.obtener_timeout(),
        max_retries=2,
    )
    return create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        middleware=[construir_middleware_aprobacion_humana()],
        checkpointer=InMemorySaver(),
    )
