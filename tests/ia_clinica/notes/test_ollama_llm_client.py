"""Pruebas de OllamaLLMClient sin depender de un servidor Ollama real.

No se prueba contra una instancia real de Ollama (no hay garantía de que
esté corriendo en el entorno de pruebas): se simula la librería
``requests`` para verificar el contrato (qué se envía, qué se devuelve,
y que los errores de red se traducen en ``OllamaConnectionError`` en vez
de una excepción críptica de ``requests``).
"""

import json

import pytest
import requests

from ia_clinica.notes.llm_client import OllamaConnectionError, OllamaLLMClient


class _RespuestaFalsa:
    def __init__(self, payload, status_ok=True):
        self._payload = payload
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise requests.exceptions.HTTPError("500 Server Error")

    def json(self):
        return self._payload


def test_complete_envia_prompts_y_devuelve_el_contenido(monkeypatch):
    llamada = {}

    def post_falso(url, json, timeout):
        llamada["url"] = url
        llamada["json"] = json
        llamada["timeout"] = timeout
        return _RespuestaFalsa({"message": {"content": '{"sections": []}'}})

    monkeypatch.setattr(requests, "post", post_falso)

    cliente = OllamaLLMClient(model="qwen2.5:14b-instruct-q4_K_M", base_url="http://localhost:11434")
    resultado = cliente.complete(system_prompt="system X", user_prompt="user Y")

    assert resultado == '{"sections": []}'
    assert llamada["url"] == "http://localhost:11434/api/chat"
    assert llamada["json"]["model"] == "qwen2.5:14b-instruct-q4_K_M"
    assert llamada["json"]["messages"] == [
        {"role": "system", "content": "system X"},
        {"role": "user", "content": "user Y"},
    ]
    # Por defecto se pide decodificación restringida a gramática JSON
    # ("format": "json"): evita el error más común en la práctica (una
    # comilla sin escapar dentro de un campo de texto que rompe el JSON
    # a la mitad de la respuesta).
    assert llamada["json"]["format"] == "json"
    assert llamada["json"]["stream"] is False


def test_complete_permite_desactivar_el_formato_json(monkeypatch):
    llamada = {}

    def post_falso(url, json, timeout):
        llamada["json"] = json
        return _RespuestaFalsa({"message": {"content": '{"sections": []}'}})

    monkeypatch.setattr(requests, "post", post_falso)

    cliente = OllamaLLMClient(usar_formato_json=False)
    cliente.complete(system_prompt="system X", user_prompt="user Y")

    assert "format" not in llamada["json"]


def test_complete_traduce_errores_de_red_en_ollama_connection_error(monkeypatch):
    def post_que_falla(url, json, timeout):
        raise requests.exceptions.ConnectionError("no se pudo conectar")

    monkeypatch.setattr(requests, "post", post_que_falla)

    cliente = OllamaLLMClient()
    with pytest.raises(OllamaConnectionError):
        cliente.complete("system", "user")


def test_complete_lanza_error_claro_si_falta_la_llave_message(monkeypatch):
    def post_falso(url, json, timeout):
        return _RespuestaFalsa({"algo_inesperado": True})

    monkeypatch.setattr(requests, "post", post_falso)

    cliente = OllamaLLMClient()
    with pytest.raises(OllamaConnectionError):
        cliente.complete("system", "user")


def test_esta_disponible_true_cuando_el_servidor_responde(monkeypatch):
    def get_falso(url, timeout):
        return _RespuestaFalsa({"models": []})

    monkeypatch.setattr(requests, "get", get_falso)

    cliente = OllamaLLMClient()
    assert cliente.esta_disponible() is True


def test_esta_disponible_false_cuando_no_hay_servidor(monkeypatch):
    def get_que_falla(url, timeout):
        raise requests.exceptions.ConnectionError("nadie escuchando en ese puerto")

    monkeypatch.setattr(requests, "get", get_que_falla)

    cliente = OllamaLLMClient()
    assert cliente.esta_disponible() is False


def test_esta_disponible_no_llama_al_endpoint_de_chat(monkeypatch):
    """AC implícito de diseño: el chequeo de salud no debe pagar el costo
    de una inferencia completa del modelo."""

    def post_que_no_deberia_llamarse(*args, **kwargs):
        raise AssertionError("esta_disponible() no debe llamar a /api/chat")

    monkeypatch.setattr(requests, "post", post_que_no_deberia_llamarse)
    monkeypatch.setattr(requests, "get", lambda url, timeout: _RespuestaFalsa({"models": []}))

    cliente = OllamaLLMClient()
    assert cliente.esta_disponible() is True
