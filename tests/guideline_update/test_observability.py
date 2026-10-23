"""Las llamadas a Claude de guidelineUpdate quedan en Langfuse como
generaciones, sin las imágenes en base64 y sin romper el agente si
Langfuse falla."""

from contextlib import contextmanager
from types import SimpleNamespace as NS

from guidelineUpdate import observability


class _ClienteFalso:
    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        return NS(content=[NS(type="text", text="[]")], stop_reason="end_turn",
                  usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=8, cache_creation_input_tokens=0))


def test_la_generacion_registra_tokens_y_no_las_imagenes(monkeypatch):
    registros = {}

    class _Generacion:
        def update(self, **kwargs):
            registros["update"] = kwargs

    @contextmanager
    def _abrir(**kwargs):
        registros["abrir"] = kwargs
        yield _Generacion()

    monkeypatch.setattr(observability, "get_client", lambda: NS(start_as_current_observation=_abrir))
    imagen = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo" * 100}}

    respuesta = observability.llamar_claude(
        _ClienteFalso(), "detectar", model="claude-sonnet-5", max_tokens=100,
        messages=[{"role": "user", "content": [{"type": "text", "text": "hola"}, imagen]}])

    assert respuesta.stop_reason == "end_turn"
    assert "iVBORw0KGgo" not in str(registros["abrir"]["input"])
    assert registros["abrir"]["as_type"] == "generation"
    assert registros["update"]["usage_details"] == {
        "input": 10, "output": 5, "cache_read_input_tokens": 8, "cache_creation_input_tokens": 0}


def test_si_langfuse_falla_la_llamada_a_claude_sigue(monkeypatch):
    def _roto():
        raise RuntimeError("langfuse caído")

    monkeypatch.setattr(observability, "get_client", _roto)

    respuesta = observability.llamar_claude(_ClienteFalso(), "detectar", model="claude-sonnet-5", messages=[])

    assert respuesta.content[0].text == "[]"
