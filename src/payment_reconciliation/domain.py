from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class Source(StrEnum):
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"


class Status(StrEnum):
    MATCHED = "MATCHED"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    MISSING_INTERNAL = "MISSING_INTERNAL"
    MISSING_EXTERNAL = "MISSING_EXTERNAL"
    DUPLICATE = "DUPLICATE"
    AMBIGUOUS = "AMBIGUOUS"
    REFERENCE_MISMATCH = "REFERENCE_MISMATCH"


@dataclass(frozen=True, slots=True)
class Transaction:
    id: str
    source: Source
    amount: Decimal
    currency: str
    timestamp: datetime
    reference: str | None
    normalized_reference: str | None


@dataclass(frozen=True, slots=True)
class Candidate:
    internal_id: str
    external_id: str
    score: int
    reference_equal: bool
    amount_difference: Decimal
    time_difference_seconds: int
    amount_within_tolerance: bool
    time_within_tolerance: bool


@dataclass(frozen=True, slots=True)
class ReconciliationItem:
    status: Status
    internal_ids: tuple[str, ...]
    external_ids: tuple[str, ...]
    score: int | None
    evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "internal_ids": list(self.internal_ids),
            "external_ids": list(self.external_ids),
            "score": self.score,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    items: tuple[ReconciliationItem, ...]

    def summary(self) -> dict[str, int]:
        counts = {status.value: 0 for status in Status}
        for item in self.items:
            counts[item.status.value] += 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "items": [item.as_dict() for item in self.items],
        }
