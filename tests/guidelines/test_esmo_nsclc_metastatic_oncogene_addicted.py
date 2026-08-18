from pathlib import Path

import pytest
import yaml

from core.engine import evaluate_rule_set


ROOT = Path(__file__).resolve().parents[2]

MODULE = (
    ROOT
    / "guidelines"
    / "nsclc_metastatic_oncogene_addicted"
)

RULES = MODULE / "rules"

CASES = (
    ROOT
    / "tests"
    / "guidelines"
    / "cases"
    / "esmo"
    / "nsclc_metastatic_oncogene_addicted"
    / "cases.yaml"
)

RULE_FILES = [
    "eligibility.yaml",
    "routing.yaml",
    "sequencing.yaml",
    "exclusions.yaml",
]


def load_cases():
    with CASES.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)["cases"]


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c["id"])
def test_synthetic_case(case):
    results = evaluate_rule_set(RULES / case["rule_file"], case["facts"])
    target = next(item for item in results if item.rule_id == case["expected_rule_id"])
    assert target.status == case["expected_rule_status"]
    if case.get("expected_action") is not None and target.status == "applicable":
        assert target.conclusion["action"] == case["expected_action"]


def test_all_yaml_files_are_valid():
    for path in MODULE.rglob("*.yaml"):
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict), path


def test_rule_ids_are_unique():
    ids = []
    for filename in RULE_FILES:
        with (RULES / filename).open("r", encoding="utf-8") as f:
            ids.extend(r["id"] for r in yaml.safe_load(f)["rules"])
    assert len(ids) == len(set(ids))


def test_every_rule_preserves_esmo_evidence_block():
    for filename in RULE_FILES:
        with (RULES / filename).open("r", encoding="utf-8") as f:
            rules = yaml.safe_load(f)["rules"]
        for r in rules:
            ev = r["evidence"]
            assert ev["organization"] == "ESMO"
            assert "evidence_level" in ev["native"]
            assert "recommendation_grade" in ev["native"]
            assert "mcbs" in ev["native"]
            assert "explicit_grade_reported" in ev
