from pathlib import Path

from clinical_query import JsonClinicalRepository, NaturalLanguageClinicalQueryService


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "clinical_query" / "sample_patients.json"


def build_service() -> NaturalLanguageClinicalQueryService:
    return NaturalLanguageClinicalQueryService(JsonClinicalRepository(DATA))


def test_existing_data_includes_value_source_and_date() -> None:
    response = build_service().ask("PSEUDO-001", "¿Cuál fue el último CA-125?")

    assert response.found is True
    assert "31 U/mL" in response.answer
    assert "2026-07-22" in response.answer
    assert "Laboratorio institucional" in response.answer
    assert "LAB-2026-019" in response.answer


def test_latest_record_is_selected_chronologically() -> None:
    response = build_service().ask("PSEUDO-001", "Dime el CA 125 más reciente")

    assert response.datum is not None
    assert response.datum.value == "31"
    assert response.datum.source_id == "LAB-2026-019"


def test_missing_known_data_is_explicit_and_not_inferred() -> None:
    response = build_service().ask("PSEUDO-001", "¿Cuál es el último PSA?")

    assert response.found is False
    assert response.concept == "psa"
    assert "No hay información" in response.answer
    assert "No se infirió ni se inventó ningún valor" in response.answer


def test_every_returned_value_is_traceable_to_a_specific_source() -> None:
    response = build_service().ask("PSEUDO-001", "¿Cuál es la hemoglobina?")

    assert response.found is True
    assert response.datum is not None
    assert response.datum.source == "Hemograma"
    assert response.datum.source_id == "HEM-2026-019"
    assert response.datum.observed_at.isoformat() == "2026-07-22T09:10:00"


def test_unknown_question_does_not_generate_a_clinical_value() -> None:
    response = build_service().ask("PSEUDO-001", "¿Cómo está el paciente?")

    assert response.found is False
    assert response.datum is None
    assert "No pude identificar de forma segura" in response.answer


def test_patient_isolation_prevents_cross_patient_lookup() -> None:
    response = build_service().ask("PSEUDO-999", "¿Cuál es la creatinina?")

    assert response.found is False
    assert response.datum is None
    assert "No hay información" in response.answer
