"""Pruebas de Fase 1 para tx_clinica/tools/decision_tools.py (C1, C3).

Se testea el objeto @tool directamente con .invoke(...), sin pasar por
create_agent ni por el LLM -- es la forma soportada por langchain-core
de invocar una tool "a mano" pasando config. Por separado (fuera de este
archivo) se validó que create_agent + HumanInTheLoopMiddleware +
reanudación preserva ese config hasta la tool tras una pausa de
aprobación humana; ver PLAN_REORGANIZACION_TX_CLINICA.md, snippet S3.

Las dependencias de módulos no enviados (obtener_paciente_o_error,
_diagnosticar_y_recomendar, resolver_chequeo_interacciones, _registrar)
se sustituyen por monkeypatch sobre el módulo ya importado -- prueba de
integración liviana centrada en el comportamiento nuevo (C1, C3), no una
reimplementación de esos módulos.
"""
import json
from dataclasses import dataclass
from types import SimpleNamespace

from tx_clinica.tools import decision_tools as dt


@dataclass
class FakePaciente:
    paciente_id: int


@dataclass
class FakeCandidato:
    regimen_id: str
    es_primera_opcion: bool


@dataclass
class FakeResultadoRecomendacion:
    module_id: str
    candidatos: list


def _parchar_dependencias(monkeypatch, *, candidatos, resolucion_error=None, chequeo="CHEQUEO_OK",
                           registrar_resultado=None):
    monkeypatch.setattr(dt, "obtener_paciente_o_error", lambda pid: FakePaciente(pid))
    monkeypatch.setattr(
        dt, "_diagnosticar_y_recomendar",
        lambda pid, facts: FakeResultadoRecomendacion(module_id="m", candidatos=candidatos),
    )
    monkeypatch.setattr(dt, "construir_facts_paciente", lambda conn, pid: {})
    monkeypatch.setattr(dt, "obtener_conexion", lambda: SimpleNamespace())
    monkeypatch.setattr(dt, "conn_lock", _NullLock())
    monkeypatch.setattr(dt, "serializar_candidato", lambda c: {"regimen_id": c.regimen_id})

    resolucion = SimpleNamespace(error=resolucion_error, chequeo=chequeo)
    monkeypatch.setattr(dt, "resolver_chequeo_interacciones", lambda pid, regimen: resolucion)

    llamadas = {}

    def _fake_registrar(conn, **kwargs):
        llamadas["kwargs"] = kwargs
        if registrar_resultado is not None:
            return registrar_resultado
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
    return llamadas


class _NullLock:
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_c3_esquema_visible_al_llm_no_tiene_oncologo_id():
    assert "oncologo_id" not in dt.registrar_decision_tratamiento.args
    assert "config" not in dt.registrar_decision_tratamiento.args


def test_c3_sin_oncologo_id_en_config_devuelve_error_explicito(monkeypatch):
    _parchar_dependencias(monkeypatch, candidatos=[FakeCandidato("reg_a", True)])
    r = dt.registrar_decision_tratamiento.invoke(
        {"patient_id": 10, "tipo_decision": "accept"},
        config={"configurable": {"thread_id": "t1"}},  # sin oncologo_id
    )
    payload = json.loads(r)
    assert "error" in payload
    assert "oncologo_id" in payload["error"] or "oncólogo autenticado" in payload["error"]


def test_c3_oncologo_id_llega_desde_config_no_del_llm(monkeypatch):
    llamadas = _parchar_dependencias(monkeypatch, candidatos=[FakeCandidato("reg_a", True)])
    r = dt.registrar_decision_tratamiento.invoke(
        {"patient_id": 10, "tipo_decision": "accept"},
        config={"configurable": {"thread_id": "t1", "oncologo_id": 77}},
    )
    payload = json.loads(r)
    assert payload["registrado"] is True
    assert llamadas["kwargs"]["oncologo_id"] == 77


def test_c1_accept_con_regimen_distinto_al_sugerido_se_rechaza(monkeypatch):
    llamadas = _parchar_dependencias(
        monkeypatch,
        candidatos=[FakeCandidato("reg_a", True), FakeCandidato("reg_b", False)],
    )
    r = dt.registrar_decision_tratamiento.invoke(
        {"patient_id": 10, "tipo_decision": "accept", "regimen_final_id": "reg_b"},
        config={"configurable": {"thread_id": "t1", "oncologo_id": 1}},
    )
    payload = json.loads(r)
    assert "error" in payload
    assert "modify" in payload["error"]
    assert "kwargs" not in llamadas, "no debía llegar a llamar _registrar"


def test_c1_accept_sin_regimen_final_id_sigue_funcionando(monkeypatch):
    """El caso normal (el LLM no manda regimen_final_id en accept) no debe
    verse afectado por la guarda C1."""
    llamadas = _parchar_dependencias(
        monkeypatch, candidatos=[FakeCandidato("reg_a", True), FakeCandidato("reg_b", False)],
    )
    r = dt.registrar_decision_tratamiento.invoke(
        {"patient_id": 10, "tipo_decision": "accept"},
        config={"configurable": {"thread_id": "t1", "oncologo_id": 1}},
    )
    payload = json.loads(r)
    assert payload["registrado"] is True
    assert llamadas["kwargs"]["regimen_final_id"] is None


def test_c1_modify_con_el_regimen_correcto_no_se_bloquea(monkeypatch):
    llamadas = _parchar_dependencias(
        monkeypatch, candidatos=[FakeCandidato("reg_a", True), FakeCandidato("reg_b", False)],
    )
    r = dt.registrar_decision_tratamiento.invoke(
        {"patient_id": 10, "tipo_decision": "modify", "regimen_final_id": "reg_b"},
        config={"configurable": {"thread_id": "t1", "oncologo_id": 1}},
    )
    payload = json.loads(r)
    assert payload["registrado"] is True
    assert llamadas["kwargs"]["regimen_final_id"] == "reg_b"


def test_c1_bug_real_de_la_traza_queda_bloqueado(monkeypatch):
    """Reproduce el caso EXACTO visto en la corrida real: el oncólogo
    eligió 'el regimen 2' (no el primero), el LLM llamó accept con
    regimen_final_id del régimen 2 -- con C1, esto ya no se confirma en
    silencio como el sugerido."""
    llamadas = _parchar_dependencias(
        monkeypatch,
        candidatos=[
            FakeCandidato("pembro_monotherapy", True),
            FakeCandidato("pembro_pemetrexed_platinum_induction", False),
        ],
    )
    r = dt.registrar_decision_tratamiento.invoke(
        {
            "patient_id": 10,
            "tipo_decision": "accept",
            "regimen_final_id": "pembro_pemetrexed_platinum_induction",
        },
        config={"configurable": {"thread_id": "t1", "oncologo_id": 1}},
    )
    payload = json.loads(r)
    assert "error" in payload
    assert "kwargs" not in llamadas