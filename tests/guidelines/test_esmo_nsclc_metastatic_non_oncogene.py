from pathlib import Path

from cdss.core.engine import evaluate_rule_set


ROOT = Path(__file__).resolve().parents[3]
RULES = (
    ROOT
    / "src"
    / "cdss"
    / "guidelines"
    / "nsclc_metastatic_non_oncogene"
    / "rules"
)


def applicable_ids(filename: str, facts: dict) -> set[str]:
    results = evaluate_rule_set(RULES / filename, facts)
    return {item.rule_id for item in results if item.status == "applicable"}


def test_first_line_pembro_monotherapy_supported() -> None:
    facts = {
        "treatment_line": 1,
        "histology": "non_squamous",
        "ecog_ps": 1,
        "pdl1_tps": 70,
        "smoking_status": "former_smoker",
        "immunotherapy_contraindication": "no",
        "rapid_tumor_reduction_needed": "no",
    }

    assert "ESMO-NSCLC-M-FL-001" in applicable_ids("first_line.yaml", facts)


def test_low_pdl1_pembro_monotherapy_is_flagged() -> None:
    facts = {
        "treatment_line": 1,
        "pdl1_tps": 20,
        "prescribed_antineoplastic_drugs": ["pembrolizumab"],
        "smoking_status": "former_smoker",
        "ecog_ps": 1,
        "immunotherapy_contraindication": "no",
    }

    assert "ESMO-NSCLC-M-EXC-001" in applicable_ids("exclusions.yaml", facts)


def test_missing_pdl1_does_not_become_negative() -> None:
    facts = {
        "treatment_line": 1,
        "ecog_ps": 1,
        "pdl1_tps": None,
        "smoking_status": "former_smoker",
        "immunotherapy_contraindication": "no",
    }

    results = evaluate_rule_set(RULES / "first_line.yaml", facts)
    target = next(item for item in results if item.rule_id == "ESMO-NSCLC-M-FL-001")

    assert target.status == "not_evaluable"
    assert "pdl1_tps" in target.missing_fields
