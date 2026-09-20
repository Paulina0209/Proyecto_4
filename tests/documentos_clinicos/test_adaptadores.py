"""Pruebas de los adaptadores de DOC-02: traducción de fuentes reales del
repositorio (resumen de caso de IA-04, expediente completo de
``historia_clinica_mock``) al modelo genérico ``DocumentoExportable``.
"""

from datetime import datetime

import pytest

from historia_clinica_mock.adapters import PacienteNoEncontradoError

from ia_clinica.summary.models import (
    DIAGNOSTICO,
    ESTADIO,
    ESTADO_ACTUAL,
    MISSING_INFO_MARKER,
    TRATAMIENTOS_PREVIOS,
    CaseSummary,
    CaseSummarySection,
)

from documentos_clinicos.adaptadores import (
    expediente_completo_a_documento_exportable,
    resumen_caso_a_documento_exportable,
)


def _resumen_completo() -> CaseSummary:
    return CaseSummary(
        patient_ref="paciente-1",
        paciente_id=1,
        generated_at=datetime(2026, 1, 1, 10, 0),
        sections=[
            CaseSummarySection(key=DIAGNOSTICO, label="Diagnóstico", content="Cáncer de mama", status="documented"),
            CaseSummarySection(key=ESTADIO, label="Estadio", content="II", status="documented"),
            CaseSummarySection(
                key=TRATAMIENTOS_PREVIOS,
                label="Tratamientos previos",
                content="Quimioterapia neoadyuvante.",
                status="documented",
            ),
            CaseSummarySection(
                key=ESTADO_ACTUAL, label="Estado actual", content="Buena respuesta clínica.", status="documented"
            ),
        ],
    )


def _resumen_incompleto() -> CaseSummary:
    return CaseSummary(
        patient_ref="paciente-7",
        paciente_id=7,
        generated_at=datetime(2026, 1, 1, 10, 0),
        sections=[
            CaseSummarySection(key=DIAGNOSTICO, label="Diagnóstico", content="Cáncer de ovario", status="documented"),
            CaseSummarySection(key=ESTADIO, label="Estadio", content=MISSING_INFO_MARKER, status="missing"),
            CaseSummarySection(
                key=TRATAMIENTOS_PREVIOS,
                label="Tratamientos previos",
                content=MISSING_INFO_MARKER,
                status="missing",
            ),
            CaseSummarySection(key=ESTADO_ACTUAL, label="Estado actual", content=MISSING_INFO_MARKER, status="missing"),
        ],
        warnings=["Se descartó una afirmación no verificable del modelo."],
    )


class TestResumenCasoADocumentoExportable:
    def test_traduce_cada_seccion_documentada(self):
        documento = resumen_caso_a_documento_exportable(_resumen_completo())

        assert [s.titulo for s in documento.secciones] == ["Diagnóstico", "Estadio", "Tratamientos previos", "Estado actual"]
        assert documento.paciente_ref == "paciente-1"
        assert documento.generado_en == datetime(2026, 1, 1, 10, 0)
        assert documento.tiene_contenido() is True

    def test_conserva_el_disclaimer_de_ia(self):
        resumen = _resumen_completo()

        documento = resumen_caso_a_documento_exportable(resumen)

        assert documento.disclaimer == resumen.disclaimer
        assert "IA" in documento.disclaimer

    def test_secciones_faltantes_se_agregan_como_advertencia_visible(self):
        documento = resumen_caso_a_documento_exportable(_resumen_incompleto())

        assert any("Estadio" in a and "Tratamientos previos" in a and "Estado actual" in a for a in documento.advertencias)

    def test_advertencias_del_resumen_original_se_conservan(self):
        documento = resumen_caso_a_documento_exportable(_resumen_incompleto())

        assert "Se descartó una afirmación no verificable del modelo." in documento.advertencias

    def test_resumen_sin_secciones_faltantes_no_agrega_advertencia_de_faltantes(self):
        documento = resumen_caso_a_documento_exportable(_resumen_completo())

        assert not any("secciones sin información suficiente" in a for a in documento.advertencias)


class TestExpedienteCompletoADocumentoExportable:
    def test_incluye_datos_del_paciente_y_secciones_con_informacion(self, conn_sembrada):
        conn, ids = conn_sembrada

        documento = expediente_completo_a_documento_exportable(conn, ids["paciente_maria"])

        titulos = [s.titulo for s in documento.secciones]
        assert "Datos del paciente" in titulos
        assert "Consultas" in titulos
        assert "Laboratorios" in titulos
        assert "Imagenología" in titulos
        assert "Biomarcadores" in titulos
        assert documento.tiene_contenido() is True

    def test_no_pasa_por_ningun_llm_el_disclaimer_es_del_expediente(self, conn_sembrada):
        conn, ids = conn_sembrada

        documento = expediente_completo_a_documento_exportable(conn, ids["paciente_maria"])

        assert "expediente clínico" in documento.disclaimer.lower()

    def test_paciente_sin_comorbilidades_reales_no_incluye_esa_seccion(self, conn_sembrada):
        # María solo tiene la comorbilidad centinela "ninguna_registrada",
        # que no debe presentarse como si fuera una condición real.
        conn, ids = conn_sembrada

        documento = expediente_completo_a_documento_exportable(conn, ids["paciente_maria"])

        assert "Comorbilidades" not in [s.titulo for s in documento.secciones]

    def test_paciente_con_comorbilidad_real_si_incluye_la_seccion(self, conn_sembrada):
        conn, ids = conn_sembrada
        conn.execute(
            "INSERT INTO comorbilidades "
            "(paciente_id, consulta_id, fecha_registro, condicion, severidad, tipo_contraindicacion_ici) "
            "VALUES (?, NULL, ?, ?, ?, ?)",
            (ids["paciente_maria"], "2026-02-01", "diabetes_mellitus_tipo_2", "moderada", None),
        )
        conn.commit()

        documento = expediente_completo_a_documento_exportable(conn, ids["paciente_maria"])

        seccion = next(s for s in documento.secciones if s.titulo == "Comorbilidades")
        assert seccion.bloques[0].filas == (("2026-02-01", "diabetes_mellitus_tipo_2", "moderada", "No"),)

    def test_usa_ahora_explicito_cuando_se_provee(self, conn_sembrada):
        conn, ids = conn_sembrada
        referencia = datetime(2026, 3, 1, 9, 30)

        documento = expediente_completo_a_documento_exportable(conn, ids["paciente_maria"], ahora=referencia)

        assert documento.generado_en == referencia

    def test_paciente_inexistente_lanza_error_explicito(self, conn_sembrada):
        conn, _ids = conn_sembrada

        with pytest.raises(PacienteNoEncontradoError):
            expediente_completo_a_documento_exportable(conn, 99999)
