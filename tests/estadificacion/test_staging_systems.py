"""EST-01 — Catálogo versionado de sistemas de estadificación."""

import pytest

from estadificacion.staging_systems import (
    CATALOGO_SISTEMAS,
    agrupar_estadio,
    familia_de_valor,
    sistema_para_cancer,
)


@pytest.mark.parametrize(
    "cancer_type",
    ["breast", "NSCLC", "melanoma", "renal_cell_carcinoma"],
)
def test_cada_cancer_del_mock_tiene_sistema(cancer_type):
    sistema = sistema_para_cancer(cancer_type)
    assert sistema is not None
    assert sistema.id and sistema.version
    assert sistema.fuente
    assert sistema.nota_alcance


def test_cancer_desconocido_no_devuelve_sistema():
    assert sistema_para_cancer("cáncer_inexistente") is None
    assert sistema_para_cancer(None) is None


def test_cada_sistema_declara_version_y_componentes_tnm():
    for sistema in CATALOGO_SISTEMAS:
        codigos = {c.codigo for c in sistema.componentes}
        assert codigos == {"T", "N", "M"}
        assert all(c.variable_expediente for c in sistema.componentes)


@pytest.mark.parametrize(
    "valor,esperado",
    [("cT2", "T2"), ("pT4b", "T4"), ("N0", "N0"), ("cM0", "M0"), ("M1", "M1"), ("desconocido", None)],
)
def test_familia_de_valor_normaliza_prefijos_y_sufijos(valor, esperado):
    assert familia_de_valor(valor) == esperado


def test_agrupar_estadio_usa_comodin_para_m1():
    sistema = sistema_para_cancer("breast")
    assert agrupar_estadio(sistema, "T1", "N0", "M1") == "IV"


def test_agrupar_estadio_devuelve_none_si_falta_componente():
    sistema = sistema_para_cancer("breast")
    assert agrupar_estadio(sistema, "T2", None, "M0") is None
