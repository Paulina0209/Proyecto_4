"""Technical tests for the ESMO localized/adjuvant RCC module."""

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
    / "renal_cell_carcinoma_localized_adjuvant"
)
RULES = MODULE / "rules"
CASES_FILE = (
    Path(__file__).parent
    / "cases"
    / "esmo"
    / "renal_cell_carcinoma_localized_adjuvant"
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
        ("ESMO-RCC-LOC-ADJ-001", "I", "A", {"version": "1.1", "score": "A"}),
        ("ESMO-RCC-LOC-ADJ-002", "I", "A", {"version": "1.1", "score": "A"}),
        ("ESMO-RCC-LOC-ADJ-003", "I", "A", {"version": "1.1", "score": "A"}),
        ("ESMO-RCC-LOC-ADJ-004", "I", "A", {"version": "1.1", "score": "A"}),
        ("ESMO-RCC-LOC-ADJ-005", "II", "B", {"version": "1.1", "score": "A"}),
    ],
)
def test_adjuvant_rules_preserve_native_esmo_evidence(
    rule_id: str,
    level: str,
    grade: str,
    mcbs: dict[str, str],
) -> None:
    rules = load_yaml(RULES / "adjuvant.yaml")["rules"]
    rule = next(item for item in rules if item["id"] == rule_id)
    native = rule["evidence"]["native"]

    assert native["evidence_level"] == level
    assert native["recommendation_grade"] == grade
    assert native["mcbs"] == mcbs
    assert rule["evidence"]["explicit_grade_reported"] is True


def test_m1_ned_rule_is_kept_in_adjuvant_module() -> None:
    rules = load_yaml(RULES / "adjuvant.yaml")["rules"]
    rule = next(item for item in rules if item["id"] == "ESMO-RCC-LOC-ADJ-005")
    assert rule["conclusion"]["regimen_id"] == "pembro_adjuvant_M1_NED"
    assert "M1_NED" in rule["interpretation_note"]


def test_low_risk_rule_requires_review_not_automatic_deviation() -> None:
    rules = load_yaml(RULES / "exclusions.yaml")["rules"]
    rule = next(item for item in rules if item["id"] == "ESMO-RCC-LOC-EXC-003")
    assert rule["conclusion"]["audit_effect"] == "requires_clinical_review"


def test_cycle_rule_is_protocol_context_not_fabricated_guideline_grade() -> None:
    rules = load_yaml(RULES / "continuation.yaml")["rules"]
    rule = next(item for item in rules if item["id"] == "ESMO-RCC-LOC-CONT-002")
    assert rule["evidence"]["statement_scope"] == "trial_protocol_context"
    assert rule["evidence"]["explicit_grade_reported"] is False
    assert rule["evidence"]["native"]["evidence_level"] is None


def test_metadata_preserves_temporal_and_licensing_constraints() -> None:
    metadata = load_yaml(MODULE / "metadata.yaml")
    assert metadata["temporal_applicability"]["version_effective_from"] == "2024-05-22"
    assert metadata["licensing"]["public_distribution"] == "not_authorized"


def test_all_module_yaml_files_are_valid_objects() -> None:
    for path in MODULE.rglob("*.yaml"):
        assert isinstance(load_yaml(path), dict), path
