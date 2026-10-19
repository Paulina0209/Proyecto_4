"""Configuración del asistente (todo por variables de entorno, ver .env.example).

    COPILOTO_LLM_PROVEEDOR      openai (por defecto) | ollama
    OPENAI_MODEL                modelo de OpenAI que redacta (core.llm_config, por defecto gpt-6-luna)
    OLLAMA_URL / OLLAMA_MODEL   servidor y modelo local (por defecto http://localhost:11434, llama3.1:8b)
    OPENAI_EMBEDDING_MODEL      modelo de embeddings (por defecto text-embedding-3-small)
    COPILOTO_VECTORIAL_DIR      carpeta de ChromaDB (por defecto data/vectorial)
    COPILOTO_UMBRAL_SIMILITUD   similitud coseno mínima para aceptar un fragmento (por defecto 0.30)
    COPILOTO_CONVERSACIONES_DB  historial de conversaciones (por defecto data/conversaciones.db)
    COPILOTO_LLM_TIMEOUT        segundos que se le dan al modelo (por defecto 8, NFR-01)
"""

from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _cargar_env() -> None:
    from core import llm_config

    llm_config.cargar_env()


def proveedor_llm() -> str:
    _cargar_env()
    valor = (os.environ.get("COPILOTO_LLM_PROVEEDOR") or "openai").strip().lower()
    return valor if valor in ("openai", "ollama") else "openai"


def ollama_url() -> str:
    _cargar_env()
    return (os.environ.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/")


def ollama_modelo() -> str:
    _cargar_env()
    return os.environ.get("OLLAMA_MODEL") or "llama3.1:8b"


def modelo_embeddings() -> str:
    _cargar_env()
    return os.environ.get("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small"


def carpeta_vectorial() -> Path:
    _cargar_env()
    return Path(os.environ.get("COPILOTO_VECTORIAL_DIR") or RAIZ / "data" / "vectorial")


def umbral_similitud() -> float:
    _cargar_env()
    try:
        return float(os.environ.get("COPILOTO_UMBRAL_SIMILITUD") or 0.30)
    except ValueError:
        return 0.30


def ruta_conversaciones() -> Path:
    _cargar_env()
    return Path(os.environ.get("COPILOTO_CONVERSACIONES_DB") or RAIZ / "data" / "conversaciones.db")


def timeout_llm() -> float:
    _cargar_env()
    try:
        return float(os.environ.get("COPILOTO_LLM_TIMEOUT") or 8.0)
    except ValueError:
        return 8.0
