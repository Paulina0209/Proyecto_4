"""Prueba de integración end-to-end usando el cliente de referencia.

Este es el único cliente LLM real (aunque no basado en un modelo de
lenguaje) que este módulo instancia por defecto. Sirve para demostrar que
todo el flujo (contexto -> generador -> borrador) funciona sin llaves de
API ni proveedor externo, y que como copia literalmente los fragmentos de
origen, su salida está garantizada como trazable.
"""

from ia_clinica.notes.generator import ClinicalNoteGenerator
from ia_clinica.notes.llm_client import RuleBasedLLMClient
from ia_clinica.notes.models import MISSING_INFO_MARKER, ClinicalContext, SourceSpan


def test_flujo_completo_sin_proveedor_externo():
    context = ClinicalContext(
        consult_id="consulta-002",
        patient_ref="paciente-456",
        segments=[
            SourceSpan(id="s1", text="La paciente refiere dolor lumbar de dos semanas de evolución."),
            SourceSpan(id="s2", text="Examen físico sin hallazgos relevantes; signos vitales estables."),
            SourceSpan(id="s3", text="Impresión diagnóstica: dolor lumbar mecánico, sin datos de alarma."),
            # Nótese: no hay ningún fragmento de tipo "plan" en esta consulta.
        ],
    )
    generator = ClinicalNoteGenerator(llm_client=RuleBasedLLMClient())

    draft = generator.generate_draft(context)

    assert draft.is_ai_generated_draft is True
    assert draft.get_section("S").status == "documented"
    assert draft.get_section("O").status == "documented"
    assert draft.get_section("A").status == "documented"
    # No se mencionó ningún plan durante la consulta: la sección debe
    # quedar marcada como faltante, nunca inventada.
    assert draft.get_section("P").status == "missing"
    assert draft.get_section("P").content == MISSING_INFO_MARKER

    # Toda sección documentada debe poder trazarse a un fragmento real.
    for section in draft.sections:
        if section.status == "documented":
            for span_id in section.source_span_ids:
                assert context.get_segment(span_id) is not None
                assert context.get_segment(span_id).text in section.content
