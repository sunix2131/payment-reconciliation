from __future__ import annotations

import json
from pathlib import Path

import pytest

from payment_reconciliation.config import load_rules
from payment_reconciliation.domain import Source
from payment_reconciliation.loaders import load_transactions, normalize_reference


def test_reference_normalization_handles_unicode_case_and_separators() -> None:
    assert normalize_reference("  Invoice_№ \uff14\uff12 / ABC  ") == "invoiceno42abc"


def test_loader_requires_timezone(tmp_path: Path) -> None:
    path = tmp_path / "transactions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "i1",
                    "amount": "10.00",
                    "currency": "EUR",
                    "timestamp": "2026-08-01T09:00:00",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="UTC offset"):
        load_transactions(path, Source.INTERNAL)


def test_json_number_is_parsed_directly_as_decimal(tmp_path: Path) -> None:
    path = tmp_path / "transactions.json"
    path.write_text(
        '[{"id":"i1","amount":10.1,"currency":"EUR","timestamp":"2026-08-01T09:00:00Z"}]',
        encoding="utf-8",
    )

    transactions = load_transactions(path, Source.INTERNAL)

    assert str(transactions[0].amount) == "10.1"


def test_unknown_rule_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text("rules:\n  - type: fuzzy_magic\n    weight: 10\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported rule"):
        load_rules(path)


def test_decimal_tolerance_must_not_be_yaml_float(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text(
        "rules:\n  - type: amount\n    weight: 50\n    tolerance: 0.01\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="decimal string"):
        load_rules(path)
