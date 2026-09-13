"""Fixture compartido por todos los tests de tx_clinica/tests/.

guidelines_root construye su propio guidelines/ de prueba (4 módulos,
con los formatos y casos reales que causaron bugs durante el
desarrollo -- ver test_builder.py para el detalle). Al vivir en
conftest.py, cualquier archivo de test en esta carpeta puede usarlo sin
importarlo explícitamente (mecanismo estándar de pytest).
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
                    {"field": "immunotherapy_contraindication", "operator": "equals", "value": "no"},
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
                    {"field": "prescribed_regimen_id", "operator": "equals", "value": "pembro_monotherapy"},
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
