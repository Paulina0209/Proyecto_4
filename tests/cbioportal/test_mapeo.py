"""Traducción de cBioPortal al expediente: reglas clínicas fail-closed."""

from types import SimpleNamespace

import pytest

from cbioportal.mapeo import calendario, ficha_paciente, identificacion_cbioportal, registros_desde_cbioportal
from historia_clinica.integracion_externa import PacienteNoCoincideError

from .conftest import ESTUDIO, FECHA_REFERENCIA


@pytest.fixture
def historia(fuente):
    return lambda paciente: fuente.historia(ESTUDIO, paciente)


def _registros(contenido):
    paciente = SimpleNamespace(identificacion=identificacion_cbioportal(ESTUDIO, contenido["paciente"]))
    registros, omitidos = registros_desde_cbioportal(contenido, paciente, FECHA_REFERENCIA)
    return registros, omitidos


def _filas(contenido, tabla):
    return [r.valores for r in _registros(contenido)[0] if r.tabla == tabla]


def _datos(contenido):
    return {v["variable"]: v["valor"] for v in _filas(contenido, "datos_clinicos_estructurados")}


def _biomarcadores(contenido):
    return {v["biomarcador"]: v["resultado"] for v in _filas(contenido, "biomarcadores")}


def test_el_ultimo_evento_cae_en_la_fecha_de_referencia_y_se_conservan_los_intervalos(historia):
    fecha = calendario(historia("P-0000015"), FECHA_REFERENCIA)
    assert fecha(415) == "2026-09-29"
    assert fecha(398) == "2026-09-12"


def test_ficha_del_paciente(historia):
    ficha = ficha_paciente(historia("P-0000015"), FECHA_REFERENCIA)
    assert ficha.identificacion == "CBIO:msk_chord_2024:P-0000015"
    assert ficha.sexo == "femenino"
    assert ficha.fecha_nacimiento == "1981-01-01"
    assert ficha.diagnostico_principal == "Breast Invasive Ductal Carcinoma"
    assert ficha.estadio == "I"
    assert ficha.tipo_cancer == "breast"


def test_con_dos_canceres_no_se_asume_tipo_ni_estadio(historia):
    contenido = historia("P-0000012")
    ficha = ficha_paciente(contenido, FECHA_REFERENCIA)
    assert ficha.tipo_cancer is None
    assert ficha.estadio is None
    assert "cancer_type" not in _datos(contenido)
    assert "ajcc_stage_at_diagnosis" not in _datos(contenido)
    # Ambos primarios quedan como antecedentes.
    assert len([a for a in _filas(contenido, "antecedentes_externos") if a["tipo"] == "condicion"]) == 2


def test_hr_y_her2_no_no_son_un_negativo_confirmado(historia):
    """En MSK-CHORD, HR/HER2 "No" = no se encontró un positivo (hay
    pacientes así tratadas con trastuzumab u hormonoterapia): no se registra
    negativo ni se deriva triple negativo; queda faltante para HC-05."""
    contenido = historia("P-0000015")
    datos, biomarcadores = _datos(contenido), _biomarcadores(contenido)
    assert datos["cancer_type"] == "breast"
    for variable in ("her2_status", "hormone_receptor_status", "er_status", "pr_status", "breast_subtype"):
        assert variable not in datos
    for nombre in ("HER2", "Receptores hormonales (HR)", "RE", "RP"):
        assert nombre not in biomarcadores


def test_her2_positivo_si_se_registra(cliente, fuente):
    cliente.pacientes["P-0000015"]["datos_paciente"]["HER2"] = "Yes"
    contenido = fuente.historia(ESTUDIO, "P-0000015")
    datos, biomarcadores = _datos(contenido), _biomarcadores(contenido)
    assert datos["her2_status"] == "positive"
    assert biomarcadores["HER2"] == "positivo"
    assert datos["breast_subtype"] == "other"


def test_con_receptores_hormonales_positivos_no_se_inventa_re_ni_rp(cliente, fuente):
    cliente.pacientes["P-0000015"]["datos_paciente"]["HR"] = "Yes"
    contenido = fuente.historia(ESTUDIO, "P-0000015")
    datos, biomarcadores = _datos(contenido), _biomarcadores(contenido)
    assert datos["hormone_receptor_status"] == "positive"
    assert "er_status" not in datos and "pr_status" not in datos
    assert "RE" not in biomarcadores and "RP" not in biomarcadores
    assert datos["breast_subtype"] == "other"


def test_no_se_derivan_variables_que_requieren_juicio_clinico(historia):
    datos = _datos(historia("P-0000036"))
    for variable in ("disease_setting", "clinical_t_category", "clinical_n_status", "clinical_m_status",
                     "molecular_pathway_status", "smoking_status", "pdl1_tps"):
        assert variable not in datos
    assert datos["smoking_status_nlp_prediction"] == "Former/Current Smoker"


def test_variantes_se_guardan_como_hechos_y_nunca_como_positivo(historia):
    biomarcadores = _biomarcadores(historia("P-0000036"))
    assert biomarcadores["EGFR"] == "mutación detectada: V834L (Missense_Mutation) — muestra P-0000036-T01-IM3"
    assert biomarcadores["ALK"].startswith("fusión detectada: EML4-ALK")
    assert not any("positivo" in v for v in biomarcadores.values())


def test_fusion_reportada_en_ambos_sentidos_se_guarda_una_vez(cliente, fuente):
    cliente.pacientes["P-0000036"]["fusiones"].insert(0,
        {"muestra": "P-0000036-T01-IM3", "gen_1": "ALK", "gen_2": "EML4", "descripcion": "Protein fusion: in frame (ALK-EML4)"}
    )
    alk = _biomarcadores(fuente.historia(ESTUDIO, "P-0000036"))["ALK"]
    assert alk == "fusión detectada: EML4-ALK (Protein fusion: in frame) — muestra P-0000036-T01-IM3"


def test_msi_no_reportable_queda_como_no_concluyente(cliente, fuente):
    cliente.pacientes["P-0000036"]["muestras"]["P-0000036-T01-IM3"]["MSI_TYPE"] = "Do not report"
    msi = _biomarcadores(fuente.historia(ESTUDIO, "P-0000036"))["MSI"]
    assert msi.startswith("no concluyente")


def test_no_detectada_solo_para_genes_del_panel(cliente, fuente):
    biomarcadores = _biomarcadores(fuente.historia(ESTUDIO, "P-0000036"))
    assert biomarcadores["KRAS"] == "mutación no detectada (panel IMPACT341) — muestra P-0000036-T01-IM3"
    assert biomarcadores["ROS1"] == "fusión no detectada (panel IMPACT341) — muestra P-0000036-T01-IM3"

    cliente.pacientes["P-0000036"]["muestras"]["P-0000036-T01-IM3"].pop("GENE_PANEL")
    sin_panel = _biomarcadores(fuente.historia(ESTUDIO, "P-0000036"))
    assert "KRAS" not in sin_panel  # sin panel conocido no se afirma ausencia
    assert "EGFR" in sin_panel  # los hallazgos sí se guardan


def test_erbb2_no_se_consulta_en_mama_para_no_pasar_por_estado_her2(historia):
    assert "ERBB2" not in _biomarcadores(historia("P-0000015"))


def test_pdl1_binario_no_se_guarda_como_biomarcador_pdl1(historia):
    contenido = historia("P-0000036")
    assert "PD-L1" not in _biomarcadores(contenido)
    assert _datos(contenido)["pdl1_positive_without_tps"] == "positive"


def test_ecog_es_el_mas_reciente(historia):
    assert _datos(historia("P-0000015"))["ecog_ps"] == "1"


def test_laboratorios_con_rango_de_referencia(historia):
    labs = _filas(historia("P-0000015"), "laboratorios")
    alto = next(l for l in labs if l["valor"] == "1412")
    normal = next(l for l in labs if l["valor"] == "25")
    assert alto["prueba"] == "CA 15-3" and alto["rango_referencia"] == "0-30" and alto["alterado"] == 1
    assert normal["alterado"] == 0


def test_imagenes_dicen_que_vienen_de_nlp(historia):
    imagen = _filas(historia("P-0000015"), "imagenologia")[0]
    assert imagen["modalidad"] == "TAC"
    assert imagen["region"] == "tórax, abdomen"
    assert "NLP" in imagen["hallazgos"] and "distinto del texto original" in imagen["hallazgos"]
    assert "Progresión detectada" in imagen["hallazgos"] and "hueso" in imagen["hallazgos"]


def test_la_progresion_de_imagen_se_lee_bien_con_deteccion_de_negacion(historia):
    """DX-02 busca "progresión" con detección de negación: la afirmativa debe
    contar y la negativa no (antes, el encabezado "no es el texto original"
    negaba cualquier progresión)."""
    from dx_clinica.matcher import coincide_sin_negacion

    imagen = _filas(historia("P-0000015"), "imagenologia")[0]
    assert coincide_sin_negacion(imagen["hallazgos"], ("progresión",))
    for negativa in ("Sin progresión (probabilidad 0.02).", "No concluyente para progresión (probabilidad 0.40)."):
        texto = negativa + " (Resumen de informe radiológico generado por NLP en MSK-CHORD, distinto del texto original.)"
        assert not coincide_sin_negacion(texto, ("progresión",))


def test_tratamientos_y_procedimientos_como_antecedentes(historia):
    antecedentes = _filas(historia("P-0000015"), "antecedentes_externos")
    descripciones = [a["descripcion"] for a in antecedentes]
    assert any(d.startswith("Capecitabine (quimioterapia), del ") for d in descripciones)
    assert any(d.startswith("Radioterapia") for d in descripciones)
    assert any("registro de tumores" in d and "AJCC I" in d for d in descripciones)


def test_eventos_sin_equivalente_se_cuentan_como_omitidos(historia):
    _, omitidos = _registros(historia("P-0000015"))
    assert omitidos == 2  # secuenciación y toma de muestra


def test_identificadores_externos_son_unicos(historia):
    for paciente in ("P-0000015", "P-0000036", "P-0000012"):
        registros, _ = _registros(historia(paciente))
        ids = [r.identificador_externo for r in registros]
        assert len(ids) == len(set(ids))


def test_rechaza_la_historia_de_otro_paciente(historia):
    with pytest.raises(PacienteNoCoincideError):
        registros_desde_cbioportal(
            historia("P-0000015"), SimpleNamespace(identificacion="CBIO:msk_chord_2024:P-0000036"), FECHA_REFERENCIA
        )
