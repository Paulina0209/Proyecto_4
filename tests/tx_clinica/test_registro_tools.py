"""El agente puede guardar datos clínicos y la conciliación de medicamentos,
pero solo con la aprobación del oncólogo (pausa del grafo) y con validación
estricta. Modelo de chat falso: no se llama a OpenAI."""

from typing import List

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from expediente.repository import facts_estructurados_de_paciente
from historia_clinica.db import crear_conexion
from patients.medicacion_actual import inicializar_schema as inicializar_medicacion
from patients.medicacion_actual import listar_medicacion_activa, obtener_estado_conciliacion
from tx_clinica.conversacion import enviar_mensaje, reanudar_con_decisiones
from tx_clinica.middleware.human_in_the_loop import construir_middleware_aprobacion_humana
from tx_clinica.tools import patients_tools, registro_tools
from tx_clinica.tools.registro_tools import (
    registrar_conciliacion_medicamentos,
    registrar_datos_clinicos_paciente,
    validar_datos,
)

ONCOLOGO = {"configurable": {"oncologo_id": 7}}


class ModeloFalso(BaseChatModel):
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
        return "falso"


@pytest.fixture
def conn(monkeypatch):
    conexion = crear_conexion(":memory:", check_same_thread=False)
    inicializar_medicacion(conexion)
    conexion.execute(
        "INSERT INTO pacientes (id, nombre, fecha_nacimiento, sexo, identificacion) "
        "VALUES (1, 'Paciente Prueba', '1960-01-01', 'otro', 'X-1')"
    )
    conexion.commit()
    for modulo in (registro_tools, patients_tools):
        monkeypatch.setattr(modulo, "obtener_conexion", lambda: conexion)
    yield conexion
    conexion.close()


def _agente(llamada):
    modelo = ModeloFalso(responses=[AIMessage(content="", tool_calls=[{**llamada, "id": "c1"}]),
                                    AIMessage(content="Listo.")])
    return create_agent(
        model=modelo,
        tools=[registrar_datos_clinicos_paciente, registrar_conciliacion_medicamentos],
        system_prompt="prueba",
        middleware=[construir_middleware_aprobacion_humana()],
        checkpointer=InMemorySaver(),
    )


DATOS = {"patient_id": 1, "datos": {"disease_setting": "metastatic", "treatment_line": 1}}


# --- Aprobación humana: nada se guarda sin ella -----------------------------


def test_se_pausa_y_no_guarda_hasta_que_el_oncologo_aprueba(conn):
    agente = _agente({"name": "registrar_datos_clinicos_paciente", "args": DATOS})

    pausada = enviar_mensaje(agente, "guarda los datos", "h1", oncologo_id=7)

    assert pausada.esta_pausada
    assert facts_estructurados_de_paciente(conn, 1) == {}

    final = reanudar_con_decisiones(agente, [{"type": "approve"}], "h1", oncologo_id=7)

    assert not final.esta_pausada
    assert facts_estructurados_de_paciente(conn, 1) == {"disease_setting": "metastatic", "treatment_line": "1"}


def test_si_el_oncologo_rechaza_no_se_guarda_nada(conn):
    agente = _agente({"name": "registrar_datos_clinicos_paciente", "args": DATOS})
    enviar_mensaje(agente, "guarda los datos", "h2", oncologo_id=7)

    reanudar_con_decisiones(agente, [{"type": "reject", "message": "No, ese dato está mal."}], "h2", oncologo_id=7)

    assert facts_estructurados_de_paciente(conn, 1) == {}


def test_el_oncologo_puede_corregir_antes_de_guardar(conn):
    agente = _agente({"name": "registrar_datos_clinicos_paciente", "args": DATOS})
    enviar_mensaje(agente, "guarda los datos", "h3", oncologo_id=7)

    corregido = {"name": "registrar_datos_clinicos_paciente",
                 "args": {"patient_id": 1, "datos": {"disease_setting": "metastatic", "treatment_line": 2}}}
    reanudar_con_decisiones(agente, [{"type": "edit", "edited_action": corregido}], "h3", oncologo_id=7)

    assert facts_estructurados_de_paciente(conn, 1)["treatment_line"] == "2"


def test_la_conciliacion_tambien_pide_aprobacion(conn):
    agente = _agente({"name": "registrar_conciliacion_medicamentos",
                      "args": {"patient_id": 1, "sin_medicacion_concomitante": True}})

    assert enviar_mensaje(agente, "no toma nada", "h4", oncologo_id=7).esta_pausada
    assert obtener_estado_conciliacion(conn, 1) == "no_realizada"

    reanudar_con_decisiones(agente, [{"type": "approve"}], "h4", oncologo_id=7)

    assert obtener_estado_conciliacion(conn, 1) == "sin_medicacion_concomitante"


# --- Validación estricta (después de aprobar, antes de escribir) ------------


def test_valores_validos_se_normalizan():
    datos, errores = validar_datos({"disease_setting": "Metastatic", "treatment_line": "1", "smoking_status": "never_smoker"})
    assert errores == []
    assert datos == {"disease_setting": "metastatic", "treatment_line": 1, "smoking_status": "never_smoker"}


@pytest.mark.parametrize(
    ("datos", "fragmento"),
    [
        ({"variable_inventada": "x"}, "no es una variable"),
        ({"smoking_status": "nunca"}, "no es un valor permitido"),
        ({"treatment_line": "primera"}, "numérico"),
        ({"treatment_line": 1.5}, "entero"),
        ({"treatment_line": 0}, ">= 1"),
        ({"egfr_status": "sensitizing_mutation"}, "biomarcador"),
        ({"pdl1_tps": 60}, "biomarcador"),
        ({"actionable_driver_names": ["EGFR"]}, "no se registra por chat"),
        ({}, "ningún dato"),
    ],
)
def test_datos_invalidos(datos, fragmento):
    _, errores = validar_datos(datos)
    assert any(fragmento in e for e in errores), errores


def test_con_un_dato_invalido_no_se_guarda_ninguno(conn):
    respuesta = registrar_datos_clinicos_paciente.invoke(
        {"patient_id": 1, "datos": {"disease_setting": "metastatic", "smoking_status": "nunca"}}, config=ONCOLOGO
    )

    assert '"registrado": false' in respuesta
    assert facts_estructurados_de_paciente(conn, 1) == {}


def test_sin_oncologo_en_la_sesion_no_guarda(conn):
    respuesta = registrar_datos_clinicos_paciente.invoke({"patient_id": 1, "datos": {"treatment_line": 1}})

    assert "oncologo_id" in respuesta
    assert facts_estructurados_de_paciente(conn, 1) == {}


def test_paciente_inexistente(conn):
    assert "paciente_no_registrado" in registrar_datos_clinicos_paciente.invoke(
        {"patient_id": 999, "datos": {"treatment_line": 1}}, config=ONCOLOGO
    )


@pytest.mark.parametrize(
    "args",
    [
        {"patient_id": 1},  # lista vacía no es "sin medicación"
        {"patient_id": 1, "medicamentos": ["Losartán"], "sin_medicacion_concomitante": True},
    ],
)
def test_conciliacion_ambigua_no_se_guarda(conn, args):
    assert '"registrado": false' in registrar_conciliacion_medicamentos.invoke(args, config=ONCOLOGO)
    assert obtener_estado_conciliacion(conn, 1) == "no_realizada"


def test_conciliacion_con_medicamentos(conn):
    registrar_conciliacion_medicamentos.invoke({"patient_id": 1, "medicamentos": ["Losartán 50 mg", " "]}, config=ONCOLOGO)

    assert listar_medicacion_activa(conn, 1) == ["Losartán 50 mg"]
    assert obtener_estado_conciliacion(conn, 1) == "con_medicacion_registrada"
