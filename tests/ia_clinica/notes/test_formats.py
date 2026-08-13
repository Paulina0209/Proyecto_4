import pytest

from ia_clinica.notes.formats import NoteFormatSpec, NoteSectionSpec, SOAP_FORMAT, get_format


def test_soap_format_tiene_las_cuatro_secciones_clasicas():
    assert SOAP_FORMAT.section_keys() == ("S", "O", "A", "P")


def test_get_format_soap_por_defecto():
    assert get_format() is SOAP_FORMAT
    assert get_format("SOAP") is SOAP_FORMAT


def test_get_format_institucional_tiene_prioridad_sobre_default():
    custom_soap = NoteFormatSpec(name="SOAP", sections=(NoteSectionSpec(key="X", label="X", guidance="g"),))
    resolved = get_format("SOAP", institution_formats={"SOAP": custom_soap})
    assert resolved is custom_soap


def test_get_format_formato_no_registrado_lanza_error():
    with pytest.raises(ValueError):
        get_format("FORMATO_INEXISTENTE")


def test_note_format_spec_rechaza_secciones_vacias():
    with pytest.raises(ValueError):
        NoteFormatSpec(name="VACIO", sections=())


def test_note_format_spec_rechaza_claves_duplicadas():
    with pytest.raises(ValueError):
        NoteFormatSpec(
            name="DUP",
            sections=(
                NoteSectionSpec(key="X", label="Uno", guidance="g"),
                NoteSectionSpec(key="X", label="Dos", guidance="g"),
            ),
        )
