"""Generic YAML rule evaluator.

The engine deliberately contains no disease, drug, or guideline-specific logic.
Clinical knowledge remains under ``guidelines/``.

Condition evaluation is three-valued:
- True  -> rule is ``applicable``
- False -> rule is ``not_applicable``
- None  -> rule is ``not_evaluable`` because required facts are missing

This preserves the architectural rule that missing clinical data must never be
silently interpreted as a negative finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RuleEvaluation:
    rule_id: str
    status: str
    conclusion: dict[str, Any] | None
    missing_fields: set[str] = field(default_factory=set)


def _leaf(condition: dict[str, Any], facts: dict[str, Any]) -> tuple[bool | None, set[str]]:
    field_name = condition.get("field")
    operator = condition.get("operator")
    expected = condition.get("value")

    if not field_name or not operator:
        raise ValueError(f"Invalid leaf condition: {condition!r}")

    if field_name not in facts or facts[field_name] is None:
        return None, {field_name}

    actual = facts[field_name]

    try:
        if operator == "equals":
            result = actual == expected
        elif operator == "not_equals":
            result = actual != expected
        elif operator == "in":
            result = actual in expected
        elif operator == "not_in":
            result = actual not in expected
        elif operator == "greater_than":
            result = actual > expected
        elif operator == "greater_than_or_equal":
            result = actual >= expected
        elif operator == "less_than":
            result = actual < expected
        elif operator == "less_than_or_equal":
            result = actual <= expected
        elif operator == "contains":
            result = expected in actual
        elif operator == "contains_all":
            result = all(item in actual for item in expected)
        elif operator == "contains_any":
            result = any(item in actual for item in expected)
        elif operator == "exact_set":
            result = set(actual) == set(expected)
        else:
            raise ValueError(f"Unsupported operator: {operator}")
    except TypeError:
        # A present but incompatible value is a failed condition, not a missing fact.
        result = False

    return bool(result), set()


def _evaluate_condition(condition: dict[str, Any], facts: dict[str, Any]) -> tuple[bool | None, set[str]]:
    if "all" in condition:
        missing: set[str] = set()
        saw_unknown = False
        for child in condition["all"]:
            value, child_missing = _evaluate_condition(child, facts)
            missing.update(child_missing)
            if value is False:
                return False, set()
            if value is None:
                saw_unknown = True
        return (None, missing) if saw_unknown else (True, set())

    if "any" in condition:
        missing: set[str] = set()
        saw_unknown = False
        for child in condition["any"]:
            value, child_missing = _evaluate_condition(child, facts)
            missing.update(child_missing)
            if value is True:
                return True, set()
            if value is None:
                saw_unknown = True
        return (None, missing) if saw_unknown else (False, set())

    if "not" in condition:
        value, missing = _evaluate_condition(condition["not"], facts)
        if value is None:
            return None, missing
        return (not value), set()

    return _leaf(condition, facts)


def evaluate_rule_set(rule_file: str | Path, facts: dict[str, Any]) -> list[RuleEvaluation]:
    """Evaluate every rule in a YAML rule-set against normalized clinical facts."""
    path = Path(rule_file)
    with path.open("r", encoding="utf-8-sig") as file:
        payload = yaml.safe_load(file)

    if not isinstance(payload, dict) or not isinstance(payload.get("rules"), list):
        raise ValueError(f"Invalid rule-set file: {path}")

    evaluations: list[RuleEvaluation] = []
    for rule in payload["rules"]:
        value, missing = _evaluate_condition(rule.get("conditions", {}), facts)
        if value is True:
            status = "applicable"
        elif value is False:
            status = "not_applicable"
        else:
            status = "not_evaluable"

        evaluations.append(
            RuleEvaluation(
                rule_id=rule["id"],
                status=status,
                conclusion=rule.get("conclusion"),
                missing_fields=missing,
            )
        )

    return evaluations
