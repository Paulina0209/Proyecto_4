"""Configuración compartida del modelo de lenguaje (OpenAI / GPT).

Todos los componentes que usan un LLM real (``ia_clinica`` para IA-02/03/04
y el agente de ``tx_clinica``) leen la llave y el modelo de aquí, para que
cambiar de modelo sea tocar una variable de entorno y no varios archivos.

Variables (en el ``.env`` de la raíz, que NO se sube a GitHub; ver
``.env.example``):

    OPENAI_API_KEY   llave de la API de OpenAI. Por compatibilidad también
                     se acepta ``API_KEY`` si ``OPENAI_API_KEY`` no existe.
    OPENAI_MODEL     modelo a usar (por defecto ``MODELO_POR_DEFECTO``).
    OPENAI_TIMEOUT   segundos de espera por respuesta (por defecto 120).
"""

from __future__ import annotations

import os
from pathlib import Path

MODELO_POR_DEFECTO = "gpt-5.4-mini"
TIMEOUT_POR_DEFECTO = 120.0

_RAIZ_REPO = Path(__file__).resolve().parent.parent
_env_cargado = False


def cargar_env(ruta: Path | None = None) -> None:
    """Carga el ``.env`` de la raíz en ``os.environ`` (una sola vez).

    Nunca sobrescribe variables que ya existan en el entorno. Usa
    ``python-dotenv`` si está instalado; si no, un lector mínimo de
    líneas ``CLAVE=valor``.
    """
    global _env_cargado
    if _env_cargado and ruta is None:
        return
    ruta = ruta or _RAIZ_REPO / ".env"
    _env_cargado = True
    if not ruta.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            os.environ.setdefault(clave.strip(), valor.strip().strip("'\""))
    else:
        load_dotenv(ruta, override=False)


def obtener_api_key() -> str | None:
    cargar_env()
    return os.environ.get("OPENAI_API_KEY") or os.environ.get("API_KEY") or None


def obtener_modelo() -> str:
    cargar_env()
    return os.environ.get("OPENAI_MODEL") or MODELO_POR_DEFECTO


def obtener_timeout() -> float:
    cargar_env()
    valor = os.environ.get("OPENAI_TIMEOUT")
    return float(valor) if valor else TIMEOUT_POR_DEFECTO
