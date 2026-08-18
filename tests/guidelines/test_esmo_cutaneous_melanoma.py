"""Technical tests for the ESMO cutaneous melanoma module."""

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
    / "cutaneous_melanoma"
)
RULES = MODULE / "rules"
CASES_FILE = (
    Path(__file__).parent
    / "cases"
    / "esmo"
    / "cutaneous_melanoma"
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

    assert target is not None, (
        f"Rule {expected['rule_id']} was not found in {case['rule_file']}."
    )
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
    ("filename", "rule_id", "level", "grade", "mcbs"),
    [
        ("adjuvant.yaml", "ESMO-MEL-CUT-ADJ-001", "I", "A", {"version": "1.1", "score": "A"}),
        ("adjuvant.yaml", "ESMO-MEL-CUT-ADJ-002", "I", "A", {"version": "1.1", "score": "A"}),
        ("neoadjuvant.yaml", "ESMO-MEL-CUT-NEO-001", "II", "A", None),
        ("unresectable_metastatic.yaml", "ESMO-MEL-CUT-MET-001", "I", "A", {"version": "1.1", "score": "A/4"}),
        ("unresectable_metastatic.yaml", "ESMO-MEL-CUT-MET-002", "I", "A", {"version": "1.1", "score": "A/4"}),
    ],
)
def test_positive_rules_preserve_native_esmo_evidence(
    filename: str,
    rule_id: str,
    level: str,
    grade: str,
    mcbs: dict[str, str] | None,
) -> None:
    rules = load_yaml(RULES / filename)["rules"]
    rule = next(item for item in rules if item["id"] == rule_id)
    native = rule["evidence"]["native"]

    assert native["evidence_level"] == level
    assert native["recommendation_grade"] == grade
    assert native["mcbs"] == mcbs
    assert rule["evidence"]["explicit_grade_reported"] is True


def test_class_level_recommendation_is_not_mislabeled_as_drug_specific() -> None:
    rules = load_yaml(RULES / "adjuvant.yaml")["rules"]
    rule = next(item for item in rules if item["id"] == "ESMO-MEL-CUT-ADJ-003")
    assert rule["evidence"]["statement_scope"] == "class_level"
    assert rule["conclusion"]["candidate_drug"] == "pembrolizumab"


def test_pdl1_is_not_required_for_pembrolizumab_selection() -> None:
    case = next(item for item in CASES if item["id"] == "adjuvant_stage_iib_pdl1_zero_supported")
    evaluation = next(
        item
        for item in evaluate_rule_set(RULES / case["rule_file"], case["facts"])
        if item.rule_id == "ESMO-MEL-CUT-ADJ-001"
    )
    assert evaluation.status == "applicable"
    assert evaluation.conclusion is not None
    assert evaluation.conclusion["pdl1_requirement"] == "none"


@pytest.mark.parametrize("case_id", ["advanced_first_line_braf_v600e_supported", "advanced_first_line_braf_wild_type_supported", "advanced_first_line_missing_braf_still_supported"])
def test_first_line_pembrolizumab_does_not_depend_on_braf_status(case_id: str) -> None:
    case = next(item for item in CASES if item["id"] == case_id)
    evaluation = next(
        item
        for item in evaluate_rule_set(RULES / case["rule_file"], case["facts"])
        if item.rule_id == "ESMO-MEL-CUT-MET-001"
    )
    assert evaluation.status == "applicable"
    assert evaluation.conclusion is not None
    assert evaluation.conclusion["braf_requirement"] == "none"


def test_neoadjuvant_rule_preserves_reported_regulatory_boundary() -> None:
    rules = load_yaml(RULES / "neoadjuvant.yaml")["rules"]
    rule = next(item for item in rules if item["id"] == "ESMO-MEL-CUT-NEO-001")
    assert (
        rule["evidence"]["regulatory_status_as_reported_by_source"]
        == "not EMA or FDA approved as neoadjuvant therapy"
    )


def test_metadata_preserves_temporal_and_licensing_constraints() -> None:
    metadata = load_yaml(MODULE / "metadata.yaml")
    assert metadata["temporal_applicability"]["version_effective_from"] == "2024-11-14"
    assert metadata["licensing"]["public_distribution"] == "not_authorized"


def test_all_module_yaml_files_are_valid_objects() -> None:
    for path in MODULE.rglob("*.yaml"):
        assert isinstance(load_yaml(path), dict), path
