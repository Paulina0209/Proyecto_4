from clinical_query import MockSQLiteClinicalRepository, NaturalLanguageClinicalQueryService
from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.seed import sembrar_datos_sinteticos


def build_service():
    conn = crear_conexion()
    ids = sembrar_datos_sinteticos(conn)
    service = NaturalLanguageClinicalQueryService(MockSQLiteClinicalRepository(conn))
    return conn, ids, service


def test_maria_can_retrieve_her2_with_exact_provenance():
    conn, ids, service = build_service()
    try:
        response = service.ask(str(ids["paciente_maria"]), "¿Cuál fue el último HER2?")
        assert response.found is True
        assert response.datum is not None
        assert response.datum.value == "negativo"
        assert response.datum.source_id == f"biomarcador-{ids['biomarcador_maria_1']}"
        assert response.datum.observed_at.isoformat() == "2025-11-02T00:00:00"
    finally:
        conn.close()


def test_carlos_can_retrieve_egfr():
    conn, ids, service = build_service()
    try:
        response = service.ask(str(ids["paciente_carlos"]), "Muéstrame el EGFR más reciente")
        assert response.found is True
        assert "positivo (exón 19)" in response.answer
        assert response.datum is not None
        assert response.datum.source_id == f"biomarcador-{ids['biomarcador_carlos_1']}"
    finally:
        conn.close()


def test_maria_never_receives_carlos_egfr():
    conn, ids, service = build_service()
    try:
        response = service.ask(str(ids["paciente_maria"]), "¿Cuál es el EGFR?")
        assert response.found is False
        assert response.datum is None
        assert "No hay información" in response.answer
    finally:
        conn.close()


def test_carlos_never_receives_maria_her2():
    conn, ids, service = build_service()
    try:
        response = service.ask(str(ids["paciente_carlos"]), "¿Cuál es el HER2?")
        assert response.found is False
        assert response.datum is None
    finally:
        conn.close()


def test_laboratory_value_is_retrieved_from_mock():
    conn, ids, service = build_service()
    try:
        response = service.ask(str(ids["paciente_carlos"]), "¿Cuál fue la ALT más reciente?")
        assert response.found is True
        assert response.datum is not None
        assert response.datum.value == "78"
        assert response.datum.unit == "U/L"
        assert response.datum.source_id == f"lab-{ids['lab_carlos_1']}"
    finally:
        conn.close()


def test_unknown_patient_does_not_leak_data():
    conn, ids, service = build_service()
    try:
        response = service.ask("9999", "¿Cuál es el HER2?")
        assert response.found is False
        assert response.datum is None
    finally:
        conn.close()
