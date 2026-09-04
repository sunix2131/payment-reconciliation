from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from payment_reconciliation.config import Rules
from payment_reconciliation.domain import Source, Status, Transaction
from payment_reconciliation.engine import reconcile
from payment_reconciliation.loaders import normalize_reference

NOW = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def transaction(
    transaction_id: str,
    source: Source,
    amount: str,
    reference: str | None,
    *,
    seconds: int = 0,
    currency: str = "EUR",
) -> Transaction:
    return Transaction(
        id=transaction_id,
        source=source,
        amount=Decimal(amount),
        currency=currency,
        timestamp=NOW + timedelta(seconds=seconds),
        reference=reference,
        normalized_reference=normalize_reference(reference),
    )


def test_exact_reference_amount_and_time_match() -> None:
    report = reconcile(
        [transaction("i1", Source.INTERNAL, "10.00", "Order-42")],
        [transaction("e1", Source.EXTERNAL, "10.00", " order 42 ", seconds=12)],
        Rules(),
    )

    assert len(report.items) == 1
    assert report.items[0].status is Status.MATCHED
    assert report.items[0].score == 170


def test_exact_reference_surfaces_amount_mismatch() -> None:
    report = reconcile(
        [transaction("i1", Source.INTERNAL, "10.00", "ORDER-42")],
        [transaction("e1", Source.EXTERNAL, "10.50", "ORDER-42", seconds=10)],
        Rules(),
    )

    assert report.items[0].status is Status.AMOUNT_MISMATCH
    assert report.items[0].internal_ids == ("i1",)
    assert report.items[0].external_ids == ("e1",)


def test_close_amount_and_time_surface_reference_mismatch() -> None:
    report = reconcile(
        [transaction("i1", Source.INTERNAL, "10.00", "ORDER-42")],
        [transaction("e1", Source.EXTERNAL, "10.01", "PSP-900", seconds=30)],
        Rules(),
    )

    assert report.items[0].status is Status.REFERENCE_MISMATCH
    assert report.items[0].score == 70


def test_unconnected_transactions_are_reported_on_both_sides() -> None:
    report = reconcile(
        [transaction("i1", Source.INTERNAL, "10", "INTERNAL")],
        [transaction("e1", Source.EXTERNAL, "30", "EXTERNAL", seconds=900)],
        Rules(),
    )

    assert report.summary()[Status.MISSING_EXTERNAL] == 1
    assert report.summary()[Status.MISSING_INTERNAL] == 1


def test_duplicate_references_are_quarantined_before_matching() -> None:
    report = reconcile(
        [
            transaction("i1", Source.INTERNAL, "10", "ORDER-42"),
            transaction("i2", Source.INTERNAL, "10", "order 42"),
        ],
        [transaction("e1", Source.EXTERNAL, "10", "ORDER-42")],
        Rules(),
    )

    duplicate = next(item for item in report.items if item.status is Status.DUPLICATE)
    assert duplicate.internal_ids == ("i1", "i2")
    assert report.summary()[Status.MISSING_INTERNAL] == 1


def test_equal_candidates_are_ambiguous_instead_of_guessed() -> None:
    report = reconcile(
        [transaction("i1", Source.INTERNAL, "10", None)],
        [
            transaction("e1", Source.EXTERNAL, "10", None, seconds=-10),
            transaction("e2", Source.EXTERNAL, "10", None, seconds=10),
        ],
        Rules(),
    )

    assert len(report.items) == 1
    assert report.items[0].status is Status.AMBIGUOUS
    assert report.items[0].external_ids == ("e1", "e2")


def test_mutual_best_resolution_does_not_depend_on_input_order() -> None:
    internal = [
        transaction("i-fuzzy", Source.INTERNAL, "10", "UNKNOWN"),
        transaction("i-exact", Source.INTERNAL, "10", "ORDER-42"),
    ]
    external = [transaction("e1", Source.EXTERNAL, "10", "ORDER-42", seconds=5)]

    forward = reconcile(internal, external, Rules())
    reverse = reconcile(list(reversed(internal)), external, Rules())

    assert forward == reverse
    matched = next(item for item in forward.items if item.status is Status.MATCHED)
    assert matched.internal_ids == ("i-exact",)
    assert forward.summary()[Status.MISSING_EXTERNAL] == 1


def test_identical_ids_across_sources_remain_distinct_records() -> None:
    report = reconcile(
        [transaction("same-id", Source.INTERNAL, "10", "ORDER-42")],
        [transaction("same-id", Source.EXTERNAL, "10", "ORDER-42")],
        Rules(),
    )

    assert report.items[0].status is Status.MATCHED
    assert report.items[0].internal_ids == ("same-id",)
    assert report.items[0].external_ids == ("same-id",)


def test_wrong_source_is_rejected() -> None:
    wrong = transaction("e1", Source.EXTERNAL, "10", "ORDER-42")
    with pytest.raises(ValueError, match="wrong source"):
        reconcile([wrong], [], Rules())


def test_refunds_reconcile_as_signed_decimal_amounts() -> None:
    report = reconcile(
        [transaction("i-refund", Source.INTERNAL, "-10.25", "REFUND-42")],
        [transaction("e-refund", Source.EXTERNAL, "-10.25", "refund 42")],
        Rules(),
    )

    assert report.items[0].status is Status.MATCHED
