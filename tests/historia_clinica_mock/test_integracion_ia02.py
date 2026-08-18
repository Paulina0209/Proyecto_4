"""Prueba de integración: base de datos mock -> IA-02, de punta a punta.

Complementa (no repite) las pruebas de aceptación de IA-02 en
``tests/ia_clinica/notes/test_generator.py``: aquí el ``ClinicalContext``
no se construye a mano en la prueba, sino a través del adaptador real
sobre datos sembrados en una base de datos SQLite, para demostrar que la
integración completa funciona, no solo cada pieza por separado.
"""

from ia_clinica.notes.generator import ClinicalNoteGenerator
from ia_clinica.notes.llm_client import RuleBasedLLMClient
from ia_clinica.notes.models import MISSING_INFO_MARKER

from historia_clinica_mock.adapters import construir_contexto_clinico


def _generar(conn, consulta_id):
    context = construir_contexto_clinico(conn, consulta_id)
    return ClinicalNoteGenerator(llm_client=RuleBasedLLMClient()).generate_draft(context)


def test_consulta_con_datos_completos_produce_borrador_documentado(conn_sembrada):
    conn, ids = conn_sembrada
    draft = _generar(conn, ids["consulta_maria_1"])

    assert draft.is_ai_generated_draft is True
    # El objetivo debe incluir el laboratorio y la imagen de esa consulta.
    objetivo_ids = set(draft.get_section("O").source_span_ids)
    assert f"lab-{ids['lab_maria_1']}" in objetivo_ids
    assert f"imagen-{ids['imagen_maria_1']}" in objetivo_ids


def test_consulta_sin_labs_ni_imagenes_no_inventa_esas_secciones(conn_sembrada):
    conn, ids = conn_sembrada
    draft = _generar(conn, ids["consulta_maria_2"])

    # Esta consulta no tiene laboratorio ni imagenología vinculados en la
    # base de datos: el borrador debe decirlo explícitamente, nunca
    # inventar un hallazgo de examen físico o un resultado de laboratorio.
    assert draft.get_section("O").status == "missing"
    assert draft.get_section("O").content == MISSING_INFO_MARKER


def test_borrador_de_paciente_distinto_no_mezcla_datos_de_otro_paciente(conn_sembrada):
    conn, ids = conn_sembrada
    draft_maria = _generar(conn, ids["consulta_maria_1"])
    draft_carlos = _generar(conn, ids["consulta_carlos_1"])

    assert draft_maria.patient_ref != draft_carlos.patient_ref
    texto_carlos = draft_carlos.to_text()
    assert "HER2" not in texto_carlos  # biomarcador de María no debe aparecer en la nota de Carlos
    assert "EGFR" in texto_carlos
