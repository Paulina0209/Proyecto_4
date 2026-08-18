from evidencia_clinica import EvidenceSearchService
from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.repository import obtener_paciente
from historia_clinica_mock.seed import sembrar_datos_sinteticos


def test_free_search_returns_relevant_source_and_publication_date():
    service = EvidenceSearchService()
    results = service.search('EGFR NSCLC metastatic')
    assert results
    top = results[0].document
    assert 'nsclc' in top.module_id.lower()
    assert top.title
    assert top.publication_date
    assert top.source_path.startswith('guidelines/')


def test_breast_query_finds_breast_guideline():
    service = EvidenceSearchService()
    results = service.search('triple negative breast pembrolizumab')
    assert results
    assert 'breast' in results[0].document.module_id


def test_search_for_patient_is_scoped_to_clinical_context():
    conn = crear_conexion()
    sembrar_datos_sinteticos(conn)
    maria = obtener_paciente(conn, 1)
    assert maria is not None

    service = EvidenceSearchService()
    results = service.search_for_patient(maria, ['HER2', 'pembrolizumab'])
    assert results
    assert 'breast' in results[0].document.module_id
    conn.close()


def test_no_match_returns_empty_list_instead_of_inventing_evidence():
    service = EvidenceSearchService()
    assert service.search('zzzxxyy nonexistent evidence term') == []


def test_results_expose_licensing_status_for_regulatory_awareness():
    service = EvidenceSearchService()
    results = service.search('melanoma')
    assert results
    assert results[0].document.licensing_status is not None
