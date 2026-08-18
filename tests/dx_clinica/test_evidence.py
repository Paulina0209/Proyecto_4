from dx_clinica.evidence import (
    catalogar_evidencia_desde_guias,
    evidencia_por_diagnostico_principal,
    obtener_evidencia,
)


def test_catalogo_carga_los_modulos_reales_de_guidelines():
    catalogo = catalogar_evidencia_desde_guias()
    assert "breast_early_tnbc" in catalogo
    assert "nsclc_metastatic_oncogene_addicted" in catalogo


def test_evidencia_de_un_modulo_conocido_trae_doi_real():
    evidencia = obtener_evidencia("breast_early_tnbc")
    assert evidencia is not None
    assert evidencia.organization == "ESMO"
    assert evidencia.doi == "10.1016/j.annonc.2023.11.016"
    assert evidencia.publication_year == 2024


def test_evidencia_incluye_estado_de_validacion_clinica_en_la_cita():
    evidencia = obtener_evidencia("breast_early_tnbc")
    cita = evidencia.resumen_citable()
    assert "pending" in cita
    assert "no se debe interpretar como evidencia clínicamente validada" in cita


def test_modulo_inexistente_devuelve_none():
    assert obtener_evidencia("modulo_que_no_existe") is None


def test_evidencia_por_diagnostico_principal_conocido():
    evidencia = evidencia_por_diagnostico_principal("Cáncer de mama triple negativo")
    assert evidencia is not None
    assert evidencia.module_id == "esmo_breast_early_tnbc"


def test_evidencia_por_diagnostico_desconocido_no_inventa_una_asociacion():
    assert evidencia_por_diagnostico_principal("Diagnóstico no registrado en la tabla") is None
    assert evidencia_por_diagnostico_principal(None) is None
