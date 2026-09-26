"""Integración: verifica que oncologo_id viaja desde enviar_mensaje/
reanudar_con_decisiones (conversacion.py) hasta registrar_decision_tratamiento
(decision_tools.py) a traves de config["configurable"], incluso despues de
una pausa de aprobacion humana -- exactamente el flujo real del proyecto,
solo con un modelo de chat falso en vez de Ollama."""
import json
from types import SimpleNamespace
from typing import List

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from tx_clinica.conversacion import enviar_mensaje, reanudar_con_decisiones
from tx_clinica.tools import decision_tools as dt


class FakeToolCallingModel(BaseChatModel):
    responses: List[AIMessage] = []
    i: int = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        msg = self.responses[self.i]
        self.i += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling"


def test_oncologo_id_sobrevive_pausa_y_llega_a_la_tool(monkeypatch):
    from dataclasses import dataclass

    @dataclass
    class FakeCandidato:
        regimen_id: str
        es_primera_opcion: bool

    @dataclass
    class FakePaciente:
        paciente_id: int

    llamadas = {}
    monkeypatch.setattr(dt, "obtener_paciente_o_error", lambda pid: FakePaciente(pid))
    monkeypatch.setattr(dt, "construir_facts_paciente", lambda conn, pid: {})
    monkeypatch.setattr(dt, "obtener_conexion", lambda: SimpleNamespace())
    monkeypatch.setattr(
        dt, "_diagnosticar_y_recomendar",
        lambda pid, facts: SimpleNamespace(
            module_id="m", candidatos=[FakeCandidato("reg_a", True)]
        ),
    )
    monkeypatch.setattr(dt, "serializar_candidato", lambda c: {"regimen_id": c.regimen_id})
    monkeypatch.setattr(
        dt, "resolver_chequeo_interacciones",
        lambda pid, regimen: SimpleNamespace(error=None, chequeo="CHEQUEO_OK"),
    )

    def _fake_registrar(conn, **kwargs):
        llamadas["oncologo_id"] = kwargs["oncologo_id"]
        return SimpleNamespace(
            exito=True,
            decision=SimpleNamespace(
                id=1, tipo_decision=kwargs["tipo_decision"],
                regimen_sugerido_id=kwargs["regimen_sugerido_id"],
                regimen_final_id=kwargs["regimen_final_id"],
                motivo_rechazo=None, justificaciones_ids=[],
            ),
        )

    monkeypatch.setattr(dt, "_registrar", _fake_registrar)

    fake_llm = FakeToolCallingModel(responses=[
        AIMessage(content="", tool_calls=[{
            "name": "registrar_decision_tratamiento",
            "args": {"patient_id": 10, "tipo_decision": "accept"},
            "id": "call_1",
        }]),
        AIMessage(content="Decision registrada."),
    ])

    agente = create_agent(
        model=fake_llm,
        tools=[dt.registrar_decision_tratamiento],
        system_prompt="test",
        middleware=[HumanInTheLoopMiddleware(interrupt_on={"registrar_decision_tratamiento": True})],
        checkpointer=InMemorySaver(),
    )

    thread_id = "hilo-integracion-1"
    r1 = enviar_mensaje(agente, "acepto el regimen", thread_id, oncologo_id=77)
    assert r1.esta_pausada

    r2 = reanudar_con_decisiones(agente, [{"type": "approve"}], thread_id, oncologo_id=77)
    assert not r2.esta_pausada
    assert llamadas["oncologo_id"] == 77, (
        "oncologo_id debia llegar a la tool via config, sobreviviendo la pausa HITL"
    )
