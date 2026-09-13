"""Tests de tx_clinica.builder / evidence / module_selector.seleccionar_modulo.

El fixture guidelines_root vive en conftest.py (compartido con los demás
archivos de test de esta carpeta) -- ver ahí el detalle de los 4 módulos
de prueba y por qué cada uno cubre un caso real que causó un bug durante
el desarrollo.

Corre con:  python -m pytest tx_clinica/tests -v
"""

from __future__ import annotations

from tx_clinica.builder import construir_recomendaciones_tratamiento, obtener_farmacos_de_regimen
from tx_clinica.evidence import obtener_evidencia_regla
from tx_clinica.module_selector import seleccionar_modulo


# ---------------------------------------------------------------------------
# AC1 — sugerencia alineada con la guía, con razonamiento (rule_id real)
# ---------------------------------------------------------------------------
class TestSugerenciaAlineadaConGuia:
    def test_regla_que_condiciona_por_farmacos_da_un_candidato_correcto(self, guidelines_root):
        facts = {
            "cancer_type": "breast", "breast_subtype": "triple_negative",
            "metastatic_disease": "no", "clinical_stage": "II", "treatment_phase": None,
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)

        assert resultado.module_id == "breast_early_tnbc"
        assert len(resultado.candidatos) == 1
        assert resultado.candidatos[0].regimen_id == "pembro_neoadjuvant_sequence"
        assert resultado.candidatos[0].rule_id_disparada == "ESMO-BREAST-E-TNBC-NEO-001"

    def test_matching_por_prescribed_regimen_id_tambien_funciona(self, guidelines_root):
        """Algunos módulos (ej. mama metastásica) matchean por
        prescribed_regimen_id en vez de prescribed_antineoplastic_drugs."""
        facts = {
            "cancer_type": "breast", "disease_setting": "metastatic",
            "treatment_line": 1, "pdl1_cps": 15,
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)

        assert resultado.module_id == "breast_metastatic_tnbc"
        assert len(resultado.candidatos) == 1
        assert resultado.candidatos[0].regimen_id == "pembro_paclitaxel"


# ---------------------------------------------------------------------------
# Regresión: reglas que no condicionan por fármacos no deben duplicar
# candidatos ni mezclar régimenes de contexto ajeno.
# ---------------------------------------------------------------------------
class TestDeduplicacionPorRegimenEnConclusion:
    def test_regla_sin_condicion_de_farmacos_no_duplica_candidatos(self, guidelines_root):
        facts = {
            "cancer_type": "melanoma", "melanoma_primary_site": "cutaneous",
            "treatment_phase": "adjuvant", "stage_group": "IIB", "age_years": 47,
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)

        assert len(resultado.candidatos) == 1
        assert resultado.candidatos[0].regimen_id == "pembro_adjuvant_stage_iib_iic"

    def test_conclusion_con_induction_y_maintenance_regimen_id_no_mezcla_histologias(self, guidelines_root):
        facts = {
            "cancer_type": "NSCLC", "molecular_pathway_status": "non_oncogene_addicted",
            "histology": "non_squamous", "treatment_line": 1, "pdl1_tps": 20,
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)

        regimenes = {c.regimen_id for c in resultado.candidatos}
        assert regimenes == {"pembro_pemetrexed_induction", "pembro_pemetrexed_maintenance"}
        assert "pembro_carboplatin_taxane_induction" not in regimenes
        assert "pembro_maintenance" not in regimenes

    def test_histologia_escamosa_recibe_su_propio_par_induction_maintenance(self, guidelines_root):
        """Caso simétrico al anterior: paciente escamoso debe recibir
        SOLO los régimenes de FL-003, nunca los de FL-002."""
        facts = {
            "cancer_type": "NSCLC", "molecular_pathway_status": "non_oncogene_addicted",
            "histology": "squamous", "treatment_line": 1, "pdl1_tps": 20,
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)

        regimenes = {c.regimen_id for c in resultado.candidatos}
        assert regimenes == {"pembro_carboplatin_taxane_induction", "pembro_maintenance"}
        assert "pembro_pemetrexed_induction" not in regimenes


# ---------------------------------------------------------------------------
# Formato de régimen no reconocido: se excluye, nunca se adivina.
# ---------------------------------------------------------------------------
class TestFormatoDeRegimenDesconocido:
    def test_regimen_sin_farmacos_reconocibles_no_aparece_como_candidato(self, guidelines_root):
        facts = {
            "cancer_type": "melanoma", "melanoma_primary_site": "cutaneous",
            "treatment_phase": "adjuvant", "stage_group": "IIB", "age_years": 47,
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)

        regimenes = {c.regimen_id for c in resultado.candidatos}
        assert "regimen_formato_desconocido" not in regimenes


# ---------------------------------------------------------------------------
# Clasificación de audit_effect: negativos explícitos excluyen el
# régimen por completo; not_evaluable se distingue de faltar un dato.
# ---------------------------------------------------------------------------
class TestClasificacionDeAuditEffect:
    def test_contraindicacion_explicita_excluye_el_regimen_por_completo(self, guidelines_root):
        """PD-L1 <50 + monoterapia -> ESMO-NSCLC-M-EXC-001 da
        opposes_prescription -- pembro_monotherapy NO debe aparecer,
        aunque otra regla (FL-001) no lo haya evaluado todavía."""
        facts = {
            "cancer_type": "NSCLC", "molecular_pathway_status": "non_oncogene_addicted",
            "treatment_line": 1, "pdl1_tps": 20, "histology": "non_squamous",
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)

        regimenes = {c.regimen_id for c in resultado.candidatos}
        assert "pembro_monotherapy" not in regimenes

    def test_dato_faltante_simplemente_omite_el_regimen_sin_error(self, guidelines_root):
        """Si falta un campo que una regla necesita, el motor da
        not_evaluable a NIVEL DE MOTOR (missing_fields) -- el régimen
        simplemente no califica, sin lanzar ninguna excepción."""
        facts = {
            "cancer_type": "NSCLC", "molecular_pathway_status": "non_oncogene_addicted",
            "treatment_line": 1,
            # pdl1_tps y histology deliberadamente ausentes
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)
        assert isinstance(resultado.candidatos, tuple)  # no crashea

    def test_audit_effect_not_evaluable_declarado_en_regla_se_respeta(self, guidelines_root):
        """Caso distinto al anterior: el dato SÍ está presente
        (pdl1_tps='not_tested'), y la propia regla declara
        audit_effect=not_evaluable -- no supports_prescription ni
        requires_clinical_review."""
        facts = {
            "cancer_type": "NSCLC", "molecular_pathway_status": "non_oncogene_addicted",
            "treatment_line": 1, "histology": "non_squamous", "pdl1_tps": "not_tested",
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)

        no_evaluables = [c for c in resultado.candidatos if c.audit_effect == "not_evaluable"]
        # pembro_monotherapy (matching exact_set=[pembrolizumab]) es el
        # único régimen cuyo override deja pdl1_tps intacto = 'not_tested'
        assert any(c.regimen_id == "pembro_monotherapy" for c in no_evaluables)


# ---------------------------------------------------------------------------
# AC3 — sin guía aplicable, no se fuerza una sugerencia genérica.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# AC2 — Dado que el paciente tiene una comorbilidad que contraindica una
# opción de primera línea, esa opción no se presenta como primera línea,
# o se presenta con la advertencia correspondiente.
# ---------------------------------------------------------------------------
class TestComorbilidadConAdvertencia:
    def test_sin_comorbilidad_el_regimen_es_primera_linea_normal(self, guidelines_root):
        facts = {
            "cancer_type": "NSCLC", "molecular_pathway_status": "non_oncogene_addicted",
            "treatment_line": 1, "pdl1_tps": 70, "histology": "non_squamous",
            "immunotherapy_contraindication": "no",
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)

        positivo = next(c for c in resultado.candidatos if c.regimen_id == "pembro_monotherapy")
        assert positivo.audit_effect == "supports_prescription"
        assert positivo.advertencia_comorbilidad is None
        assert positivo.es_primera_opcion is True

    def test_con_comorbilidad_el_regimen_no_es_primera_linea_pero_trae_advertencia(self, guidelines_root):
        """Mismo paciente que el test anterior, pero con
        immunotherapy_contraindication='yes' -- el régimen que antes era
        supports_prescription ahora debe pasar a requires_clinical_review
        CON una advertencia explícita, nunca desaparecer en silencio."""
        facts = {
            "cancer_type": "NSCLC", "molecular_pathway_status": "non_oncogene_addicted",
            "treatment_line": 1, "pdl1_tps": 70, "histology": "non_squamous",
            "immunotherapy_contraindication": "yes",
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)

        regimenes = {c.regimen_id: c for c in resultado.candidatos}
        assert "pembro_monotherapy" in regimenes, "el régimen no debe desaparecer en silencio"

        candidato = regimenes["pembro_monotherapy"]
        assert candidato.audit_effect == "requires_clinical_review"
        assert candidato.es_primera_opcion is False
        assert candidato.advertencia_comorbilidad is not None
        assert "immunotherapy_contraindication" in candidato.advertencia_comorbilidad
        assert "yes" in candidato.advertencia_comorbilidad

    def test_advertencia_cita_el_valor_real_no_uno_inventado(self, guidelines_root):
        facts = {
            "cancer_type": "NSCLC", "molecular_pathway_status": "non_oncogene_addicted",
            "treatment_line": 1, "pdl1_tps": 70, "histology": "non_squamous",
            "immunotherapy_contraindication": "yes",
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)
        candidato = next(c for c in resultado.candidatos if c.regimen_id == "pembro_monotherapy")
        assert facts["immunotherapy_contraindication"] in candidato.advertencia_comorbilidad

    def test_regimen_que_no_calificaria_ni_siquiera_sin_comorbilidad_no_se_fuerza(self, guidelines_root):
        """Si el régimen no calificaría de todas formas (ej. PD-L1 bajo),
        la comorbilidad no debe "rescatarlo"."""
        facts = {
            "cancer_type": "NSCLC", "molecular_pathway_status": "non_oncogene_addicted",
            "treatment_line": 1, "pdl1_tps": 20,
            "histology": "non_squamous", "immunotherapy_contraindication": "yes",
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)
        regimenes_via_fl001 = [
            c for c in resultado.candidatos
            if c.regimen_id == "pembro_monotherapy" and c.advertencia_comorbilidad is not None
        ]
        assert regimenes_via_fl001 == []

    def test_contraindicacion_explicita_de_otra_regla_no_se_convierte_en_advertencia(self, guidelines_root):
        """Un régimen excluido por opposes_prescription es distinto a la
        comorbilidad -- no debe reaparecer con advertencia."""
        facts = {
            "cancer_type": "NSCLC", "molecular_pathway_status": "non_oncogene_addicted",
            "treatment_line": 1, "pdl1_tps": 20,
            "histology": "non_squamous",
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)
        regimenes = {c.regimen_id for c in resultado.candidatos}
        assert "pembro_monotherapy" not in regimenes


class TestSinGuiaAplicable:
    def test_diagnostico_que_no_calza_con_ningun_modulo(self, guidelines_root):
        facts = {"cancer_type": "unknown_cancer_type"}
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)

        assert resultado.sin_guia_aplicable is True
        assert resultado.module_id is None
        assert resultado.esta_vacio()

    def test_facts_vacio_no_hace_adivinar_un_modulo_por_defecto(self, guidelines_root):
        resultado = construir_recomendaciones_tratamiento(1, {}, guidelines_root)
        assert resultado.sin_guia_aplicable is True

    def test_modulo_seleccionado_es_el_de_criterios_correctos_entre_varios_disponibles(self, guidelines_root):
        """Con 4 módulos en guidelines_root, confirma que selecciona el
        correcto (NSCLC) y no cualquiera por casualidad de orden alfabético."""
        facts = {"cancer_type": "NSCLC", "molecular_pathway_status": "non_oncogene_addicted"}
        modulo = seleccionar_modulo(facts, guidelines_root)
        assert modulo == "nsclc_metastatic_non_oncogene"


# ---------------------------------------------------------------------------
# Apoyo a la decisión, no prescripción automática.
# ---------------------------------------------------------------------------
class TestApoyoNoAutomatico:
    def test_disclaimer_fijo_presente(self, guidelines_root):
        facts = {
            "cancer_type": "breast", "breast_subtype": "triple_negative",
            "metastatic_disease": "no", "clinical_stage": "II", "treatment_phase": None,
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)
        assert "NO constituyen una prescripción automática" in resultado.disclaimer

    def test_ningun_candidato_expone_probabilidad_ni_porcentaje(self, guidelines_root):
        facts = {
            "cancer_type": "NSCLC", "molecular_pathway_status": "non_oncogene_addicted",
            "treatment_line": 1, "pdl1_tps": 70, "histology": "non_squamous",
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)
        for candidato in resultado.candidatos:
            assert not hasattr(candidato, "probabilidad")
            assert not hasattr(candidato, "porcentaje")


# ---------------------------------------------------------------------------
# TX-02 — nivel de evidencia y fuente exacta.
# ---------------------------------------------------------------------------
class TestNivelDeEvidenciaVisible:
    def test_candidato_expone_evidencia_completa(self, guidelines_root):
        facts = {
            "cancer_type": "breast", "breast_subtype": "triple_negative",
            "metastatic_disease": "no", "clinical_stage": "II", "treatment_phase": None,
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)

        candidato = resultado.candidatos[0]
        assert candidato.evidencia is not None
        assert candidato.evidencia.evidence_level == "I"
        assert candidato.evidencia.recommendation_grade == "A"
        assert candidato.evidencia.mcbs_score == "A"
        assert candidato.evidencia.module_version == "1.0"
        assert candidato.evidencia.organization == "ESMO"
        assert "ESMO" in candidato.evidencia.resumen_citable()

    def test_evidencia_de_candidato_por_secuencia_tambien_se_resuelve(self, guidelines_root):
        """Los candidatos que vienen de induction_regimen_id/maintenance_regimen_id
        (no de regimen_id simple) también deben traer evidencia -- no es
        exclusivo del caso más simple."""
        facts = {
            "cancer_type": "NSCLC", "molecular_pathway_status": "non_oncogene_addicted",
            "histology": "non_squamous", "treatment_line": 1, "pdl1_tps": 20,
        }
        resultado = construir_recomendaciones_tratamiento(1, facts, guidelines_root)
        for candidato in resultado.candidatos:
            assert candidato.evidencia is not None
            assert candidato.evidencia.evidence_level == "I"

    def test_regla_sin_bloque_evidence_no_hace_fallar_la_construccion(self, guidelines_root):
        """ESMO-BREAST-E-TNBC-ELIG-001 (regla de scope) no tiene bloque
        'evidence' -- obtener_evidencia_regla debe devolver un objeto con
        campos None, no lanzar excepción ni inventar un grado."""
        modulo = guidelines_root / "breast_early_tnbc"
        evidencia = obtener_evidencia_regla(modulo, "rules/eligibility.yaml", "ESMO-BREAST-E-TNBC-ELIG-001")

        assert evidencia is not None
        assert evidencia.evidence_level is None
        assert evidencia.explicit_grade_reported is False

    def test_regla_inexistente_devuelve_none_sin_inventar(self, guidelines_root):
        modulo = guidelines_root / "breast_early_tnbc"
        evidencia = obtener_evidencia_regla(modulo, "rules/neoadjuvant.yaml", "ID-QUE-NO-EXISTE")
        assert evidencia is None

# ---------------------------------------------------------------------------
# obtener_farmacos_de_regimen -- helper público agregado para TX-03
# (interacciones), reutiliza el mismo extractor tolerante que ya usaba
# builder.py internamente, sin duplicarlo.
# ---------------------------------------------------------------------------
class TestObtenerFarmacosDeRegimen:
    def test_regimen_con_includes_lista(self, guidelines_root):
        modulo = guidelines_root / "breast_metastatic_tnbc"
        farmacos = obtener_farmacos_de_regimen(modulo, "pembro_paclitaxel")
        assert farmacos == ["pembrolizumab", "paclitaxel"]

    def test_regimen_con_components_lista(self, guidelines_root):
        modulo = guidelines_root / "cutaneous_melanoma"
        farmacos = obtener_farmacos_de_regimen(modulo, "pembro_adjuvant_stage_iib_iic")
        assert farmacos == ["pembrolizumab"]

    def test_regimen_con_matching_exact_antineoplastic_set_dict_keyed(self, guidelines_root):
        """regimens.yaml de nsclc_metastatic_non_oncogene es un DICCIONARIO
        keyed por id, no una lista -- confirma que el helper también
        funciona con ese formato."""
        modulo = guidelines_root / "nsclc_metastatic_non_oncogene"
        farmacos = obtener_farmacos_de_regimen(modulo, "pembro_monotherapy")
        assert farmacos == ["pembrolizumab"]

    def test_regimen_con_matching_all_of(self, guidelines_root):
        modulo = guidelines_root / "nsclc_metastatic_non_oncogene"
        farmacos = obtener_farmacos_de_regimen(modulo, "pembro_pemetrexed_induction")
        assert farmacos == ["pembrolizumab", "pemetrexed"]

    def test_regimen_inexistente_devuelve_none(self, guidelines_root):
        modulo = guidelines_root / "breast_metastatic_tnbc"
        assert obtener_farmacos_de_regimen(modulo, "un_regimen_que_no_existe") is None

    def test_regimen_con_formato_no_reconocido_devuelve_none(self, guidelines_root):
        """Mismo régimen que TestFormatoDeRegimenDesconocido ya prueba a
        nivel de construir_recomendaciones_tratamiento -- acá se prueba
        directo contra el helper."""
        modulo = guidelines_root / "cutaneous_melanoma"
        assert obtener_farmacos_de_regimen(modulo, "regimen_formato_desconocido") is None

    def test_modulo_sin_regimens_yaml_devuelve_none_sin_fallar(self, tmp_path):
        modulo_vacio = tmp_path / "modulo_sin_regimens"
        modulo_vacio.mkdir()
        assert obtener_farmacos_de_regimen(modulo_vacio, "cualquier_id") is None
