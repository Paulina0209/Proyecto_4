from historia_clinica_mock.adapters import obtener_hallazgos_de_paciente
from historia_clinica_mock.repository import obtener_paciente
from ia_clinica.explainability import PatientRecommendationService


def test_patient_recommendations_are_scoped_to_active_patient(conn_sembrada):
    conn_mock, seeded_ids = conn_sembrada
    maria = obtener_paciente(conn_mock, seeded_ids["paciente_maria"])
    carlos = obtener_paciente(conn_mock, seeded_ids["paciente_carlos"])

    # Deliberadamente mezclamos hallazgos de ambos para probar la defensa del servicio.
    mixed = (
        obtener_hallazgos_de_paciente(conn_mock, maria.id)
        + obtener_hallazgos_de_paciente(conn_mock, carlos.id)
    )

    result = PatientRecommendationService().for_patient(maria, mixed)

    assert result.patient_id == maria.id
    for explanation in result.explanations:
        for fact in explanation.patient_facts:
            # Los ids trazados deben existir dentro de los hallazgos de María.
            maria_ids = {h.id for h in obtener_hallazgos_de_paciente(conn_mock, maria.id)}
            assert fact.fact_id in maria_ids


def test_patient_recommendation_service_returns_explainable_outputs(conn_sembrada):
    conn_mock, seeded_ids = conn_sembrada
    maria = obtener_paciente(conn_mock, seeded_ids["paciente_maria"])
    hallazgos = obtener_hallazgos_de_paciente(conn_mock, maria.id)

    result = PatientRecommendationService().for_patient(maria, hallazgos)

    assert result.explanations
    first = result.explanations[0]
    assert first.recommendation
    assert first.rationale
    assert first.patient_facts
    assert first.source_component == "DX-02"
