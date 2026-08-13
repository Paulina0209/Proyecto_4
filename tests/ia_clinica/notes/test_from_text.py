"""Pruebas de ClinicalContext.from_text: entrada como un solo párrafo libre.

Complementa AC1 de IA-02: el criterio de aceptación no exige que la
consulta llegue ya fragmentada por el usuario. Estas pruebas documentan
que un párrafo único también funciona, siempre que el texto pueda
separarse en oraciones razonablemente delimitadas.
"""

from ia_clinica.notes.generator import ClinicalNoteGenerator
from ia_clinica.notes.llm_client import RuleBasedLLMClient
from ia_clinica.notes.models import MISSING_INFO_MARKER, ClinicalContext

PARRAFO = (
    "Paciente de 45 años que refiere dolor óseo progresivo de tres semanas. "
    "Al examen físico se palpa adenopatía axilar izquierda de 2 cm. "
    "Impresión diagnóstica: progresión de enfermedad ósea metastásica. "
    "Plan: se solicita gammagrafía ósea y control en dos semanas."
)


def test_from_text_separa_el_parrafo_en_una_oracion_por_fragmento():
    context = ClinicalContext.from_text(consult_id="c-1", patient_ref="p-1", text=PARRAFO)

    assert len(context.segments) == 4
    assert [s.id for s in context.segments] == ["seg-1", "seg-2", "seg-3", "seg-4"]
    assert context.segments[0].text == "Paciente de 45 años que refiere dolor óseo progresivo de tres semanas."


def test_from_text_ignora_lineas_vacias():
    texto_con_saltos = "Primera línea.\n\nSegunda línea.\n"
    context = ClinicalContext.from_text(consult_id="c-1", patient_ref="p-1", text=texto_con_saltos)
    assert [s.text for s in context.segments] == ["Primera línea.", "Segunda línea."]


def test_generador_con_parrafo_unico_via_from_text_separa_las_secciones():
    context = ClinicalContext.from_text(consult_id="c-parrafo", patient_ref="p-1", text=PARRAFO)
    draft = ClinicalNoteGenerator(llm_client=RuleBasedLLMClient()).generate_draft(context)

    # Cada sección debe quedar con SU oración correspondiente, no con el
    # párrafo completo repetido en las cuatro secciones.
    assert draft.get_section("S").content == "Paciente de 45 años que refiere dolor óseo progresivo de tres semanas."
    assert draft.get_section("O").content == "Al examen físico se palpa adenopatía axilar izquierda de 2 cm."
    assert draft.get_section("A").content == "Impresión diagnóstica: progresión de enfermedad ósea metastásica."
    assert draft.get_section("P").content == "Plan: se solicita gammagrafía ósea y control en dos semanas."


def test_parrafo_sin_segmentar_con_cliente_de_referencia_no_separa_secciones():
    """Documenta la limitación del cliente de referencia con un bloque sin segmentar.

    RuleBasedLLMClient no es un LLM real: clasifica fragmentos completos,
    no oraciones dentro de ellos. Si se le da un único SourceSpan con todo
    el párrafo (sin usar from_text), el mismo bloque queda repetido en
    cada sección cuyas palabras clave aparezcan en él. Esta prueba fija
    esa limitación conocida para que no se rompa silenciosamente ni se
    confunda con un defecto del generador (que sí valida correctamente
    contra el fragmento citado).
    """
    from ia_clinica.notes.models import SourceSpan

    context = ClinicalContext(
        consult_id="c-parrafo-sin-segmentar",
        patient_ref="p-1",
        segments=[SourceSpan(id="unico", text=PARRAFO)],
    )
    draft = ClinicalNoteGenerator(llm_client=RuleBasedLLMClient()).generate_draft(context)

    documented = [s for s in draft.sections if s.status == "documented"]
    assert len(documented) >= 2
    # Limitación conocida: el mismo bloque completo aparece repetido.
    assert all(s.content == PARRAFO for s in documented)
    # Sigue siendo trazable (aunque a nivel de párrafo completo, no de oración).
    assert all(s.source_span_ids == ["unico"] for s in documented)
