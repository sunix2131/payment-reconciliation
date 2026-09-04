from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from payment_reconciliation.domain import Source, Transaction

_REFERENCE_SEPARATOR = re.compile(r"[\W_]+", re.UNICODE)


def load_transactions(path: Path, source: Source) -> list[Transaction]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows: Iterable[dict[str, Any]] = csv.DictReader(stream)
            return _parse_rows(rows, source)
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
        if isinstance(payload, dict):
            payload = payload.get("transactions")
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise ValueError(f"{path}: JSON must be an array or a transactions array")
        return _parse_rows(payload, source)
    raise ValueError(f"{path}: expected a .csv or .json input file")


def normalize_reference(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = _REFERENCE_SEPARATOR.sub("", normalized)
    return normalized or None


def _parse_rows(rows: Iterable[dict[str, Any]], source: Source) -> list[Transaction]:
    transactions: list[Transaction] = []
    seen_ids: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        try:
            transaction_id = _required_string(row, "id")
            if transaction_id in seen_ids:
                raise ValueError(f"duplicate transaction id {transaction_id!r}")
            seen_ids.add(transaction_id)
            amount = _amount(row.get("amount"))
            currency = _required_string(row, "currency").upper()
            if len(currency) != 3 or not currency.isalpha() or not currency.isascii():
                raise ValueError("currency must be a three-letter ASCII code")
            timestamp = _timestamp(row.get("timestamp"))
            raw_reference = row.get("reference")
            reference = None if raw_reference is None else str(raw_reference).strip() or None
            transactions.append(
                Transaction(
                    id=transaction_id,
                    source=source,
                    amount=amount,
                    currency=currency,
                    timestamp=timestamp,
                    reference=reference,
                    normalized_reference=normalize_reference(reference),
                )
            )
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValueError(f"{source.value.lower()} row {row_number}: {error}") from error
    return transactions


def _required_string(row: dict[str, Any], field: str) -> str:
    value = row.get(field)
    if value is None or not str(value).strip():
        raise ValueError(f"{field} is required")
    return str(value).strip()


def _amount(value: object) -> Decimal:
    if isinstance(value, float):
        raise ValueError("amount must be encoded as a decimal string, not a JSON float")
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise ValueError("amount must be a finite decimal")
    return amount


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return parsed.astimezone(UTC)
