"""Pruebas de aceptación IA-05 — Explicabilidad de recomendaciones."""

from dx_clinica.builder import construir_diagnosticos_diferenciales
from historia_clinica_mock.adapters import obtener_hallazgos_de_paciente
from historia_clinica_mock.repository import obtener_paciente
from ia_clinica.explainability import (
    ConfidenceLevel,
    EvidenceTrace,
    ExplanationService,
    PatientFactTrace,
)


class TestDatosYEvidenciaVisibles:
    def test_explica_candidato_con_datos_trazables_y_evidencia(self, conn_sembrada):
        conn, ids = conn_sembrada
        paciente = obtener_paciente(conn, ids["paciente_maria"])
        hallazgos = obtener_hallazgos_de_paciente(conn, paciente.id)
        candidato = construir_diagnosticos_diferenciales(paciente, hallazgos).candidatos[0]

        explanation = ExplanationService().explain_differential_candidate(candidato, hallazgos)

        assert explanation.recommendation
        assert explanation.has_traceable_patient_data
        assert explanation.evidence is not None
        assert explanation.evidence.organization == "ESMO"
        assert explanation.evidence.source_path.endswith("metadata.yaml")
        assert set(f.fact_id for f in explanation.patient_facts) <= {h.id for h in hallazgos}
        assert len([f.fact_id for f in explanation.patient_facts]) == len(set(f.fact_id for f in explanation.patient_facts))
        assert explanation.evidence.source_path.startswith("guidelines/")

    def test_expone_fecha_origen_e_id_de_cada_dato_usado(self, conn_sembrada):
        conn, ids = conn_sembrada
        paciente = obtener_paciente(conn, ids["paciente_carlos"])
        hallazgos = obtener_hallazgos_de_paciente(conn, paciente.id)
        candidato = construir_diagnosticos_diferenciales(paciente, hallazgos).candidatos[0]

        explanation = ExplanationService().explain_differential_candidate(candidato, hallazgos)

        assert explanation.patient_facts
        for fact in explanation.patient_facts:
            assert fact.fact_id
            assert fact.value
            assert fact.source_type
            assert fact.date


class TestNoFalsaConfianza:
    def test_sin_evidencia_marca_not_evaluable_y_lo_declara(self, conn_sembrada):
        conn, ids = conn_sembrada
        paciente = obtener_paciente(conn, ids["paciente_carlos"])
        hallazgos = obtener_hallazgos_de_paciente(conn, paciente.id)
        resultado = construir_diagnosticos_diferenciales(paciente, hallazgos)
        candidato = next(c for c in resultado.candidatos if c.perfil_id == "proceso_infeccioso_respiratorio")

        explanation = ExplanationService().explain_differential_candidate(candidato, hallazgos)

        assert explanation.evidence is None
        assert explanation.confidence == ConfidenceLevel.NOT_EVALUABLE
        assert any("No hay una guía o fuente de evidencia" in x for x in explanation.limitations)
        assert explanation.explicitly_reports_uncertainty

    def test_sin_datos_de_paciente_marca_not_evaluable(self):
        evidence = EvidenceTrace(
            module_id="test",
            organization="TEST",
            title="Fuente sintética",
            publication_year=2026,
            doi=None,
            validation_status="validated",
            source_path="test/metadata.yaml",
        )

        explanation = ExplanationService().build(
            recommendation="Recomendación sintética",
            source_component="TEST",
            rationale="Prueba",
            patient_facts=[],
            evidence=evidence,
        )

        assert explanation.confidence == ConfidenceLevel.NOT_EVALUABLE
        assert any("No hay datos clínicos trazables" in x for x in explanation.limitations)

    def test_guia_con_validacion_pendiente_no_puede_ser_high(self, conn_sembrada):
        conn, ids = conn_sembrada
        paciente = obtener_paciente(conn, ids["paciente_maria"])
        hallazgos = obtener_hallazgos_de_paciente(conn, paciente.id)
        candidato = construir_diagnosticos_diferenciales(paciente, hallazgos).candidatos[0]

        explanation = ExplanationService().explain_differential_candidate(candidato, hallazgos)

        assert explanation.evidence is not None
        assert explanation.evidence.validation_status == "pending"
        assert explanation.confidence == ConfidenceLevel.LOW
        assert any("validación clínica final" in x for x in explanation.limitations)

    def test_datos_faltantes_se_exponen_en_lugar_de_ocultarse(self, conn_sembrada):
        conn, ids = conn_sembrada
        paciente = obtener_paciente(conn, ids["paciente_carlos"])
        hallazgos = obtener_hallazgos_de_paciente(conn, paciente.id)
        resultado = construir_diagnosticos_diferenciales(paciente, hallazgos)
        candidato = next(c for c in resultado.candidatos if c.criterios_sin_sustento)

        explanation = ExplanationService().explain_differential_candidate(candidato, hallazgos)

        assert explanation.missing_data == candidato.criterios_sin_sustento
        assert explanation.explicitly_reports_uncertainty


class TestConfianzaNoProbabilistica:
    def test_confianza_no_es_porcentaje(self):
        fact = PatientFactTrace("h1", "hallazgo", "consulta", "2026-01-01")
        evidence = EvidenceTrace("m1", "ORG", "Guía", 2026, None, "validated", "metadata.yaml")
        explanation = ExplanationService().build(
            recommendation="Recomendación",
            source_component="TEST",
            rationale="Razonamiento",
            patient_facts=[fact],
            evidence=evidence,
        )

        assert explanation.confidence == ConfidenceLevel.HIGH
        assert "%" not in explanation.confidence.value
        assert not hasattr(explanation, "probability")
        assert not hasattr(explanation, "percentage")

    def test_fuente_y_datos_completos_permiten_high_solo_si_validada(self):
        fact = PatientFactTrace("h1", "hallazgo", "consulta", "2026-01-01")
        evidence = EvidenceTrace("m1", "ORG", "Guía", 2026, None, "validated", "metadata.yaml")
        explanation = ExplanationService().build(
            recommendation="Recomendación",
            source_component="TEST",
            rationale="Razonamiento",
            patient_facts=[fact],
            evidence=evidence,
            missing_data=[],
        )

        assert explanation.confidence == ConfidenceLevel.HIGH
        assert explanation.limitations == ()
