"""Dobles de prueba para LLMClient, usados por las pruebas de IA-02.

No es un archivo ``test_*.py`` a propósito: pytest no debe intentar
recolectarlo como módulo de pruebas, solo como utilidad importada por
ellas.
"""

import json
from typing import Optional

from ia_clinica.notes.llm_client import LLMClient


class ScriptedLLMClient(LLMClient):
    """Cliente falso para pruebas: devuelve exactamente el payload que se le indique.

    Permite simular cualquier comportamiento del modelo (bien formado,
    incompleto, con referencias inventadas, JSON corrupto, etc.) sin
    depender de un proveedor real ni de heurísticas léxicas.
    """

    def __init__(self, response_payload=None, raw_response: Optional[str] = None):
        self.response_payload = response_payload
        self.raw_response = raw_response
        self.last_system_prompt: Optional[str] = None
        self.last_user_prompt: Optional[str] = None

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt
        if self.raw_response is not None:
            return self.raw_response
        return json.dumps(self.response_payload, ensure_ascii=False)


def section(key, status="documented", content="", source_span_ids=None):
    return {
        "key": key,
        "status": status,
        "content": content,
        "source_span_ids": source_span_ids or [],
    }
