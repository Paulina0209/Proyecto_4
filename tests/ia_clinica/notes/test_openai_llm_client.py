"""Pruebas de OpenAILLMClient sin llamar a la API real de OpenAI.

Se inyecta un cliente falso con la misma forma que ``openai.OpenAI``
(``chat.completions.create`` y ``models.retrieve``) para verificar el
contrato: qué se envía, qué se devuelve, y que los errores de la API se
traducen en ``OpenAIConnectionError`` en vez de una excepción críptica.
"""

from types import SimpleNamespace

import pytest

from core import llm_config
from ia_clinica.notes.llm_client import OpenAIConnectionError, OpenAILLMClient


class _ClienteFalso:
    def __init__(self, contenido='{"sections": []}', error=None, modelo_existe=True):
        self.llamadas = []
        self._contenido = contenido
        self._error = error
        self._modelo_existe = modelo_existe
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.models = SimpleNamespace(retrieve=self._retrieve)
        self.retrieve_llamado = False

    def _create(self, **kwargs):
        self.llamadas.append(kwargs)
        if self._error is not None:
            raise self._error
        mensaje = SimpleNamespace(content=self._contenido)
        return SimpleNamespace(choices=[SimpleNamespace(message=mensaje)])

    def _retrieve(self, modelo):
        self.retrieve_llamado = True
        if not self._modelo_existe:
            raise RuntimeError("model_not_found")
        return SimpleNamespace(id=modelo)


def test_complete_envia_prompts_y_devuelve_el_contenido():
    falso = _ClienteFalso()
    cliente = OpenAILLMClient(model="gpt-prueba", client=falso)

    resultado = cliente.complete(system_prompt="system X", user_prompt="user Y")

    assert resultado == '{"sections": []}'
    (llamada,) = falso.llamadas
    assert llamada["model"] == "gpt-prueba"
    assert llamada["messages"] == [
        {"role": "system", "content": "system X"},
        {"role": "user", "content": "user Y"},
    ]
    # Por defecto se pide JSON garantizado por la API.
    assert llamada["response_format"] == {"type": "json_object"}


def test_complete_permite_desactivar_el_formato_json():
    falso = _ClienteFalso()
    OpenAILLMClient(client=falso, usar_formato_json=False).complete("system", "user")

    assert "response_format" not in falso.llamadas[0]


def test_complete_traduce_errores_de_la_api():
    falso = _ClienteFalso(error=RuntimeError("401 invalid_api_key"))
    with pytest.raises(OpenAIConnectionError):
        OpenAILLMClient(client=falso).complete("system", "user")


def test_complete_lanza_error_claro_si_la_respuesta_no_trae_texto():
    falso = _ClienteFalso(contenido=None)
    with pytest.raises(OpenAIConnectionError):
        OpenAILLMClient(client=falso).complete("system", "user")


def test_sin_llave_lanza_error_claro_sin_llamar_a_la_red(monkeypatch):
    monkeypatch.setattr(llm_config, "obtener_api_key", lambda: None)
    cliente = OpenAILLMClient(model="gpt-prueba")

    with pytest.raises(OpenAIConnectionError, match="OPENAI_API_KEY"):
        cliente.complete("system", "user")
    assert cliente.esta_disponible() is False


def test_modelo_por_defecto_sale_de_la_configuracion(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-desde-env")
    assert OpenAILLMClient(client=_ClienteFalso()).model == "gpt-desde-env"


def test_esta_disponible_segun_el_modelo_y_sin_generar_texto():
    falso = _ClienteFalso()
    assert OpenAILLMClient(client=falso).esta_disponible() is True
    assert falso.retrieve_llamado is True
    assert falso.llamadas == []  # no pagó una inferencia

    assert OpenAILLMClient(client=_ClienteFalso(modelo_existe=False)).esta_disponible() is False


def test_api_key_acepta_el_nombre_antiguo(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("API_KEY", "sk-antigua")
    assert llm_config.obtener_api_key() == "sk-antigua"
