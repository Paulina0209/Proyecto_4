import pytest

from ia_clinica.summary.models import (
    AI_SUMMARY_DISCLAIMER,
    DIAGNOSTICO,
    ESTADIO,
    ESTADO_ACTUAL,
    MISSING_INFO_MARKER,
    TRATAMIENTOS_PREVIOS,
    CaseSummary,
    CaseSummaryContext,
    CaseSummarySection,
    SourceSpan,
)


class TestCaseSummaryContext:
    def test_patient_ref_vacio_lanza_error(self):
        with pytest.raises(ValueError):
            CaseSummaryContext(patient_ref="  ", paciente_id=1, diagnostico_principal=None, estadio=None)

    def test_ids_de_segmentos_duplicados_lanza_error(self):
        with pytest.raises(ValueError):
            CaseSummaryContext(
                patient_ref="paciente-1",
                paciente_id=1,
                diagnostico_principal=None,
                estadio=None,
                segments=[
                    SourceSpan(id="seg-1", text="a"),
                    SourceSpan(id="seg-1", text="b"),
                ],
            )

    def test_es_vacio_solo_si_no_hay_nada_en_absoluto(self):
        assert CaseSummaryContext(
            patient_ref="paciente-1", paciente_id=1, diagnostico_principal=None, estadio=None, segments=[]
        ).is_empty()
        assert not CaseSummaryContext(
            patient_ref="paciente-1", paciente_id=1, diagnostico_principal="X", estadio=None, segments=[]
        ).is_empty()
        assert not CaseSummaryContext(
            patient_ref="paciente-1",
            paciente_id=1,
            diagnostico_principal=None,
            estadio=None,
            segments=[SourceSpan(id="seg-1", text="a")],
        ).is_empty()

    def test_get_segment_devuelve_none_si_no_existe(self):
        contexto = CaseSummaryContext(
            patient_ref="paciente-1", paciente_id=1, diagnostico_principal=None, estadio=None, segments=[]
        )
        assert contexto.get_segment("no-existe") is None


class TestCaseSummary:
    def _resumen(self, secciones):
        from datetime import datetime

        return CaseSummary(
            patient_ref="paciente-1",
            paciente_id=1,
            generated_at=datetime(2026, 1, 1),
            sections=secciones,
        )

    def test_es_siempre_borrador_de_ia_sin_setter(self):
        resumen = self._resumen([])
        assert resumen.is_ai_generated_draft is True
        assert resumen.disclaimer == AI_SUMMARY_DISCLAIMER
        assert not hasattr(resumen, "aprobar")
        assert not hasattr(resumen, "finalizar")

    def test_secciones_faltantes_solo_incluye_las_no_documentadas(self):
        resumen = self._resumen(
            [
                CaseSummarySection(key=DIAGNOSTICO, label="Diagnóstico", content="X", status="documented"),
                CaseSummarySection(key=ESTADIO, label="Estadio", content=MISSING_INFO_MARKER, status="missing"),
                CaseSummarySection(
                    key=TRATAMIENTOS_PREVIOS, label="Tratamientos previos", content=MISSING_INFO_MARKER, status="missing"
                ),
                CaseSummarySection(key=ESTADO_ACTUAL, label="Estado actual", content="Y", status="documented"),
            ]
        )

        assert resumen.secciones_faltantes() == ["Estadio", "Tratamientos previos"]
        assert resumen.tiene_informacion_incompleta()

    def test_sin_secciones_faltantes_no_hay_informacion_incompleta(self):
        resumen = self._resumen(
            [CaseSummarySection(key=DIAGNOSTICO, label="Diagnóstico", content="X", status="documented")]
        )
        assert resumen.secciones_faltantes() == []
        assert not resumen.tiene_informacion_incompleta()

    def test_to_dict_incluye_secciones_faltantes(self):
        resumen = self._resumen(
            [CaseSummarySection(key=ESTADIO, label="Estadio", content=MISSING_INFO_MARKER, status="missing")]
        )
        data = resumen.to_dict()
        assert data["secciones_faltantes"] == ["Estadio"]
        assert data["is_ai_generated_draft"] is True

    def test_to_text_sin_faltantes_no_incluye_advertencia(self):
        resumen = self._resumen(
            [CaseSummarySection(key=DIAGNOSTICO, label="Diagnóstico", content="X", status="documented")]
        )
        assert "INFORMACIÓN INCOMPLETA" not in resumen.to_text()
