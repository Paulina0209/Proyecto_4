"""IA-06 — El asistente pide aclaración ante consultas clínicas ambiguas."""

from clinical_query import (
    AmbiguityKind,
    Clarification,
    MockSQLiteClinicalRepository,
    NaturalLanguageClinicalQueryService,
)
from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.seed import sembrar_datos_sinteticos


def build_service():
    conn = crear_conexion()
    ids = sembrar_datos_sinteticos(conn)
    service = NaturalLanguageClinicalQueryService(MockSQLiteClinicalRepository(conn))
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
