"""Technical tests for the ESMO advanced/metastatic RCC module."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from core.engine import evaluate_rule_set


ROOT = Path(__file__).resolve().parents[2]
MODULE = (
    ROOT
    / "guidelines"
    / "renal_cell_carcinoma_advanced_metastatic"
)
RULES = MODULE / "rules"
CASES_FILE = (
    Path(__file__).parent
    / "cases"
    / "esmo"
    / "renal_cell_carcinoma_advanced_metastatic"
    / "cases.yaml"
)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML object.")
    return data


def load_cases() -> list[dict[str, Any]]:
    cases = load_yaml(CASES_FILE).get("cases")
    if not isinstance(cases, list):
        raise ValueError("cases.yaml must contain a `cases` list.")
    return cases


CASES = load_cases()


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_synthetic_case(case: dict[str, Any]) -> None:
    expected = case["expected"]
    evaluations = evaluate_rule_set(RULES / case["rule_file"], case["facts"])

    target = next(
        (item for item in evaluations if item.rule_id == expected["rule_id"]),
        None,
    )

    assert target is not None
    assert target.status == expected["status"]

    if "audit_effect" in expected:
        assert target.conclusion is not None
        assert target.conclusion["audit_effect"] == expected["audit_effect"]

    if "missing_fields" in expected:
        assert set(expected["missing_fields"]).issubset(target.missing_fields)


def test_case_identifiers_are_unique() -> None:
    identifiers = [case["id"] for case in CASES]
    assert len(identifiers) == len(set(identifiers))


def test_rule_identifiers_are_unique_across_module() -> None:
    identifiers: list[str] = []
    for path in RULES.glob("*.yaml"):
        identifiers.extend(rule["id"] for rule in load_yaml(path)["rules"])
    assert len(identifiers) == len(set(identifiers))


@pytest.mark.parametrize(
    ("rule_id", "level", "grade", "mcbs"),
    [
        ("ESMO-RCC-ADV-FL-001", "I", "A", {"version": "1.1", "score": 4}),
        ("ESMO-RCC-ADV-FL-002", "I", "A", {"version": "1.1", "score": 4}),
        ("ESMO-RCC-ADV-FL-003", "III", "B", None),
        ("ESMO-RCC-ADV-FL-004", "III", "B", None),
        ("ESMO-RCC-ADV-FL-005", "III", "C", None),
        ("ESMO-RCC-ADV-FL-006", "III", "A", None),
        ("ESMO-RCC-ADV-FL-007", "III", "A", None),
    ],
)
def test_first_line_rules_preserve_native_esmo_evidence(
    rule_id: str,
    level: str,
    grade: str,
    mcbs: dict[str, int] | None,
) -> None:
    rules = load_yaml(RULES / "first_line.yaml")["rules"]
    rule = next(item for item in rules if item["id"] == rule_id)
    native = rule["evidence"]["native"]

    assert native["evidence_level"] == level
    assert native["recommendation_grade"] == grade
    assert native["mcbs"] == mcbs
    assert rule["evidence"]["explicit_grade_reported"] is True


def test_clear_cell_pembrolizumab_combinations_do_not_depend_on_imdc() -> None:
    cases = [
        item
        for item in CASES
        if item["id"] in {
            "advanced_ccrcc_lenvatinib_favourable_supported",
            "advanced_ccrcc_axitinib_poor_supported",
            "advanced_ccrcc_lenvatinib_unknown_imdc_supported",
        }
    ]
    assert len(cases) == 3

    for case in cases:
        expected_rule = case["expected"]["rule_id"]
        evaluation = next(
            item
            for item in evaluate_rule_set(RULES / case["rule_file"], case["facts"])
            if item.rule_id == expected_rule
        )
        assert evaluation.status == "applicable"


def test_negative_rechallenge_rule_is_class_level() -> None:
    rules = load_yaml(RULES / "subsequent_line.yaml")["rules"]
    rule = next(item for item in rules if item["id"] == "ESMO-RCC-ADV-SL-002")
    assert rule["evidence"]["statement_scope"] == "class_level"
    assert rule["evidence"]["native"]["evidence_level"] == "I"
    assert rule["evidence"]["native"]["recommendation_grade"] == "D"


def test_papillary_pembrolizumab_regulatory_status_is_preserved() -> None:
    rules = load_yaml(RULES / "first_line.yaml")["rules"]
    rule = next(item for item in rules if item["id"] == "ESMO-RCC-ADV-FL-003")
    assert (
        rule["evidence"]["regulatory_status_as_reported_by_source"]
        == "not EMA or FDA approved"
    )


def test_m1_ned_is_routed_to_adjuvant_module() -> None:
    rules = load_yaml(RULES / "exclusions.yaml")["rules"]
    rule = next(item for item in rules if item["id"] == "ESMO-RCC-ADV-EXC-001")
    assert (
        rule["conclusion"]["module_id"]
        == "esmo_renal_cell_carcinoma_localized_adjuvant"
    )
    assert rule["conclusion"]["audit_effect"] == "outside_scope"


def test_progression_does_not_force_automatic_discontinuation() -> None:
    rules = load_yaml(RULES / "continuation.yaml")["rules"]
    rule = next(item for item in rules if item["id"] == "ESMO-RCC-ADV-CONT-003")
    assert rule["conclusion"]["audit_effect"] == "requires_clinical_review"
    assert "does not mandate automatic discontinuation" in rule["interpretation_note"]


def test_metadata_preserves_temporal_and_licensing_constraints() -> None:
    metadata = load_yaml(MODULE / "metadata.yaml")
    assert metadata["temporal_applicability"]["version_effective_from"] == "2024-05-22"
    assert metadata["licensing"]["public_distribution"] == "not_authorized"


def test_all_module_yaml_files_are_valid_objects() -> None:
    for path in MODULE.rglob("*.yaml"):
        assert isinstance(load_yaml(path), dict), path
