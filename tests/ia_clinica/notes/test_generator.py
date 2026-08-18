"""Pruebas de aceptación de IA-02 — Generación automática de notas clínicas.

Cada clase de prueba está anclada a uno de los cuatro criterios de
aceptación de la historia de usuario. Se usa ``ScriptedLLMClient`` para
controlar exactamente qué "dice" el modelo en cada escenario, de forma que
las pruebas sean deterministas y no dependan de ningún proveedor externo.
"""

import pytest

from ia_clinica.notes.formats import NoteFormatSpec, NoteSectionSpec, SOAP_FORMAT
from ia_clinica.notes.generator import ClinicalNoteGenerator, GenerationError
from ia_clinica.notes.models import MISSING_INFO_MARKER, ClinicalContext, SourceSpan

from _llm_test_doubles import ScriptedLLMClient, section


# ---------------------------------------------------------------------------
# AC1 — Dado que existe información registrada de una consulta, cuando se
# solicita la nota, el sistema genera un borrador estructurado en SOAP o en
# el estándar configurado.
# ---------------------------------------------------------------------------
class TestGeneraBorradorEstructurado:
    def test_genera_las_cuatro_secciones_soap_en_orden(self, consult_context):
        llm = ScriptedLLMClient(
            response_payload={
                "sections": [
                    section("S", content="Dolor óseo progresivo de tres semanas.", source_span_ids=["seg-1"]),
                    section("O", content="Adenopatía axilar izquierda de 2 cm.", source_span_ids=["seg-2"]),
                    section("A", content="Progresión de enfermedad ósea metastásica.", source_span_ids=["seg-3"]),
                    section("P", content="Gammagrafía ósea y control en dos semanas.", source_span_ids=["seg-4"]),
                ]
            }
        )
        generator = ClinicalNoteGenerator(llm_client=llm)

        draft = generator.generate_draft(consult_context, format_name="SOAP")

        assert draft.format_name == "SOAP"
        assert [s.key for s in draft.sections] == ["S", "O", "A", "P"]
        assert all(s.status == "documented" for s in draft.sections)
        assert draft.get_section("A").content == "Progresión de enfermedad ósea metastásica."

    def test_usa_el_estandar_configurado_por_la_institucion(self, consult_context):
        institution_format = NoteFormatSpec(
            name="APIE",
            sections=(
                NoteSectionSpec(key="AP", label="Antecedentes y Problema", guidance="..."),
                NoteSectionSpec(key="IE", label="Impresión y Estrategia", guidance="..."),
            ),
        )
        llm = ScriptedLLMClient(
            response_payload={
                "sections": [
                    section("AP", content="Dolor óseo progresivo.", source_span_ids=["seg-1"]),
                    section("IE", content="Progresión ósea; se solicita gammagrafía.", source_span_ids=["seg-3", "seg-4"]),
                ]
            }
        )
        generator = ClinicalNoteGenerator(llm_client=llm, institution_formats={"APIE": institution_format})

        draft = generator.generate_draft(consult_context, format_name="APIE")

        assert draft.format_name == "APIE"
        assert [s.key for s in draft.sections] == ["AP", "IE"]

    def test_formato_no_configurado_lanza_error_explicito(self, consult_context):
        generator = ClinicalNoteGenerator(llm_client=ScriptedLLMClient(response_payload={"sections": []}))

        with pytest.raises(ValueError):
            generator.generate_draft(consult_context, format_name="INEXISTENTE")

    def test_contexto_vacio_no_genera_nada(self):
        empty_context = ClinicalContext(consult_id="c-1", patient_ref="p-1", segments=[])
        generator = ClinicalNoteGenerator(llm_client=ScriptedLLMClient(response_payload={"sections": []}))

        with pytest.raises(ValueError):
            generator.generate_draft(empty_context)

    def test_prompt_incluye_solo_los_fragmentos_del_contexto(self, consult_context):
        llm = ScriptedLLMClient(response_payload={"sections": []})
        generator = ClinicalNoteGenerator(llm_client=llm)

        generator.generate_draft(consult_context)

        for segment in consult_context.segments:
            assert segment.text in llm.last_user_prompt
        assert "guías" not in llm.last_user_prompt.lower()
        assert "guideline" not in llm.last_user_prompt.lower()


# ---------------------------------------------------------------------------
# AC2 — El contenido generado corresponde únicamente a información
# disponible en el contexto clínico proporcionado.
# ---------------------------------------------------------------------------
class TestContenidoLimitadoAlContexto:
    def test_contenido_con_fragmento_valido_se_acepta(self, consult_context):
        llm = ScriptedLLMClient(
            response_payload={"sections": [section("S", content="Dolor óseo.", source_span_ids=["seg-1"])]}
        )
        generator = ClinicalNoteGenerator(llm_client=llm)

        draft = generator.generate_draft(consult_context)

        s_section = draft.get_section("S")
        assert s_section.status == "documented"
        assert s_section.source_span_ids == ["seg-1"]

    def test_contenido_que_cita_fragmento_inexistente_se_descarta(self, consult_context):
        llm = ScriptedLLMClient(
            response_payload={
                "sections": [
                    section(
                        "S",
                        content="El paciente tiene metástasis cerebrales difusas.",
                        source_span_ids=["seg-no-existe"],
                    )
                ]
            }
        )
        generator = ClinicalNoteGenerator(llm_client=llm)

        draft = generator.generate_draft(consult_context)

        s_section = draft.get_section("S")
        assert s_section.status == "missing"
        assert s_section.content == MISSING_INFO_MARKER
        assert s_section.source_span_ids == []
        assert any("descartada" in w for w in draft.warnings)

    def test_contenido_sin_ninguna_referencia_se_descarta(self, consult_context):
        llm = ScriptedLLMClient(
            response_payload={"sections": [section("S", content="Dato clínico sin respaldo.", source_span_ids=[])]}
        )
        generator = ClinicalNoteGenerator(llm_client=llm)

        draft = generator.generate_draft(consult_context)

        assert draft.get_section("S").status == "missing"

    def test_referencias_parcialmente_invalidas_conservan_solo_las_validas(self, consult_context):
        llm = ScriptedLLMClient(
            response_payload={
                "sections": [
                    section(
                        "O",
                        content="Adenopatía axilar izquierda de 2 cm.",
                        source_span_ids=["seg-2", "seg-inventado"],
                    )
                ]
            }
        )
        generator = ClinicalNoteGenerator(llm_client=llm)

        draft = generator.generate_draft(consult_context)

        o_section = draft.get_section("O")
        assert o_section.status == "documented"
        assert o_section.source_span_ids == ["seg-2"]
        assert any("fragmentos inexistentes" in w for w in draft.warnings)

    def test_baja_cobertura_lexica_queda_advertida_no_oculta(self, consult_context):
        # Contenido "documentado" y con una referencia válida, pero cuyo
        # vocabulario casi no aparece en el fragmento citado: no se
        # descarta (podría ser una paráfrasis legítima), pero se marca
        # explícitamente para refuerzo de revisión manual.
        llm = ScriptedLLMClient(
            response_payload={
                "sections": [
                    section(
                        "A",
                        content="Sospecha firme de recaída ganglionar bilateral extensa con compromiso hepático.",
                        source_span_ids=["seg-2"],
                    )
                ]
            }
        )
        generator = ClinicalNoteGenerator(llm_client=llm, min_lexical_grounding=0.5)

        draft = generator.generate_draft(consult_context)

        a_section = draft.get_section("A")
        assert a_section.status == "documented"
        assert any("cobertura léxica" in w for w in draft.warnings)


# ---------------------------------------------------------------------------
# AC3 — Si falta información necesaria para una sección, el sistema no
# inventa información clínica para completarla.
# ---------------------------------------------------------------------------
class TestNoInventaInformacionFaltante:
    def test_seccion_marcada_missing_usa_el_marcador_fijo(self, consult_context):
        llm = ScriptedLLMClient(response_payload={"sections": [section("P", status="missing")]})
        generator = ClinicalNoteGenerator(llm_client=llm)

        draft = generator.generate_draft(consult_context)

        p_section = draft.get_section("P")
        assert p_section.status == "missing"
        assert p_section.content == MISSING_INFO_MARKER

    def test_seccion_omitida_por_el_modelo_tambien_queda_marcada(self, consult_context):
        # El modelo ni siquiera devuelve la sección "P": se trata igual
        # que si la hubiera marcado como faltante.
        llm = ScriptedLLMClient(
            response_payload={
                "sections": [
                    section("S", content="Dolor óseo.", source_span_ids=["seg-1"]),
                ]
            }
        )
        generator = ClinicalNoteGenerator(llm_client=llm)

        draft = generator.generate_draft(consult_context)

        assert draft.get_section("P").content == MISSING_INFO_MARKER
        assert draft.get_section("O").content == MISSING_INFO_MARKER

    def test_modelo_marca_missing_pero_intenta_rellenar_contenido_se_ignora(self, consult_context):
        # Aunque el modelo, incorrectamente, ponga texto en 'content' al
        # marcar la sección como "missing", ese texto nunca llega al
        # borrador: se fuerza el marcador fijo.
        llm = ScriptedLLMClient(
            response_payload={
                "sections": [
                    section(
                        "O",
                        status="missing",
                        content="Probablemente signos de derrame pleural bilateral.",
                        source_span_ids=["seg-2"],
                    )
                ]
            }
        )
        generator = ClinicalNoteGenerator(llm_client=llm)

        draft = generator.generate_draft(consult_context)

        o_section = draft.get_section("O")
        assert o_section.content == MISSING_INFO_MARKER
        assert "derrame pleural" not in o_section.content

    def test_respuesta_json_invalida_no_se_interpreta_a_ciegas(self, consult_context):
        llm = ScriptedLLMClient(raw_response="esto no es json")
        generator = ClinicalNoteGenerator(llm_client=llm)

        with pytest.raises(GenerationError):
            generator.generate_draft(consult_context)


# ---------------------------------------------------------------------------
# AC4 — El resultado queda identificado explícitamente como un borrador
# generado por IA.
# ---------------------------------------------------------------------------
class TestBorradorIdentificadoComoGeneradoPorIA:
    def test_draft_expone_bandera_y_disclaimer(self, consult_context):
        llm = ScriptedLLMClient(response_payload={"sections": []})
        generator = ClinicalNoteGenerator(llm_client=llm)

        draft = generator.generate_draft(consult_context)

        assert draft.is_ai_generated_draft is True
        assert "BORRADOR" in draft.disclaimer
        assert "IA" in draft.disclaimer
        assert draft.status == "borrador_ia_no_confirmado"

    def test_no_existe_forma_de_marcar_el_borrador_como_oficial(self, consult_context):
        llm = ScriptedLLMClient(response_payload={"sections": []})
        generator = ClinicalNoteGenerator(llm_client=llm)
        draft = generator.generate_draft(consult_context)

        # No debe existir ningún método para "firmar"/"finalizar" en este
        # alcance (IA-02): esa responsabilidad es de una historia
        # posterior de aprobación explícita por el oncólogo.
        assert not hasattr(draft, "finalize")
        assert not hasattr(draft, "sign")
        assert not hasattr(draft, "mark_as_official")

    def test_texto_renderizado_incluye_el_aviso_de_ia_al_inicio(self, consult_context):
        llm = ScriptedLLMClient(
            response_payload={"sections": [section("S", content="Dolor óseo.", source_span_ids=["seg-1"])]}
        )
        generator = ClinicalNoteGenerator(llm_client=llm)
        draft = generator.generate_draft(consult_context)

        text = draft.to_text()
        assert text.startswith("*** BORRADOR GENERADO AUTOMÁTICAMENTE POR IA")

    def test_to_dict_conserva_trazabilidad_entrada_salida(self, consult_context):
        llm = ScriptedLLMClient(
            response_payload={"sections": [section("S", content="Dolor óseo.", source_span_ids=["seg-1"])]}
        )
        generator = ClinicalNoteGenerator(llm_client=llm)
        draft = generator.generate_draft(consult_context)

        payload = draft.to_dict()
        assert payload["is_ai_generated_draft"] is True
        assert payload["traceability"]["S"] == ["seg-1"]
