"""IA-06 — El asistente pide aclaración ante consultas clínicas ambiguas."""

from clinical_query import (
    AmbiguityKind,
    Clarification,
    SQLiteClinicalRepository,
    NaturalLanguageClinicalQueryService,
)
from expediente.db import crear_conexion
from tests.datos_sinteticos import sembrar_datos_sinteticos


def build_service():
    conn = crear_conexion()
    ids = sembrar_datos_sinteticos(conn)
    service = NaturalLanguageClinicalQueryService(SQLiteClinicalRepository(conn))
    return conn, ids, service


def test_ambiguous_data_point_asks_for_clarification():
    conn, ids, service = build_service()
    try:
        response = service.ask(
            str(ids["paciente_maria"]),
            "¿Cuál es el valor de hemoglobina o de creatinina?",
        )
        assert response.needs_clarification is True
        assert response.found is False
        assert response.datum is None
        assert response.ambiguities[0].kind is AmbiguityKind.DATA_POINT
        assert set(response.ambiguities[0].options) == {"hemoglobina", "creatinina"}
    finally:
        conn.close()


def test_ambiguous_episode_asks_which_one():
    conn, ids, service = build_service()
    try:
        # Diana tiene hemoglobina registrada en dos consultas distintas.
        response = service.ask(str(ids["paciente_diana"]), "¿Cuál es la hemoglobina?")
        assert response.needs_clarification is True
        assert response.datum is None
        assert response.ambiguities[0].kind is AmbiguityKind.EPISODE
        assert len(response.ambiguities[0].options) == 2
    finally:
        conn.close()


def test_temporal_qualifier_resolves_episode_without_asking():
    conn, ids, service = build_service()
    try:
        response = service.ask(str(ids["paciente_diana"]), "¿Cuál es la última hemoglobina?")
        assert response.needs_clarification is False
        assert response.found is True
        assert response.datum.value == "11.6"
        assert response.datum.episode_id == f"consulta-{ids['consulta_diana_2']}"
    finally:
        conn.close()


def test_query_naming_another_patient_does_not_leak_and_asks_clarification():
    conn, ids, service = build_service()
    try:
        response = service.ask(str(ids["paciente_maria"]), "¿Cuál es el EGFR de Carlos?")
        assert response.needs_clarification is True
        assert response.found is False
        assert response.datum is None
        assert response.ambiguities[0].kind is AmbiguityKind.PATIENT
    finally:
        conn.close()


def test_clarification_round_trip_answers_within_clarified_context():
    conn, ids, service = build_service()
    try:
        first = service.ask(str(ids["paciente_diana"]), "¿Cuál es la hemoglobina?")
        assert first.needs_clarification is True

        resolved = service.ask(
            str(ids["paciente_diana"]),
            "¿Cuál es la hemoglobina?",
            clarification=Clarification(episode_id=f"consulta-{ids['consulta_diana_1']}"),
        )
        assert resolved.found is True
        assert resolved.datum.value == "13.1"
        assert resolved.datum.source_id == f"lab-{ids['lab_diana_hb_1']}"
    finally:
        conn.close()


def test_confirming_active_patient_allows_the_answer():
    conn, ids, service = build_service()
    try:
        response = service.ask(
            str(ids["paciente_carlos"]),
            "¿Cuál es el EGFR de Carlos más reciente?",
            clarification=Clarification(confirm_active_patient=True),
        )
        assert response.found is True
        assert "positivo (exón 19)" in response.answer
    finally:
        conn.close()


def test_nombres_genericos_de_cbioportal_no_generan_ambiguedad_de_paciente():
    """Con pacientes reales de cBioPortal los nombres son genéricos
    ("Paciente P-0000012 (cBioPortal msk_chord_2024)"): la palabra
    "paciente" no debe hacer creer que se nombra a otro paciente."""
    from clinical_query.ambiguity import nombra_otro_paciente
    from clinical_query.repository import PacienteRef

    directorio = [
        PacienteRef(id=str(i), nombre=f"Paciente P-000000{i} (cBioPortal msk_chord_2024)",
                    identificacion=f"CBIO:msk_chord_2024:P-000000{i}")
        for i in (1, 2)
    ]
    assert nombra_otro_paciente("¿Cuál es el CEA del paciente?", directorio, "1") is None
    assert nombra_otro_paciente("¿Qué dice cBioPortal del KRAS?", directorio, "1") is None
    assert nombra_otro_paciente("¿Cuál es el KRAS del paciente P-0000001?", directorio, "1") is None
    hallazgo = nombra_otro_paciente("¿Cuál es el KRAS de P-0000002?", directorio, "1")
    assert hallazgo is not None and hallazgo.options == ("Paciente P-0000002 (cBioPortal msk_chord_2024)",)
