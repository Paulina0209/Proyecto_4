"""Pruebas técnicas del módulo ESMO de NSCLC temprano y localmente avanzado."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from core.engine import evaluate_rule_set


ROOT = Path(__file__).resolve().parents[2]
RULES = (
    ROOT
    / "guidelines"
    / "nsclc_early_locally_advanced"
    / "rules"
)
CASES_FILE = (
    Path(__file__).parent
    / "cases"
    / "esmo"
    / "nsclc_early_locally_advanced"
    / "cases.yaml"
)


def load_cases() -> list[dict[str, Any]]:
    """Carga los casos sintéticos y valida su estructura mínima."""

    with CASES_FILE.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise ValueError("cases.yaml debe contener un objeto YAML.")

    cases = data.get("cases")
    if not isinstance(cases, list):
        raise ValueError("cases.yaml debe contener una lista `cases`.")

    return cases


CASES = load_cases()


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_synthetic_case(case: dict[str, Any]) -> None:
    """Comprueba el estado y la conclusión esperados de cada caso."""

    expected = case["expected"]
    evaluations = evaluate_rule_set(RULES / case["rule_file"], case["facts"])

    target = next(
        (item for item in evaluations if item.rule_id == expected["rule_id"]),
        None,
    )

    assert target is not None, (
        f"No se encontró la regla {expected['rule_id']} "
        f"en {case['rule_file']}."
    )
    assert target.status == expected["status"]

    if "audit_effect" in expected:
        assert target.conclusion is not None
        assert target.conclusion["audit_effect"] == expected["audit_effect"]

    if "missing_fields" in expected:
        assert set(expected["missing_fields"]).issubset(target.missing_fields)


def test_case_identifiers_are_unique() -> None:
    """Evita duplicar casos durante la ampliación del banco sintético."""

    identifiers = [case["id"] for case in CASES]
    assert len(identifiers) == len(set(identifiers))


@pytest.mark.parametrize(
    ("filename", "rule_id"),
    [
        ("neoadjuvant.yaml", "ESMO-NSCLC-ELA-NEO-001"),
        ("perioperative.yaml", "ESMO-NSCLC-ELA-PERI-001"),
        ("adjuvant.yaml", "ESMO-NSCLC-ELA-ADJ-001"),
        ("adjuvant.yaml", "ESMO-NSCLC-ELA-ADJ-002"),
    ],
)
def test_positive_rules_preserve_native_esmo_evidence(
    filename: str,
    rule_id: str,
) -> None:
    """Verifica que la evidencia nativa no se pierda en reglas positivas."""

    with (RULES / filename).open("r", encoding="utf-8") as file:
        rules = yaml.safe_load(file)["rules"]

    rule = next(item for item in rules if item["id"] == rule_id)
    native = rule["evidence"]["native"]

    assert native["evidence_level"] == "I"
    assert native["recommendation_grade"] == "A"
    assert native["mcbs"] == {"version": "2.0", "score": "A (AT)"}
    assert rule["evidence"]["explicit_grade_reported"] is True


def test_adjuvant_rule_does_not_require_positive_pdl1() -> None:
    """PD-L1 de 0% no debe bloquear la recomendación adyuvante ESMO."""

    case = next(
        item
        for item in CASES
        if item["id"] == "adjuvant_only_after_platinum_supported_pdl1_zero"
    )
    evaluations = evaluate_rule_set(RULES / case["rule_file"], case["facts"])
    target = next(
        item
        for item in evaluations
        if item.rule_id == "ESMO-NSCLC-ELA-ADJ-002"
    )

    assert target.status == "applicable"
    assert target.conclusion is not None
    assert target.conclusion["pdl1_requirement"] == "none"
