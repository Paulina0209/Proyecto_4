"""Pruebas de aceptación de IA-04 — Resumen clínico de caso.

Cada clase de prueba está anclada a uno de los dos criterios de
aceptación de la historia de usuario, más una clase adicional para la
regla de no-alucinación heredada del resto del proyecto. Se usa
``ScriptedSummaryLLMClient`` para controlar exactamente qué "dice" el
modelo en cada escenario, de forma que las pruebas sean deterministas y
no dependan de ningún proveedor externo.
"""

import pytest

from ia_clinica.summary.generator import CaseSummaryGenerationError, CaseSummaryGenerator
from ia_clinica.summary.models import (
    DIAGNOSTICO,
    ESTADIO,
    ESTADO_ACTUAL,
    MISSING_INFO_MARKER,
    TRATAMIENTOS_PREVIOS,
    CaseSummaryContext,
)

from ._llm_test_doubles import ScriptedSummaryLLMClient, section


# ---------------------------------------------------------------------------
# AC1 — Dado un paciente con historia clínica suficiente, cuando se solicita
# el resumen, se recibe un documento estructurado listo para presentarse en
# junta médica.
# ---------------------------------------------------------------------------
class TestGeneraDocumentoEstructurado:
    def test_las_cuatro_secciones_quedan_documentadas(self, contexto_completo):
        llm = ScriptedSummaryLLMClient(
            response_payload={
                "sections": [
                    section(
                        TRATAMIENTOS_PREVIOS,
                        content="Recibió quimioterapia neoadyuvante.",
                        source_span_ids=["consulta-1-nota-1"],
                    ),
                    section(
                        ESTADO_ACTUAL,
                        content="Actualmente se siente mejor, sin dolor articular.",
                        source_span_ids=["consulta-1-nota-2"],
                    ),
                ]
            }
        )
        generator = CaseSummaryGenerator(llm_client=llm)

        resumen = generator.generate_summary(contexto_completo)

        assert [s.key for s in resumen.sections] == [DIAGNOSTICO, ESTADIO, TRATAMIENTOS_PREVIOS, ESTADO_ACTUAL]
        assert all(s.status == "documented" for s in resumen.sections)
        assert not resumen.tiene_informacion_incompleta()
        assert resumen.get_section(DIAGNOSTICO).content == "Cáncer de mama triple negativo"
        assert resumen.get_section(ESTADIO).content == "II"

    def test_diagnostico_y_estadio_nunca_se_piden_al_modelo(self, contexto_completo):
        llm = ScriptedSummaryLLMClient(response_payload={"sections": []})
        generator = CaseSummaryGenerator(llm_client=llm)

        generator.generate_summary(contexto_completo)

        # El generador debe poblar diagnóstico/estadio directamente del
        # expediente estructurado, sin depender de nada que el modelo
        # "redacte": el prompt nunca le pide producir esas dos claves.
        assert f'"{DIAGNOSTICO}"' not in llm.last_system_prompt
        assert f'"{ESTADIO}"' not in llm.last_system_prompt

    def test_es_siempre_un_documento_generado_por_ia(self, contexto_completo):
        llm = ScriptedSummaryLLMClient(response_payload={"sections": []})
        generator = CaseSummaryGenerator(llm_client=llm)

        resumen = generator.generate_summary(contexto_completo)

        assert resumen.is_ai_generated_draft is True
        assert "IA" in resumen.disclaimer

    def test_documento_de_texto_incluye_disclaimer_y_secciones(self, contexto_completo):
        llm = ScriptedSummaryLLMClient(
            response_payload={
                "sections": [
                    section(TRATAMIENTOS_PREVIOS, content="Quimioterapia.", source_span_ids=["consulta-1-nota-1"]),
                    section(ESTADO_ACTUAL, content="Mejoría clínica.", source_span_ids=["consulta-1-nota-2"]),
                ]
            }
        )
        generator = CaseSummaryGenerator(llm_client=llm)

        texto = generator.generate_summary(contexto_completo).to_text()

        assert "RESUMEN GENERADO AUTOMÁTICAMENTE POR IA" in texto
        assert "Diagnóstico" in texto
        assert "Estadio" in texto
        assert "Tratamientos previos" in texto
        assert "Estado actual" in texto

    def test_contexto_totalmente_vacio_no_genera_nada(self):
        contexto_vacio = CaseSummaryContext(
            patient_ref="paciente-9", paciente_id=9, diagnostico_principal=None, estadio=None, segments=[]
        )
        generator = CaseSummaryGenerator(llm_client=ScriptedSummaryLLMClient(response_payload={"sections": []}))

        with pytest.raises(ValueError):
            generator.generate_summary(contexto_vacio)


# ---------------------------------------------------------------------------
# AC2 — Dado que el paciente tiene información incompleta, cuando se genera
# el resumen, el documento indica explícitamente las secciones con datos
# faltantes.
# ---------------------------------------------------------------------------
class TestIndicaSeccionesFaltantesExplicitamente:
    def test_estadio_ausente_queda_marcado_como_faltante(self, contexto_incompleto):
        llm = ScriptedSummaryLLMClient(response_payload={"sections": []})
        generator = CaseSummaryGenerator(llm_client=llm)

        resumen = generator.generate_summary(contexto_incompleto)

        estadio_section = resumen.get_section(ESTADIO)
        assert estadio_section.status == "missing"
        assert estadio_section.content == MISSING_INFO_MARKER
        assert "Estadio" in resumen.secciones_faltantes()

    def test_secciones_derivadas_sin_hallazgos_quedan_marcadas_como_faltantes(self, contexto_incompleto):
        llm = ScriptedSummaryLLMClient(response_payload={"sections": []})
        generator = CaseSummaryGenerator(llm_client=llm)

        resumen = generator.generate_summary(contexto_incompleto)

        assert resumen.get_section(TRATAMIENTOS_PREVIOS).status == "missing"
        assert resumen.get_section(ESTADO_ACTUAL).status == "missing"
        assert resumen.tiene_informacion_incompleta()

    def test_documento_de_texto_advierte_visiblemente_sobre_lo_faltante(self, contexto_incompleto):
        llm = ScriptedSummaryLLMClient(response_payload={"sections": []})
        generator = CaseSummaryGenerator(llm_client=llm)

        texto = generator.generate_summary(contexto_incompleto).to_text()

        assert "INFORMACIÓN INCOMPLETA" in texto
        assert MISSING_INFO_MARKER in texto

    def test_diagnostico_documentado_no_impide_marcar_lo_demas_como_faltante(self, contexto_incompleto):
        # AC2 no exige que TODO falte, solo que lo que falta se indique.
        llm = ScriptedSummaryLLMClient(response_payload={"sections": []})
        generator = CaseSummaryGenerator(llm_client=llm)

        resumen = generator.generate_summary(contexto_incompleto)

        assert resumen.get_section(DIAGNOSTICO).status == "documented"
        assert resumen.tiene_informacion_incompleta()

    def test_sin_ningun_hallazgo_no_se_llama_al_modelo(self):
        contexto_sin_hallazgos = CaseSummaryContext(
            patient_ref="paciente-3",
            paciente_id=3,
            diagnostico_principal="Melanoma cutáneo",
            estadio="IIB",
            segments=[],
        )
        llm = ScriptedSummaryLLMClient(response_payload={"sections": []})
        generator = CaseSummaryGenerator(llm_client=llm)

        resumen = generator.generate_summary(contexto_sin_hallazgos)

        assert llm.times_called == 0
        assert resumen.get_section(TRATAMIENTOS_PREVIOS).status == "missing"
        assert resumen.get_section(ESTADO_ACTUAL).status == "missing"


# ---------------------------------------------------------------------------
# Regla de negocio heredada del resto del proyecto: nunca se inventa
# contenido clínico, ni siquiera cuando el modelo lo entrega bien formado.
# ---------------------------------------------------------------------------
class TestNoInventaContenido:
    def test_contenido_que_cita_fragmento_inexistente_se_descarta(self, contexto_completo):
        llm = ScriptedSummaryLLMClient(
            response_payload={
                "sections": [
                    section(
                        TRATAMIENTOS_PREVIOS,
                        content="Recibió terapia dirigida experimental.",
                        source_span_ids=["fragmento-que-no-existe"],
                    )
                ]
            }
        )
        generator = CaseSummaryGenerator(llm_client=llm)

        resumen = generator.generate_summary(contexto_completo)

        tratamientos = resumen.get_section(TRATAMIENTOS_PREVIOS)
        assert tratamientos.status == "missing"
        assert tratamientos.content == MISSING_INFO_MARKER
        assert any("descartada" in w for w in resumen.warnings)

    def test_seccion_marcada_como_missing_por_el_modelo_se_respeta(self, contexto_completo):
        llm = ScriptedSummaryLLMClient(
            response_payload={"sections": [section(ESTADO_ACTUAL, status="missing")]}
        )
        generator = CaseSummaryGenerator(llm_client=llm)

        resumen = generator.generate_summary(contexto_completo)

        assert resumen.get_section(ESTADO_ACTUAL).status == "missing"

    def test_respuesta_no_json_lanza_error_explicito(self, contexto_completo):
        llm = ScriptedSummaryLLMClient(raw_response="esto no es json")
        generator = CaseSummaryGenerator(llm_client=llm)

        with pytest.raises(CaseSummaryGenerationError):
            generator.generate_summary(contexto_completo)

    def test_valor_estructurado_en_blanco_se_trata_como_faltante(self):
        contexto = CaseSummaryContext(
            patient_ref="paciente-4",
            paciente_id=4,
            diagnostico_principal="   ",
            estadio=None,
            segments=[],
        )
        # diagnostico_principal en blanco + estadio None + sin segments
        # sigue sin ser is_empty() porque el valor "en blanco" cuenta como
        # truthy a nivel de Python; se prueba aquí que igual se normaliza
        # a "missing" en vez de mostrarse como contenido vacío.
        llm = ScriptedSummaryLLMClient(response_payload={"sections": []})
        generator = CaseSummaryGenerator(llm_client=llm)

        resumen = generator.generate_summary(contexto)

        assert resumen.get_section(DIAGNOSTICO).status == "missing"
