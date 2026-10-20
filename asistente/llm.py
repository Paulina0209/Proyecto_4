"""El modelo que redacta las respuestas: GPT (por defecto) u Ollama (local), por ``COPILOTO_LLM_PROVEEDOR``.

Se usa a través de LangChain (``ChatOpenAI`` / ``ChatOllama`` si está instalado; si no,
la API HTTP de Ollama). Tiene el presupuesto de NFR-01: si no responde a tiempo o
falla, el grafo responde con los fragmentos encontrados, sin redactar.
"""

from __future__ import annotations

from typing import Optional

from asistente import config


class ModeloNoDisponible(RuntimeError):
    pass


def descripcion() -> str:
    from core import llm_config

    if config.proveedor_llm() == "ollama":
        return f"Ollama ({config.ollama_modelo()}, local)"
    return f"GPT ({llm_config.obtener_modelo()})" if llm_config.obtener_api_key() else "sin modelo (respuesta extractiva)"


def disponible() -> bool:
    from core import llm_config

    return config.proveedor_llm() == "ollama" or bool(llm_config.obtener_api_key())


def redactar(sistema: str, usuario: str, timeout: Optional[float] = None) -> str:
    timeout = timeout or config.timeout_llm()
    if config.proveedor_llm() == "ollama":
        return _ollama(sistema, usuario, timeout)
    return _openai(sistema, usuario, timeout)


def _openai(sistema: str, usuario: str, timeout: float) -> str:
    from langchain_openai import ChatOpenAI

    from core import llm_config

    llave = llm_config.obtener_api_key()
    if not llave:
        raise ModeloNoDisponible("Sin OPENAI_API_KEY.")
    modelo = ChatOpenAI(model=llm_config.obtener_modelo(), api_key=llave, timeout=timeout, max_retries=0)
    try:
        respuesta = modelo.invoke([("system", sistema), ("human", usuario)])
    except Exception as exc:  # noqa: BLE001 - red, cuota, tiempo agotado
        raise ModeloNoDisponible(f"El modelo no respondió ({type(exc).__name__}).") from exc
    texto = getattr(respuesta, "text", None)
    return str(texto if isinstance(texto, str) else respuesta.content or "").strip()


def _ollama(sistema: str, usuario: str, timeout: float) -> str:
    try:
        from langchain_ollama import ChatOllama  # type: ignore

        modelo = ChatOllama(model=config.ollama_modelo(), base_url=config.ollama_url(), timeout=timeout, temperature=0)
        try:
            return str(modelo.invoke([("system", sistema), ("human", usuario)]).content).strip()
        except Exception as exc:  # noqa: BLE001
            raise ModeloNoDisponible(f"Ollama no respondió ({type(exc).__name__}).") from exc
    except ImportError:
        import requests

        try:
            r = requests.post(f"{config.ollama_url()}/api/chat", timeout=timeout, json={
                "model": config.ollama_modelo(), "stream": False, "options": {"temperature": 0},
                "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]})
            r.raise_for_status()
            return str(r.json()["message"]["content"]).strip()
        except Exception as exc:  # noqa: BLE001
            raise ModeloNoDisponible(f"Ollama no respondió ({type(exc).__name__}).") from exc
