"""Tests de tx_clinica/tools/interaction_tools.py y _interaction_shared.py
(TX-03).

Monkeypatchea todo lo que toca base de datos (dentro de
_interaction_shared, que es donde vive esa lógica) y apunta
GUIDELINES_ROOT + interacciones_farmacologicas.checker.RUTA_REGLAS_INTERACCIONES
a directorios de prueba -- no toca ni tu guidelines/ real ni
interacciones_farmacologicas/docs/rules_interacciones/ real.
"""

from __future__ import annotations

import json

import pytest
import yaml

import interacciones_farmacologicas.checker as checker_module
from tx_clinica.tools import _interaction_shared as ish
from tx_clinica.tools import interaction_tools as it
from tx_clinica.tools.patients_tools import ErrorPacienteNoEncontrado, PacienteResuelto

MODULO = "breast_metastatic_tnbc"  # ya definido en conftest.py (guidelines_root)

REGLAS_PRUEBA = [
    {
        "id": "TEST-INT-001",
        "conditions": {
            "all": [
                {"field": "prescribed_antineoplastic_drugs", "operator": "contains", "value": "paclitaxel"},
                {"field": "concomitant_strong_cyp3a4_inducer", "operator": "equals", "value": True},
            ]
        },
        "conclusion": {
            "interaction_id": "paclitaxel_cyp3a4_inducer_test",
            "severity": "major",
            "audit_effect": "requires_justification",
            "description": "Interacción de prueba.",
            "recommendation": "Revisar.",
            "concomitant_drug": "inductor CYP3A4",
            "source": {"titulo": "Prueba"},
        },
    }
]


@pytest.fixture(autouse=True)
def _apuntar_rutas_de_prueba(monkeypatch, guidelines_root, tmp_path):
    monkeypatch.setattr(ish, "GUIDELINES_ROOT", guidelines_root)

    ruta_reglas = tmp_path / "rules_interacciones_prueba"
    ruta_reglas.mkdir()
    (ruta_reglas / f"{MODULO}.yaml").write_text(yaml.safe_dump({"rules": REGLAS_PRUEBA}), encoding="utf-8")
    monkeypatch.setattr(checker_module, "RUTA_REGLAS_INTERACCIONES", ruta_reglas)


def _monkeypatchear_paciente_encontrado(monkeypatch, medicacion_actual, estado_conciliacion, facts):
    monkeypatch.setattr(it, "obtener_paciente_o_error", lambda pid: PacienteResuelto(paciente_id=pid, paciente=object()))
    monkeypatch.setattr(ish, "construir_facts_paciente", lambda conn, pid: facts)
    monkeypatch.setattr(ish, "listar_medicacion_activa", lambda conn, pid: medicacion_actual)
    monkeypatch.setattr(ish, "obtener_estado_conciliacion", lambda conn, pid: estado_conciliacion)
    monkeypatch.setattr(ish, "obtener_conexion", lambda: None)
    monkeypatch.setattr(it, "obtener_conexion", lambda: None)


_FACTS_BREAST_RESUELTO = {
    "cancer_type": "breast", "disease_setting": "metastatic",
    "treatment_line": 1, "pdl1_cps": 15,
}


class TestChequearInteraccionesTratamiento:
    def test_paciente_inexistente_da_error_explicito(self, monkeypatch):
        monkeypatch.setattr(it, "obtener_paciente_o_error", lambda pid: ErrorPacienteNoEncontrado(pid))
        resultado = json.loads(
            it.chequear_interacciones_tratamiento.invoke({"patient_id": 999, "regimen_id": "pembro_paclitaxel"})
        )
        assert resultado["error"] == "paciente_no_registrado"

    def test_sin_conciliar_nunca_dice_sin_interacciones(self, monkeypatch):
        _monkeypatchear_paciente_encontrado(
            monkeypatch, medicacion_actual=[], estado_conciliacion="no_realizada", facts=_FACTS_BREAST_RESUELTO
        )
        resultado = json.loads(
            it.chequear_interacciones_tratamiento.invoke({"patient_id": 1, "regimen_id": "pembro_paclitaxel"})
        )
        assert resultado["requiere_conciliacion_medicamentos"] is True
        assert resultado["sin_interacciones_conocidas"] is False

    def test_interaccion_detectada_con_medicacion_conciliada(self, monkeypatch):
        _monkeypatchear_paciente_encontrado(
            monkeypatch,
            medicacion_actual=["rifampicina"],
            estado_conciliacion="con_medicacion_registrada",
            facts=_FACTS_BREAST_RESUELTO,
        )
        resultado = json.loads(
            it.chequear_interacciones_tratamiento.invoke({"patient_id": 1, "regimen_id": "pembro_paclitaxel"})
        )
        assert resultado["interacciones_disponibles"] is True
        assert len(resultado["interacciones"]) == 1
        assert resultado["interacciones"][0]["interaccion_id"] == "paclitaxel_cyp3a4_inducer_test"
        assert resultado["interacciones"][0]["audit_effect"] == "requires_justification"

    def test_sin_medicacion_concomitante_conciliada_da_sin_interacciones(self, monkeypatch):
        _monkeypatchear_paciente_encontrado(
            monkeypatch, medicacion_actual=[], estado_conciliacion="sin_medicacion_concomitante",
            facts=_FACTS_BREAST_RESUELTO,
        )
        resultado = json.loads(
            it.chequear_interacciones_tratamiento.invoke({"patient_id": 1, "regimen_id": "pembro_paclitaxel"})
        )
        assert resultado["sin_interacciones_conocidas"] is True

    def test_regimen_inexistente_da_error_explicito(self, monkeypatch):
        _monkeypatchear_paciente_encontrado(
            monkeypatch, medicacion_actual=[], estado_conciliacion="con_medicacion_registrada",
            facts=_FACTS_BREAST_RESUELTO,
        )
        resultado = json.loads(
            it.chequear_interacciones_tratamiento.invoke({"patient_id": 1, "regimen_id": "regimen_inventado"})
        )
        assert "error" in resultado

    def test_modulo_sin_contenido_de_interacciones_da_mensaje_explicito(self, monkeypatch):
        """cutaneous_melanoma sí existe en guidelines_root pero NO tiene
        archivo en rules_interacciones/ (solo escribimos uno para
        breast_metastatic_tnbc) -- debe decirlo, no fingir 'sin
        interacciones'."""
        _monkeypatchear_paciente_encontrado(
            monkeypatch, medicacion_actual=[], estado_conciliacion="con_medicacion_registrada",
            facts={
                "cancer_type": "melanoma", "melanoma_primary_site": "cutaneous",
                "treatment_phase": "adjuvant", "stage_group": "IIB", "age_years": 47,
            },
        )
        resultado = json.loads(
            it.chequear_interacciones_tratamiento.invoke(
                {"patient_id": 1, "regimen_id": "pembro_adjuvant_stage_iib_iic"}
            )
        )
        assert resultado.get("interacciones_disponibles") is False

    def test_variables_faltantes_en_fase_1_no_llega_a_chequear_interacciones(self, monkeypatch):
        _monkeypatchear_paciente_encontrado(
            monkeypatch, medicacion_actual=[], estado_conciliacion="con_medicacion_registrada",
            facts={"cancer_type": "breast"},  # falta disease_setting
        )
        resultado = json.loads(
            it.chequear_interacciones_tratamiento.invoke({"patient_id": 1, "regimen_id": "pembro_paclitaxel"})
        )
        assert resultado["requiere_mas_datos"] is True


class TestConsultarMedicacionActual:
    def test_paciente_inexistente_da_error_explicito(self, monkeypatch):
        monkeypatch.setattr(it, "obtener_paciente_o_error", lambda pid: ErrorPacienteNoEncontrado(pid))
        resultado = json.loads(it.consultar_medicacion_actual.invoke({"patient_id": 999}))
        assert resultado["error"] == "paciente_no_registrado"

    def test_devuelve_medicacion_y_estado_de_conciliacion(self, monkeypatch):
        monkeypatch.setattr(it, "obtener_paciente_o_error", lambda pid: PacienteResuelto(paciente_id=pid, paciente=object()))
        monkeypatch.setattr(it, "obtener_conexion", lambda: None)
        monkeypatch.setattr(it, "listar_medicacion_activa", lambda conn, pid: ["rifampicina"])
        monkeypatch.setattr(it, "obtener_estado_conciliacion", lambda conn, pid: "con_medicacion_registrada")
        resultado = json.loads(it.consultar_medicacion_actual.invoke({"patient_id": 1}))
        assert resultado["medicacion_activa"] == ["rifampicina"]
        assert resultado["estado_conciliacion"] == "con_medicacion_registrada"
