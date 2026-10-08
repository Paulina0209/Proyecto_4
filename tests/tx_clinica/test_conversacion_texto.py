"""El texto final del agente es un str aunque el modelo responda en bloques
(formato de la API de Responses, como gpt-6-luna)."""

from langchain_core.messages import AIMessage, HumanMessage

from tx_clinica.conversacion import _armar_respuesta


def test_contenido_en_bloques_se_convierte_en_texto():
    bloques = [{"type": "text", "text": "EGFR L858R "}, {"type": "text", "text": "confirmada."}]
    respuesta = _armar_respuesta({"messages": [HumanMessage("¿EGFR?"), AIMessage(content=bloques)]}, None)

    assert respuesta.texto == "EGFR L858R confirmada."
    assert type(respuesta.texto) is str


def test_contenido_en_texto_plano_sigue_igual():
    respuesta = _armar_respuesta({"messages": [AIMessage(content="Sin biomarcadores accionables.")]}, None)

    assert respuesta.texto == "Sin biomarcadores accionables."


def test_sin_mensajes_no_hay_texto():
    assert _armar_respuesta({"messages": []}, None).texto is None
