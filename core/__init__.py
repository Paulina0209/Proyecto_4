"""Generic inference core for the class clinical copilot project."""

from .engine import RuleEvaluation, evaluate_rule_set

__all__ = ["RuleEvaluation", "evaluate_rule_set"]
