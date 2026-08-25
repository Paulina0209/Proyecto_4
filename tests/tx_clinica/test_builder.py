"""Tests de tx_clinica.builder / evidence / module_selector.

Autocontenido: no depende de historia_clinica_mock ni de ninguna base de
datos. El fixture guidelines_root construye su propio guidelines/ de
prueba, con módulos deliberadamente distintos entre sí para cubrir la
mayor variedad posible de formatos y casos reales que causaron bugs
durante el desarrollo:

  - reglas que condicionan por fármacos (breast_early_tnbc)
  - reglas que NO condicionan por fármacos, con varios régimenes de la
    misma fase (cutaneous_melanoma) -- causa real de duplicados
  - conclusion con induction_regimen_id/maintenance_regimen_id en vez de
    regimen_id, con ramas por histología (nsclc) -- causa real de mezcla
    de régimenes de histología ajena
  - reglas de exclusión con audit_effect negativo explícito
    (opposes_prescription/potential_deviation)
  - audit_effect = not_evaluable declarado en una regla (dato presente
    pero la guía dice que ese valor no permite decidir)
  - regimens.yaml como lista Y como diccionario keyed por id
  - matching por prescribed_regimen_id en vez de prescribed_antineoplastic_drugs
  - formato de régimen no reconocido (debe excluirse, no adivinarse)

Corre con:  python -m pytest tx_clinica/tests -v
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tx_clinica.builder import construir_recomendaciones_tratamiento
from tx_clinica.evidence import obtener_evidencia_regla
from tx_clinica.module_selector import seleccionar_modulo


def _escribir(path: Path, contenido: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(contenido, sort_keys=False))


@pytest.fixture
def guidelines_root(tmp_path: Path) -> Path:
    root = tmp_path / "guidelines"

    # =====================================================================
    # Módulo 1: breast_early_tnbc -- caso base, regla que SÍ condiciona
    # por fármacos, regimens.yaml como LISTA con `includes`.
    # =====================================================================
    mod = root / "breast_early_tnbc"
    _escribir(mod / "rules" / "eligibility.yaml", {
        "rules": [{
            "id": "ESMO-BREAST-E-TNBC-ELIG-001",
            "conditions": {"all": [
                {"field": "cancer_type", "operator": "equals", "value": "breast"},
                {"field": "breast_subtype", "operator": "equals", "value": "triple_negative"},
                {"field": "metastatic_disease", "operator": "equals", "value": "no"},
            ]},
            "conclusion": {"action": "enter_module", "audit_effect": "none"},
        }]
    })
    _escribir(mod / "rules" / "neoadjuvant.yaml", {
        "rules": [{
            "id": "ESMO-BREAST-E-TNBC-NEO-001",
            "conditions": {"all": [
                {"field": "clinical_stage", "operator": "in", "value": ["II", "III"]},
                {"field": "treatment_phase", "operator": "equals", "value": "neoadjuvant"},
                {"field": "prescribed_antineoplastic_drugs", "operator": "contains", "value": "pembrolizumab"},
            ]},
            "conclusion": {"action": "support_pembrolizumab", "phase": "neoadjuvant", "audit_effect": "supports_prescription"},
            "evidence": {"organization": "ESMO", "native": {"evidence_level": "I", "recommendation_grade": "A", "mcbs": {"score": "A"}}, "explicit_grade_reported": True},
            "source": {"title": "Early breast cancer CPG", "organization": "ESMO", "publication_year": 2024, "section": "TNBC"},
        }]
    })
    _escribir(mod / "regimens.yaml", {
        "regimens": [{"id": "pembro_neoadjuvant_sequence", "phase": "neoadjuvant", "includes": ["pembrolizumab", "taxane"]}]
    })
    _escribir(mod / "metadata.yaml", {
        "module_id": "esmo_breast_early_tnbc", "module_version": "1.0", "organization": "ESMO",
        "source": {"title": "Early breast cancer CPG", "publication_year": 2024},
        "validation": {"clinical_validation_status": "pending"},
    })

    # =====================================================================
    # Módulo 2: cutaneous_melanoma -- regla que NO condiciona por
    # fármacos (bug de deduplicación), regimens.yaml como LISTA con
    # `components`, incluye régimen de formato NO RECONOCIDO.
    # =====================================================================
    mod = root / "cutaneous_melanoma"
    _escribir(mod / "rules" / "eligibility.yaml", {
        "rules": [{
            "id": "ESMO-MEL-CUT-ELIG-001",
            "conditions": {"all": [
                {"field": "cancer_type", "operator": "equals", "value": "melanoma"},
                {"field": "melanoma_primary_site", "operator": "in", "value": ["cutaneous"]},
            ]},
            "conclusion": {"action": "enter_module", "audit_effect": "none"},
        }]
    })
    _escribir(mod / "rules" / "adjuvant.yaml", {
        "rules": [{
            "id": "ESMO-MEL-CUT-ADJ-001",
            "conditions": {"all": [
                {"field": "treatment_phase", "operator": "equals", "value": "adjuvant"},
                {"field": "stage_group", "operator": "in", "value": ["IIB", "IIC"]},
                {"field": "age_years", "operator": "greater_than_or_equal", "value": 12},
            ]},
            "conclusion": {"action": "support_regimen", "regimen_id": "pembro_adjuvant_stage_iib_iic", "audit_effect": "supports_prescription"},
            "evidence": {"organization": "ESMO", "native": {"evidence_level": "I", "recommendation_grade": "A", "mcbs": {"score": "A"}}, "explicit_grade_reported": True},
            "source": {"title": "Melanoma CPG", "organization": "ESMO", "publication_year": 2024, "section": "Adjuvant IIB-IIC"},
        }]
    })
    _escribir(mod / "regimens.yaml", {
        "regimens": [
            {"id": "pembro_adjuvant_stage_iib_iic", "components": ["pembrolizumab"], "treatment_phase": "adjuvant"},
            {"id": "pembro_adjuvant_resected_stage_iii", "components": ["pembrolizumab"], "treatment_phase": "adjuvant"},
            # Régimen de formato no reconocido a propósito: no tiene
            # includes/components/matching -- debe excluirse, no adivinarse.
            {"id": "regimen_formato_desconocido", "protocol_reference": "algo_que_no_es_farmacos"},
        ]
    })
    _escribir(mod / "metadata.yaml", {
        "module_id": "esmo_cutaneous_melanoma", "module_version": "1.0", "organization": "ESMO",
        "source": {"title": "Melanoma CPG", "publication_year": 2024},
        "validation": {"clinical_validation_status": "pending"},
    })

    # =====================================================================
    # Módulo 3: nsclc_metastatic_non_oncogene -- conclusion con
    # induction_regimen_id/maintenance_regimen_id, ramas por histología,
    # regla de EXCLUSIÓN con audit_effect negativo explícito,
    # regimens.yaml como DICCIONARIO keyed por id.
    # =====================================================================
    mod = root / "nsclc_metastatic_non_oncogene"
    _escribir(mod / "rules" / "eligibility.yaml", {
        "rules": [{
            "id": "ESMO-NSCLC-M-ELIG-001",
            "conditions": {"all": [
                {"field": "cancer_type", "operator": "equals", "value": "NSCLC"},
                {"field": "molecular_pathway_status", "operator": "equals", "value": "non_oncogene_addicted"},
            ]},
            "conclusion": {"action": "enter_module", "audit_effect": "none"},
        }]
    })
    _escribir(mod / "rules" / "first_line.yaml", {
        "rules": [
            {
                "id": "ESMO-NSCLC-M-FL-001",
                "conditions": {"all": [
                    {"field": "treatment_line", "operator": "equals", "value": 1},
                    {"field": "pdl1_tps", "operator": "greater_than_or_equal", "value": 50},
                ]},
                "conclusion": {"action": "support_regimen", "regimen_id": "pembro_monotherapy", "audit_effect": "supports_prescription"},
                "evidence": {"organization": "ESMO", "native": {"evidence_level": "I", "recommendation_grade": "A", "mcbs": {"score": 5}}, "explicit_grade_reported": True},
                "source": {"title": "NSCLC CPG", "organization": "ESMO", "publication_year": 2023, "section": "FL PS0-1"},
            },
            {
                "id": "ESMO-NSCLC-M-FL-002",
                "conditions": {"all": [
                    {"field": "histology", "operator": "equals", "value": "non_squamous"},
                    {"field": "treatment_line", "operator": "equals", "value": 1},
                ]},
                "conclusion": {
                    "action": "support_sequence",
                    "induction_regimen_id": "pembro_pemetrexed_induction",
                    "maintenance_regimen_id": "pembro_pemetrexed_maintenance",
                    "audit_effect": "supports_prescription",
                },
                "evidence": {"organization": "ESMO", "native": {"evidence_level": "I", "recommendation_grade": "A", "mcbs": {"score": 4}}, "explicit_grade_reported": True},
                "source": {"title": "NSCLC CPG", "organization": "ESMO", "publication_year": 2023, "section": "FL non-squamous"},
            },
            {
                "id": "ESMO-NSCLC-M-FL-003",
                "conditions": {"all": [
                    {"field": "histology", "operator": "equals", "value": "squamous"},
                    {"field": "treatment_line", "operator": "equals", "value": 1},
                ]},
                "conclusion": {
                    "action": "support_sequence",
                    "induction_regimen_id": "pembro_carboplatin_taxane_induction",
                    "maintenance_regimen_id": "pembro_maintenance",
                    "audit_effect": "supports_prescription",
                },
                "evidence": {"organization": "ESMO", "native": {"evidence_level": "I", "recommendation_grade": "A", "mcbs": {"score": 4}}, "explicit_grade_reported": True},
                "source": {"title": "NSCLC CPG", "organization": "ESMO", "publication_year": 2023, "section": "FL squamous"},
            },
        ]
    })
    _escribir(mod / "rules" / "exclusions.yaml", {
        "rules": [
            {
                "id": "ESMO-NSCLC-M-EXC-001",
                "name": "Monoterapia con PD-L1 bajo, no recomendada",
                "conditions": {"all": [
                    {"field": "treatment_line", "operator": "equals", "value": 1},
                    {"field": "pdl1_tps", "operator": "less_than", "value": 50},
                    {"field": "prescribed_antineoplastic_drugs", "operator": "exact_set", "value": ["pembrolizumab"]},
                ]},
                "conclusion": {"action": "flag_potential_deviation", "audit_effect": "opposes_prescription"},
                "evidence": {"organization": "ESMO", "native": {"evidence_level": "I", "recommendation_grade": "D"}, "explicit_grade_reported": True},
                "source": {"title": "NSCLC CPG", "organization": "ESMO", "publication_year": 2023, "section": "FL exclusions"},
            },
            {
                "id": "ESMO-NSCLC-M-EXC-002",
                "name": "PD-L1 no testeado: no evaluable",
                "conditions": {"field": "pdl1_tps", "operator": "equals", "value": "not_tested"},
                "conclusion": {"action": "request_missing_information", "audit_effect": "not_evaluable"},
                "evidence": {"organization": "ESMO", "native": {}, "explicit_grade_reported": False},
                "source": {"title": "NSCLC CPG", "organization": "ESMO", "publication_year": 2023, "section": "Diagnostic boundary"},
            },
        ]
    })
    _escribir(mod / "regimens.yaml", {
        "regimens": {
            "pembro_monotherapy": {"matching": {"exact_antineoplastic_set": ["pembrolizumab"]}},
            "pembro_pemetrexed_induction": {"matching": {"all_of": ["pembrolizumab", "pemetrexed"]}},
            "pembro_pemetrexed_maintenance": {"matching": {"all_of": ["pembrolizumab", "pemetrexed"]}},
            "pembro_carboplatin_taxane_induction": {"matching": {"all_of": ["pembrolizumab", "carboplatin"]}},
            "pembro_maintenance": {"matching": {"contains": ["pembrolizumab"]}},
        }
    })
    _escribir(mod / "metadata.yaml", {
        "module_id": "esmo_nsclc_metastatic_non_oncogene", "module_version": "1.1", "organization": "ESMO",
        "source": {"title": "NSCLC CPG", "publication_year": 2023},
        "validation": {"clinical_validation_status": "pending"},
    })

    # =====================================================================
    # Módulo 4: breast_metastatic_tnbc -- matching por
    # prescribed_regimen_id en vez de prescribed_antineoplastic_drugs.
    # =====================================================================
    mod = root / "breast_metastatic_tnbc"
    _escribir(mod / "rules" / "eligibility.yaml", {
        "rules": [{
            "id": "ESMO-BREAST-M-TNBC-ELIG-001",
            "conditions": {"all": [
                {"field": "cancer_type", "operator": "equals", "value": "breast"},
                {"field": "disease_setting", "operator": "equals", "value": "metastatic"},
            ]},
            "conclusion": {"action": "enter_module", "audit_effect": "none"},
        }]
    })
    _escribir(mod / "rules" / "first_line.yaml", {
        "rules": [{
            "id": "ESMO-BREAST-M-TNBC-FL-001",
            "conditions": {"all": [
                {"field": "treatment_line", "operator": "equals", "value": 1},
                {"field": "pdl1_cps", "operator": "greater_than_or_equal", "value": 10},
                {"field": "prescribed_regimen_id", "operator": "equals", "value": "pembro_paclitaxel"},
            ]},
            "conclusion": {"action": "support_regimen", "regimen_id": "pembro_paclitaxel", "audit_effect": "supports_prescription"},
            "evidence": {"organization": "ESMO", "native": {"evidence_level": "I", "recommendation_grade": "A", "mcbs": {"score": 3}}, "explicit_grade_reported": True},
            "source": {"title": "Metastatic breast CPG", "organization": "ESMO", "publication_year": 2021, "section": "FL TNBC"},
        }]
    })
    _escribir(mod / "regimens.yaml", {
        "regimens": [{"id": "pembro_paclitaxel", "includes": ["pembrolizumab", "paclitaxel"]}]
    })
    _escribir(mod / "metadata.yaml", {
        "module_id": "esmo_breast_metastatic_tnbc", "module_version": "1.0", "organization": "ESMO",
        "source": {"title": "Metastatic breast CPG", "publication_year": 2021},
        "validation": {"clinical_validation_status": "pending"},
    })

    return root


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
        """PD-L1 <50 + monoterapia exacta -> ESMO-NSCLC-M-EXC-001 da
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