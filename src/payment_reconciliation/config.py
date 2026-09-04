from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class Rules:
    exact_reference_weight: int = 100
    amount_weight: int = 50
    amount_tolerance: Decimal = Decimal("0.01")
    timestamp_weight: int = 20
    timestamp_tolerance_seconds: int = 300


def load_rules(path: Path) -> Rules:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("rules"), list):
        raise ValueError("rules file must contain a 'rules' list")

    rules = Rules()
    seen: set[str] = set()
    for raw_rule in payload["rules"]:
        if not isinstance(raw_rule, dict) or not isinstance(raw_rule.get("type"), str):
            raise ValueError("each rule must be an object with a string 'type'")
        rule_type = raw_rule["type"]
        if rule_type in seen:
            raise ValueError(f"rule {rule_type!r} is configured more than once")
        seen.add(rule_type)
        weight = _non_negative_int(raw_rule.get("weight"), f"{rule_type}.weight")

        if rule_type == "exact_reference":
            _reject_unknown(raw_rule, {"type", "weight"})
            rules = replace(rules, exact_reference_weight=weight)
        elif rule_type == "amount":
            _reject_unknown(raw_rule, {"type", "weight", "tolerance"})
            tolerance = _decimal(raw_rule.get("tolerance"), "amount.tolerance")
            if tolerance < 0:
                raise ValueError("amount.tolerance must not be negative")
            rules = replace(rules, amount_weight=weight, amount_tolerance=tolerance)
        elif rule_type == "timestamp":
            _reject_unknown(raw_rule, {"type", "weight", "tolerance_seconds"})
            tolerance_seconds = _non_negative_int(
                raw_rule.get("tolerance_seconds"), "timestamp.tolerance_seconds"
            )
            rules = replace(
                rules,
                timestamp_weight=weight,
                timestamp_tolerance_seconds=tolerance_seconds,
            )
        else:
            raise ValueError(f"unsupported rule type: {rule_type}")
    return rules


def _reject_unknown(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"unknown rule fields: {', '.join(sorted(unknown))}")


def _non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ValueError(f"{field} must be a decimal string or integer")
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f"{field} is not a decimal") from error
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result
