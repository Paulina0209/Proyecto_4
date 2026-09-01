"""EST-01 — Propuesta de estadificación a partir del expediente."""

from estadificacion.builder import proponer_estadificacion
from historia_clinica_mock.repository import datos_clinicos_estructurados_de_paciente


def _componente(propuesta, codigo):
    return next(c for c in propuesta.componentes if c.codigo == codigo)


def test_propone_componentes_tnm_para_paciente_con_datos_suficientes(conn_sembrada):
    conn, ids = conn_sembrada
    propuesta = proponer_estadificacion(conn, ids["paciente_maria"])

    codigos = {c.codigo for c in propuesta.componentes}
    assert codigos == {"T", "N", "M"}
    assert _componente(propuesta, "T").valor == "cT2"
    assert _componente(propuesta, "N").valor == "N0"
    assert _componente(propuesta, "M").valor == "cM0"
    assert propuesta.datos_faltantes == ()


def test_cada_componente_muestra_criterio_y_fundamento(conn_sembrada):
    conn, ids = conn_sembrada
    propuesta = proponer_estadificacion(conn, ids["paciente_maria"])

    for componente in propuesta.componentes:
        assert componente.criterio_aplicado.strip()
        assert componente.fundamento.strip()
        assert componente.fuente_ids


def test_presenta_estadio_global_cuando_los_componentes_lo_permiten(conn_sembrada):
    conn, ids = conn_sembrada
    propuesta = proponer_estadificacion(conn, ids["paciente_maria"])

    # breast cT2 N0 cM0 -> IIA en la tabla incluida (AJCC v8, anatómico).
    assert propuesta.estadio_global == "IIA"
    assert propuesta.esta_completa()
    assert "IIA" in propuesta.fundamento_global


def test_metastasis_a_distancia_produce_estadio_iv(conn_sembrada):
    conn, ids = conn_sembrada
    propuesta = proponer_estadificacion(conn, ids["paciente_roberto"])

    assert _componente(propuesta, "M").valor == "cM1"
    assert propuesta.estadio_global == "IV"


def test_la_propuesta_identifica_sistema_y_version(conn_sembrada):
    conn, ids = conn_sembrada
    propuesta = proponer_estadificacion(conn, ids["paciente_maria"])

    assert propuesta.sistema_id == "AJCC"
    assert propuesta.sistema_version == "8"
    assert propuesta.identificador_sistema() == "AJCC (v8)"
    assert propuesta.sistema_fuente


def test_datos_usados_son_trazables_al_expediente(conn_sembrada):
    conn, ids = conn_sembrada
    propuesta = proponer_estadificacion(conn, ids["paciente_maria"])

    ids_expediente = {
        f"dato-{d.id}"
        for d in datos_clinicos_estructurados_de_paciente(conn, ids["paciente_maria"])
    }
    for componente in propuesta.componentes:
        assert set(componente.fuente_ids) <= ids_expediente


def test_no_se_leen_variables_de_otro_sistema_ni_se_inventan_faltantes(conn_sembrada):
    conn, ids = conn_sembrada
    # Patricia (renal_cell_carcinoma) no tiene T/N/M estructurado en el seed.
    propuesta = proponer_estadificacion(conn, ids["paciente_patricia"])

    assert propuesta.sistema_id == "AJCC"
    assert set(propuesta.datos_faltantes) == {
        "clinical_t_category",
        "clinical_n_status",
        "clinical_m_status",
    }
    assert propuesta.estadio_global is None
    assert propuesta.componentes == ()


def test_sin_tipo_de_cancer_no_selecciona_sistema(conn_sembrada):
    conn, ids = conn_sembrada
    # Paciente inexistente: sin expediente, sin sistema.
    propuesta = proponer_estadificacion(conn, 9999)
    assert propuesta.sistema_id is None
    assert propuesta.estadio_global is None
