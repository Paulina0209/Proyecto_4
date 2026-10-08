"""HC-04 — Integración de resultados de biopsias y biomarcadores."""

from datetime import date, timedelta

import pytest

from expediente.repository import biomarcadores_de_paciente
from historia_clinica.biopsias_biomarcadores import (
    ACCIONABLE_CONFIRMADO,
    DESCARTADO,
    INFORMATIVO,
    PENDIENTE_CONFIRMACION,
    ErrorBiomarcador,
    ErrorConfiguracionBiomarcadores,
    biomarcadores_clave,
    biopsias_de_paciente,
    cargar_catalogo,
    confirmar_biomarcador,
    descartar_biomarcador,
    marcar_potencialmente_accionables,
    registrar_biomarcador,
    registrar_biopsia,
    registrar_episodio,
    validar_catalogo,
    variables_de_guias,
)
from historia_clinica.informacion_faltante import evaluar_informacion_faltante
from tx_clinica.patient_facts import construir_facts_paciente

from .conftest import insertar_biomarcador, insertar_dato, insertar_paciente

FECHA = date(2026, 2, 1)


@pytest.fixture
def paciente(conn):
    return insertar_paciente(conn, identificacion="EXT-1")


def _episodio(conn, paciente_id, tipo="NSCLC", descripcion="Adenocarcinoma de pulmón"):
    return registrar_episodio(conn, paciente_id, descripcion, tipo, FECHA - timedelta(days=10))


def _biopsia(conn, paciente_id, episodio_id=None):
    return registrar_biopsia(
        conn, paciente_id, fecha=FECHA, sitio="Lóbulo inferior derecho", procedimiento="Biopsia con aguja gruesa",
        diagnostico_histologico="Adenocarcinoma", episodio_id=episodio_id,
    )


def _biomarcador(conn, paciente_id, biopsia_id, biomarcador="EGFR", estado="detectada", confirmacion=None,
                 metodo="NGS", **kw):
    return registrar_biomarcador(
        conn, paciente_id, biopsia_id=biopsia_id, biomarcador=biomarcador, estado=estado,
        confirmacion=estado if confirmacion is None else confirmacion, metodo=metodo, **kw,
    )


# --- AC1: biopsia vinculada al episodio diagnóstico -------------------------


def test_con_un_solo_episodio_la_biopsia_se_vincula_sola(conn, paciente):
    episodio = _episodio(conn, paciente)

    biopsia = _biopsia(conn, paciente)

    assert biopsia.episodio_id == episodio.id
    assert biopsias_de_paciente(conn, paciente) == [biopsia]


def test_sin_episodio_no_se_puede_registrar_la_biopsia(conn, paciente):
    with pytest.raises(ErrorBiomarcador) as error:
        _biopsia(conn, paciente)
    assert error.value.errores[0][0] == "episodio_id"
    assert biopsias_de_paciente(conn, paciente) == []


def test_con_varios_episodios_hay_que_indicar_cual(conn, paciente):
    _episodio(conn, paciente)
    segundo = _episodio(conn, paciente, tipo="breast", descripcion="Carcinoma ductal de mama")

    with pytest.raises(ErrorBiomarcador, match="2 episodios"):
        _biopsia(conn, paciente)
    assert _biopsia(conn, paciente, episodio_id=segundo.id).episodio_id == segundo.id


def test_no_se_vincula_a_un_episodio_de_otro_paciente(conn, paciente):
    otro = insertar_paciente(conn, identificacion="EXT-2")
    ajeno = _episodio(conn, otro)
    _episodio(conn, paciente)

    with pytest.raises(ErrorBiomarcador):
        _biopsia(conn, paciente, episodio_id=ajeno.id)


def test_biopsia_incompleta_o_futura_se_rechaza_con_todos_los_errores(conn, paciente):
    _episodio(conn, paciente)
    with pytest.raises(ErrorBiomarcador) as error:
        registrar_biopsia(conn, paciente, fecha=date.today() + timedelta(days=1), sitio=" ", procedimiento="")
    assert {c for c, _ in error.value.errores} == {"sitio", "procedimiento", "fecha"}


# --- AC2: biomarcador accionable -> información clave + insumo de TX-01 ------


def test_egfr_sensibilizante_se_destaca_y_llega_a_tx(conn, paciente):
    _episodio(conn, paciente)
    biopsia = _biopsia(conn, paciente)

    registrado = _biomarcador(conn, paciente, biopsia.id, variante="L858R")

    assert registrado.relevancia == ACCIONABLE_CONFIRMADO
    assert "EGFR" in registrado.terapia_asociada
    assert (registrado.variable_tx, registrado.valor_tx) == ("egfr_status", "sensitizing_mutation")
    assert [b.biomarcador_id for b in biomarcadores_clave(conn, paciente)] == [registrado.biomarcador_id]
    assert registrado.episodio_id == biopsia.episodio_id
    assert construir_facts_paciente(conn, paciente)["egfr_status"] == "sensitizing_mutation"


@pytest.mark.parametrize("variante", ["E746_A750del", "exon 19 deletion", "L747_P753delinsS"])
def test_deleciones_del_exon_19_son_sensibilizantes(conn, paciente, variante):
    _episodio(conn, paciente)
    registrado = _biomarcador(conn, paciente, _biopsia(conn, paciente).id, variante=variante)
    assert registrado.valor_tx == "sensitizing_mutation"


def test_variante_no_catalogada_queda_informativa_sin_variable(conn, paciente):
    _episodio(conn, paciente)

    registrado = _biomarcador(conn, paciente, _biopsia(conn, paciente).id, variante="T790M")

    assert registrado.relevancia == INFORMATIVO
    assert registrado.variable_tx is None
    assert biomarcadores_clave(conn, paciente) == []
    assert "egfr_status" not in construir_facts_paciente(conn, paciente)


def test_resultado_negativo_tambien_es_insumo_de_tx(conn, paciente):
    _episodio(conn, paciente)

    registrado = _biomarcador(conn, paciente, _biopsia(conn, paciente).id, estado="no_detectada")

    assert registrado.relevancia == INFORMATIVO
    assert construir_facts_paciente(conn, paciente)["egfr_status"] == "wild_type"


def test_otro_tipo_de_cancer_no_es_accionable(conn, paciente):
    registrar_episodio(conn, paciente, "Carcinoma ductal de mama", "breast")

    registrado = _biomarcador(conn, paciente, _biopsia(conn, paciente).id, variante="L858R")

    assert registrado.relevancia == INFORMATIVO
    assert registrado.variable_tx is None


def test_sin_tipo_de_cancer_conocido_no_se_afirma_accionabilidad(conn, paciente):
    registrar_episodio(conn, paciente, "Tumor en estudio")

    assert _biomarcador(conn, paciente, _biopsia(conn, paciente).id, variante="L858R").relevancia == INFORMATIVO


def test_el_tipo_de_cancer_puede_venir_del_expediente(conn, paciente):
    registrar_episodio(conn, paciente, "Tumor en estudio")
    insertar_dato(conn, paciente, "cancer_type", "NSCLC")

    assert _biomarcador(conn, paciente, _biopsia(conn, paciente).id, variante="L858R").relevancia == ACCIONABLE_CONFIRMADO


def test_alk_reordenado(conn, paciente):
    _episodio(conn, paciente)

    registrado = _biomarcador(conn, paciente, _biopsia(conn, paciente).id, biomarcador="alk", estado="reordenado", metodo="fish")

    assert (registrado.metodo, registrado.variable_tx, registrado.valor_tx) == ("FISH", "alk_status", "rearranged")


def test_pdl1_tps_pasa_su_valor_a_tx(conn, paciente):
    _episodio(conn, paciente)

    registrado = _biomarcador(conn, paciente, _biopsia(conn, paciente).id, biomarcador="PD-L1", estado="cuantificado",
                              confirmacion="60", metodo="22C3", valor=60)

    assert registrado.resultado == "60 % (22C3)"
    assert construir_facts_paciente(conn, paciente)["pdl1_tps"] == 60


def test_her2_positivo_en_mama(conn, paciente):
    registrar_episodio(conn, paciente, "Carcinoma ductal de mama", "breast")

    registrado = _biomarcador(conn, paciente, _biopsia(conn, paciente).id, biomarcador="HER2", estado="positivo",
                              metodo="IHC", ihc_score="3+")

    assert registrado.resultado == "positivo (IHC 3+, IHC)"
    assert construir_facts_paciente(conn, paciente)["her2_status"] == "positive"


def test_el_texto_legible_cuenta_para_hc05(conn, paciente):
    _episodio(conn, paciente)
    insertar_dato(conn, paciente, "cancer_type", "NSCLC")
    biopsia = _biopsia(conn, paciente)
    _biomarcador(conn, paciente, biopsia.id, biomarcador="ALK", estado="no_concluyente", metodo="IHC")

    evaluacion = evaluar_informacion_faltante(conn, paciente, fases=["tratamiento"])

    alk = next(i for i in evaluacion.faltantes if i.id == "alk")
    assert alk.motivo == "valor no concluyente"


# --- Validación estricta (riesgo de la historia) -----------------------------


@pytest.mark.parametrize(
    ("datos", "campo"),
    [
        (dict(biomarcador="HER2", estado="negativo", metodo="IHC", ihc_score="3+"), "estado"),  # invertido
        (dict(biomarcador="HER2", estado="positivo", metodo="IHC", ihc_score="1+"), "estado"),
        (dict(biomarcador="HER2", estado="positivo", metodo="IHC", ihc_score="2+"), "estado"),  # 2+ sin ISH: equívoco
        (dict(biomarcador="HER2", estado="positivo", metodo="IHC"), "ihc_score"),
        (dict(biomarcador="HER2", estado="positivo", metodo="IHC", ihc_score="4+"), "ihc_score"),
        (dict(biomarcador="PD-L1", estado="cuantificado", confirmacion="120", metodo="22C3", valor=120), "valor"),
        (dict(biomarcador="PD-L1", estado="cuantificado", confirmacion="", metodo="22C3"), "valor"),
        (dict(biomarcador="RE", estado="negativo", metodo="IHC", valor=40), "estado"),  # 40 % es positivo
        (dict(biomarcador="EGFR", estado="detectada", metodo="NGS"), "variante"),  # falta la variante
        (dict(biomarcador="EGFR", estado="positivo", metodo="NGS", variante="L858R"), "estado"),  # estado de otro formato
        (dict(biomarcador="EGFR", estado="levemente positivo", metodo="NGS"), "estado"),  # texto libre
        (dict(biomarcador="EGFR", estado="detectada", metodo="intuición", variante="L858R"), "metodo"),
        (dict(biomarcador="EGFR", estado="detectada", confirmacion="no_detectada", metodo="NGS", variante="L858R"), "confirmacion"),
        (dict(biomarcador="Ki-67", estado="positivo", metodo="IHC"), "biomarcador"),  # fuera del catálogo
    ],
)
def test_validacion_estricta(conn, paciente, datos, campo):
    _episodio(conn, paciente)
    biopsia = _biopsia(conn, paciente)

    with pytest.raises(ErrorBiomarcador) as error:
        _biomarcador(conn, paciente, biopsia.id, **datos)

    assert campo in {c for c, _ in error.value.errores}
    assert biomarcadores_de_paciente(conn, paciente) == []
    assert "egfr_status" not in construir_facts_paciente(conn, paciente)


@pytest.mark.parametrize(
    ("ihc", "ish", "estado"),
    [("2+", "amplificado", "positivo"), ("2+", "no_amplificado", "negativo"), ("2+", None, "equivoco"), ("0", None, "negativo")],
)
def test_her2_coherente_con_ihc_e_ish(conn, paciente, ihc, ish, estado):
    registrar_episodio(conn, paciente, "Carcinoma ductal de mama", "breast")
    registrado = _biomarcador(conn, paciente, _biopsia(conn, paciente).id, biomarcador="HER2", estado=estado,
                              metodo="IHC", ihc_score=ihc, ish=ish)
    esperado = {"positivo": "positive", "negativo": "negative", "equivoco": "equivocal"}[estado]
    assert construir_facts_paciente(conn, paciente)["her2_status"] == esperado
    assert registrado.estado == estado


def test_biopsia_de_otro_paciente_se_rechaza(conn, paciente):
    otro = insertar_paciente(conn, identificacion="EXT-2")
    _episodio(conn, otro)
    ajena = _biopsia(conn, otro)

    with pytest.raises(ErrorBiomarcador):
        _biomarcador(conn, paciente, ajena.id, variante="L858R")


# --- Biomarcadores importados: pendientes de confirmación --------------------


def _importado(conn, paciente_id, nombre="ALK", resultado="fusión detectada: EML4-ALK (Protein fusion: in frame) — muestra S1"):
    insertar_dato(conn, paciente_id, "cancer_type", "NSCLC")
    insertar_biomarcador(conn, paciente_id, nombre, resultado)
    return marcar_potencialmente_accionables(conn, paciente_id)


def test_importado_accionable_queda_pendiente_sin_variable_de_tx(conn, paciente):
    (biomarcador_id,) = _importado(conn, paciente)

    (clave,) = biomarcadores_clave(conn, paciente)
    assert (clave.biomarcador_id, clave.relevancia, clave.variante) == (biomarcador_id, PENDIENTE_CONFIRMACION, "EML4-ALK")
    assert "alk_status" not in construir_facts_paciente(conn, paciente)


def test_confirmar_un_pendiente_lo_pasa_a_tx(conn, paciente):
    (biomarcador_id,) = _importado(conn, paciente)

    confirmado = confirmar_biomarcador(conn, paciente, biomarcador_id, "dra.ruiz", "reordenado")

    assert (confirmado.relevancia, confirmado.confirmado_por) == (ACCIONABLE_CONFIRMADO, "dra.ruiz")
    assert construir_facts_paciente(conn, paciente)["alk_status"] == "rearranged"
    with pytest.raises(ErrorBiomarcador):
        confirmar_biomarcador(conn, paciente, biomarcador_id, "dra.ruiz", "reordenado")


def test_confirmacion_distinta_no_confirma(conn, paciente):
    (biomarcador_id,) = _importado(conn, paciente)

    with pytest.raises(ErrorBiomarcador):
        confirmar_biomarcador(conn, paciente, biomarcador_id, "dra.ruiz", "no_reordenado")
    assert "alk_status" not in construir_facts_paciente(conn, paciente)


def test_descartar_un_pendiente(conn, paciente):
    (biomarcador_id,) = _importado(conn, paciente)

    assert descartar_biomarcador(conn, paciente, biomarcador_id, "dra.ruiz").relevancia == DESCARTADO
    assert biomarcadores_clave(conn, paciente) == []
    assert "alk_status" not in construir_facts_paciente(conn, paciente)


@pytest.mark.parametrize(
    ("nombre", "resultado"),
    [
        ("EGFR", "mutación detectada: V834L (Missense_Mutation) — muestra S1"),  # no sensibilizante
        ("EGFR", "mutación no detectada (panel IMPACT341) — muestra S1"),
        ("TMB", "7.8 mut/Mb — muestra S1"),  # fuera del catálogo
    ],
)
def test_importados_no_accionables_no_se_destacan(conn, paciente, nombre, resultado):
    assert _importado(conn, paciente, nombre, resultado) == []
    assert biomarcadores_clave(conn, paciente) == []


def test_marcar_es_idempotente(conn, paciente):
    _importado(conn, paciente)
    assert marcar_potencialmente_accionables(conn, paciente) == []
    assert len(biomarcadores_clave(conn, paciente)) == 1


# --- Catálogo -----------------------------------------------------------------


def test_el_catalogo_incluido_es_coherente_con_las_guias():
    catalogo = cargar_catalogo()
    assert {"EGFR", "ALK", "HER2", "PDL1_TPS", "BRAF"} <= set(catalogo)


@pytest.mark.parametrize(
    "cambio",
    [
        {"variable_tx": "egfr_estado_inventado", "valor_tx": "x"},  # variable que TX no conoce
        {"variable_tx": "egfr_status", "valor_tx": "positivo"},  # valor fuera de allowed_values
        {"variable_tx": "egfr_status"},  # sin valor
    ],
)
def test_catalogo_que_apunta_a_algo_que_tx_no_entiende_se_rechaza(cambio):
    regla = {"terapia": "Inhibidor", **cambio}
    datos = {"biomarcadores": {"EGFR": {
        "nombre": "EGFR", "alias": ["egfr"], "formato": "alteracion", "tipos_cancer": ["NSCLC"],
        "metodos": ["NGS"], "accionable": [regla],
    }}}
    with pytest.raises(ErrorConfiguracionBiomarcadores):
        validar_catalogo(datos, variables_de_guias())


def test_formato_desconocido_se_rechaza():
    datos = {"biomarcadores": {"X": {"nombre": "X", "alias": ["x"], "formato": "texto_libre", "tipos_cancer": ["NSCLC"],
                                      "metodos": ["NGS"], "accionable": [{"terapia": "t"}]}}}
    with pytest.raises(ErrorConfiguracionBiomarcadores):
        validar_catalogo(datos, variables_de_guias())
