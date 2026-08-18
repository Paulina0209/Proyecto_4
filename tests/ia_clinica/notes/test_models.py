import pytest

from ia_clinica.notes.models import ClinicalContext, SourceSpan


def test_source_span_requiere_texto_no_vacio():
    with pytest.raises(ValueError):
        SourceSpan(id="s1", text="   ")


def test_source_span_requiere_id_no_vacio():
    with pytest.raises(ValueError):
        SourceSpan(id="", text="algo")


def test_clinical_context_rechaza_ids_duplicados():
    with pytest.raises(ValueError):
        ClinicalContext(
            consult_id="c-1",
            patient_ref="p-1",
            segments=[SourceSpan(id="dup", text="a"), SourceSpan(id="dup", text="b")],
        )


def test_clinical_context_get_segment_y_full_text():
    context = ClinicalContext(
        consult_id="c-1",
        patient_ref="p-1",
        segments=[SourceSpan(id="a", text="uno"), SourceSpan(id="b", text="dos")],
    )
    assert context.get_segment("a").text == "uno"
    assert context.get_segment("no-existe") is None
    assert context.full_text() == "uno\ndos"
    assert context.is_empty() is False


def test_clinical_context_vacio():
    context = ClinicalContext(consult_id="c-1", patient_ref="p-1", segments=[])
    assert context.is_empty() is True
