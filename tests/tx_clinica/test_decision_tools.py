"""Tests de tx_clinica/tools/decision_tools.py (TX-04).

Monkeypatchea la resolución de recomendación (_diagnosticar_y_recomendar)
y de interacciones (resolver_chequeo_interacciones) para no depender de
base de datos real -- se prueba la ORQUESTACIÓN de la tool (accept
auto-completa el régimen, modify valida contra los candidatos, reject
nunca bloquea), no la lógica de negocio de más abajo (esa ya la prueban
test_recommendation_tools.py, test_interaction_tools.py y
decision_clinica/tests/test_registro.py).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

import pytest

from clinical_decision.registro import inicializar_schema as inicializar_decision
from interacciones_farmacologicas.models import InteraccionDetectada, ResultadoChequeoInteracciones
from tx_clinica.justificaciones import inicializar_schema as inicializar_auditoria
from tx_clinica.models import RegimenCandidato, ResultadoRecomendacionTratamiento
from tx_clinica.tools import decision_tools as dt
from tx_clinica.tools.patients_tools import ErrorPacienteNoEncontrado, PacienteResuelto


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    inicializar_auditoria(conn)
    inicializar_decision(conn)
    yield conn
    conn.close()


class _Resolucion:
    """Doble mínimo de ResolucionInteracciones -- evita importar
    tx_clinica.tools._interaction_shared solo por el tipo."""

    def __init__(self, chequeo=None, error=None):
        self.chequeo = chequeo
        self.error = error


def _candidato(regimen_id: str, es_primera: bool) -> RegimenCandidato:
    return RegimenCandidato(
        regimen_id=regimen_id,
        fase="first_line",
        farmacos=("pembrolizumab", "paclitaxel"),
        rule_id_disparada="R-001",
        archivo_regla="rules/first_line.yaml",
        audit_effect="supports_prescription" if es_primera else "requires_clinical_review",
        field_ids_usados=("treatment_line",),
        evidencia=None,
        advertencia_comorbilidad=None if es_primera else "advertencia de prueba",
    )


def _resultado_recomendacion(candidatos) -> ResultadoRecomendacionTratamiento:
    return ResultadoRecomendacionTratamiento(
        patient_id=1, module_id="breast_metastatic_tnbc",
        generado_en=datetime.now(), candidatos=tuple(candidatos),
    )


def _chequeo_sin_interacciones(regimen_id: str) -> ResultadoChequeoInteracciones:
    return ResultadoChequeoInteracciones(
        paciente_id=1, modulo_guia="breast_metastatic_tnbc", regimen_evaluado=regimen_id,
        sin_interacciones_conocidas=True,
    )


def _chequeo_con_interaccion_mayor(regimen_id: str) -> ResultadoChequeoInteracciones:
    return ResultadoChequeoInteracciones(
        paciente_id=1, modulo_guia="breast_metastatic_tnbc", regimen_evaluado=regimen_id,
        interacciones=[
            InteraccionDetectada("int_001", "R1", "major", "requires_justification", "d", "r", {}, "x")
        ],
    )


def _monkeypatchear_paciente_encontrado(monkeypatch):
    monkeypatch.setattr(dt, "obtener_paciente_o_error", lambda pid: PacienteResuelto(paciente_id=pid, paciente=object()))
    monkeypatch.setattr(dt, "obtener_conexion", lambda: None)
    monkeypatch.setattr(dt, "construir_facts_paciente", lambda conn, pid: {})


class TestTipoDecisionInvalido:
    def test_tipo_decision_desconocido_da_error(self, monkeypatch):
        _monkeypatchear_paciente_encontrado(monkeypatch)
        resultado = json.loads(
            dt.registrar_decision_tratamiento.invoke(
                {"patient_id": 1, "oncologo_id": 9, "tipo_decision": "aprobar_a_medias"}
            )
        )
        assert "error" in resultado


class TestReject:
    def test_reject_no_necesita_recomendacion_resuelta(self, monkeypatch, conn):
        """Reject puede registrarse incluso si la Fase 1 nunca se
        resolvió (ej. sin_guia_aplicable) -- rechazar algo que ni
        siquiera llegó a calcularse sigue siendo una decisión clínica
        legítima (AC2: nunca bloquea)."""
        _monkeypatchear_paciente_encontrado(monkeypatch)
        monkeypatch.setattr(
            dt, "_diagnosticar_y_recomendar",
            lambda pid, facts: {"requiere_mas_datos": False, "sin_guia_aplicable": True, "mensaje": "..."},
        )
        monkeypatch.setattr(dt, "obtener_conexion", lambda: conn)

        resultado = json.loads(
            dt.registrar_decision_tratamiento.invoke(
                {
                    "patient_id": 1, "oncologo_id": 9, "tipo_decision": "reject",
                    "motivo_rechazo": "El paciente prefiere manejo paliativo.",
                }
            )
        )
        assert resultado["registrado"] is True
        assert resultado["tipo_decision"] == "reject"

    def test_reject_sin_motivo_es_rechazado_por_decision_clinica(self, monkeypatch, conn):
        _monkeypatchear_paciente_encontrado(monkeypatch)
        monkeypatch.setattr(
            dt, "_diagnosticar_y_recomendar",
            lambda pid, facts: _resultado_recomendacion([_candidato("pembro_paclitaxel", True)]),
        )
        monkeypatch.setattr(dt, "obtener_conexion", lambda: conn)

        resultado = json.loads(
            dt.registrar_decision_tratamiento.invoke(
                {"patient_id": 1, "oncologo_id": 9, "tipo_decision": "reject"}
            )
        )
        assert resultado["registrado"] is False


class TestAccept:
    def test_accept_sin_recomendacion_resuelta_da_error(self, monkeypatch):
        _monkeypatchear_paciente_encontrado(monkeypatch)
        monkeypatch.setattr(
            dt, "_diagnosticar_y_recomendar",
            lambda pid, facts: {"requiere_mas_datos": True, "sin_guia_aplicable": False, "mensaje": "..."},
        )
        resultado = json.loads(
            dt.registrar_decision_tratamiento.invoke({"patient_id": 1, "oncologo_id": 9, "tipo_decision": "accept"})
        )
        assert "error" in resultado

    def test_accept_sin_interacciones_se_confirma_directo(self, monkeypatch, conn):
        _monkeypatchear_paciente_encontrado(monkeypatch)
        monkeypatch.setattr(
            dt, "_diagnosticar_y_recomendar",
            lambda pid, facts: _resultado_recomendacion([_candidato("pembro_paclitaxel", True)]),
        )
        monkeypatch.setattr(
            dt, "resolver_chequeo_interacciones",
            lambda pid, rid: _Resolucion(chequeo=_chequeo_sin_interacciones(rid)),
        )
        monkeypatch.setattr(dt, "obtener_conexion", lambda: conn)

        resultado = json.loads(
            dt.registrar_decision_tratamiento.invoke({"patient_id": 1, "oncologo_id": 9, "tipo_decision": "accept"})
        )
        assert resultado["registrado"] is True
        assert resultado["regimen_final_id"] == "pembro_paclitaxel"

    def test_accept_con_interaccion_mayor_sin_justificar_no_se_registra(self, monkeypatch, conn):
        _monkeypatchear_paciente_encontrado(monkeypatch)
        monkeypatch.setattr(
            dt, "_diagnosticar_y_recomendar",
            lambda pid, facts: _resultado_recomendacion([_candidato("pembro_paclitaxel", True)]),
        )
        monkeypatch.setattr(
            dt, "resolver_chequeo_interacciones",
            lambda pid, rid: _Resolucion(chequeo=_chequeo_con_interaccion_mayor(rid)),
        )
        monkeypatch.setattr(dt, "obtener_conexion", lambda: conn)

        resultado = json.loads(
            dt.registrar_decision_tratamiento.invoke({"patient_id": 1, "oncologo_id": 9, "tipo_decision": "accept"})
        )
        assert resultado["registrado"] is False


class TestModify:
    def test_modify_sin_regimen_final_id_da_error(self, monkeypatch):
        _monkeypatchear_paciente_encontrado(monkeypatch)
        monkeypatch.setattr(
            dt, "_diagnosticar_y_recomendar",
            lambda pid, facts: _resultado_recomendacion([_candidato("pembro_paclitaxel", True)]),
        )
        resultado = json.loads(
            dt.registrar_decision_tratamiento.invoke({"patient_id": 1, "oncologo_id": 9, "tipo_decision": "modify"})
        )
        assert "error" in resultado

    def test_modify_con_regimen_fuera_del_catalogo_lo_rechaza_el_chequeo_de_interacciones(self, monkeypatch):
        """resolver_chequeo_interacciones (TX-03) es quien primero se
        entera de que el régimen no existe -- ver decision_clinica/tests
        para el otro guard (régimen que SÍ existe pero no fue
        candidato)."""
        _monkeypatchear_paciente_encontrado(monkeypatch)
        monkeypatch.setattr(
            dt, "_diagnosticar_y_recomendar",
            lambda pid, facts: _resultado_recomendacion([_candidato("pembro_paclitaxel", True)]),
        )
        monkeypatch.setattr(
            dt, "resolver_chequeo_interacciones",
            lambda pid, rid: _Resolucion(error={"error": f"'{rid}' no existe en regimens.yaml"}),
        )
        resultado = json.loads(
            dt.registrar_decision_tratamiento.invoke(
                {"patient_id": 1, "oncologo_id": 9, "tipo_decision": "modify", "regimen_final_id": "x"}
            )
        )
        assert "error" in resultado

    def test_modify_exitoso_registra_el_diff_sugerido_vs_final(self, monkeypatch, conn):
        _monkeypatchear_paciente_encontrado(monkeypatch)
        monkeypatch.setattr(
            dt, "_diagnosticar_y_recomendar",
            lambda pid, facts: _resultado_recomendacion(
                [_candidato("pembro_paclitaxel", True), _candidato("pembro_carboplatin_gemcitabine", False)]
            ),
        )
        monkeypatch.setattr(
            dt, "resolver_chequeo_interacciones",
            lambda pid, rid: _Resolucion(chequeo=_chequeo_sin_interacciones(rid)),
        )
        monkeypatch.setattr(dt, "obtener_conexion", lambda: conn)

        resultado = json.loads(
            dt.registrar_decision_tratamiento.invoke(
                {
                    "patient_id": 1, "oncologo_id": 9, "tipo_decision": "modify",
                    "regimen_final_id": "pembro_carboplatin_gemcitabine",
                }
            )
        )
        assert resultado["registrado"] is True
        assert resultado["regimen_sugerido_id"] == "pembro_paclitaxel"
        assert resultado["regimen_final_id"] == "pembro_carboplatin_gemcitabine"
