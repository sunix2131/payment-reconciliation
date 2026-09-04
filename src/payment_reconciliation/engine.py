from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict, deque
from collections.abc import Iterable
from datetime import timedelta

from payment_reconciliation.config import Rules
from payment_reconciliation.domain import (
    Candidate,
    ReconciliationItem,
    ReconciliationReport,
    Source,
    Status,
    Transaction,
)

_STATUS_ORDER = {status: index for index, status in enumerate(Status)}


def reconcile(
    internal: Iterable[Transaction], external: Iterable[Transaction], rules: Rules
) -> ReconciliationReport:
    internal_transactions = tuple(internal)
    external_transactions = tuple(external)
    _validate_sources(internal_transactions, Source.INTERNAL)
    _validate_sources(external_transactions, Source.EXTERNAL)

    duplicate_items, duplicate_internal_ids, duplicate_external_ids = _find_duplicates(
        internal_transactions, external_transactions
    )
    eligible_internal = tuple(
        tx for tx in internal_transactions if tx.id not in duplicate_internal_ids
    )
    eligible_external = tuple(
        tx for tx in external_transactions if tx.id not in duplicate_external_ids
    )

    candidates = _generate_candidates(eligible_internal, eligible_external, rules)
    matches, ambiguous_items, resolved_internal, resolved_external = _resolve_candidates(candidates)

    internal_by_id = {tx.id: tx for tx in eligible_internal}
    external_by_id = {tx.id: tx for tx in eligible_external}
    match_items = [_matched_item(candidate, rules) for candidate in matches]
    missing_items = [
        ReconciliationItem(Status.MISSING_EXTERNAL, (tx.id,), (), None, ("no candidate",))
        for tx in eligible_internal
        if tx.id not in resolved_internal
    ]
    missing_items.extend(
        ReconciliationItem(Status.MISSING_INTERNAL, (), (tx.id,), None, ("no candidate",))
        for tx in eligible_external
        if tx.id not in resolved_external
    )

    items = duplicate_items + match_items + ambiguous_items + missing_items
    items.sort(key=_item_sort_key)

    used_internal = {tx_id for item in items for tx_id in item.internal_ids}
    used_external = {tx_id for item in items for tx_id in item.external_ids}
    if used_internal != set(internal_by_id) | duplicate_internal_ids:
        raise AssertionError("internal reconciliation coverage invariant failed")
    if used_external != set(external_by_id) | duplicate_external_ids:
        raise AssertionError("external reconciliation coverage invariant failed")
    return ReconciliationReport(tuple(items))


def _validate_sources(transactions: tuple[Transaction, ...], expected: Source) -> None:
    ids: set[str] = set()
    for transaction in transactions:
        if transaction.source is not expected:
            raise ValueError(f"transaction {transaction.id!r} has the wrong source")
        if transaction.id in ids:
            raise ValueError(f"duplicate transaction id {transaction.id!r}")
        ids.add(transaction.id)


def _find_duplicates(
    internal: tuple[Transaction, ...], external: tuple[Transaction, ...]
) -> tuple[list[ReconciliationItem], set[str], set[str]]:
    items: list[ReconciliationItem] = []
    duplicate_internal_ids: set[str] = set()
    duplicate_external_ids: set[str] = set()
    for source, transactions in (
        (Source.INTERNAL, internal),
        (Source.EXTERNAL, external),
    ):
        by_reference: dict[tuple[str, str], list[str]] = defaultdict(list)
        for transaction in transactions:
            if transaction.normalized_reference is not None:
                by_reference[(transaction.currency, transaction.normalized_reference)].append(
                    transaction.id
                )
        for (currency, reference), ids in sorted(by_reference.items()):
            if len(ids) < 2:
                continue
            sorted_ids = tuple(sorted(ids))
            if source is Source.INTERNAL:
                duplicate_internal_ids.update(sorted_ids)
            else:
                duplicate_external_ids.update(sorted_ids)
            items.append(
                ReconciliationItem(
                    status=Status.DUPLICATE,
                    internal_ids=sorted_ids if source is Source.INTERNAL else (),
                    external_ids=sorted_ids if source is Source.EXTERNAL else (),
                    score=None,
                    evidence=(f"duplicate normalized reference {reference!r} in {currency}",),
                )
            )
    return items, duplicate_internal_ids, duplicate_external_ids


def _generate_candidates(
    internal: tuple[Transaction, ...], external: tuple[Transaction, ...], rules: Rules
) -> tuple[Candidate, ...]:
    by_currency: dict[str, list[Transaction]] = defaultdict(list)
    by_reference: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    for transaction in external:
        by_currency[transaction.currency].append(transaction)
        if transaction.normalized_reference is not None:
            by_reference[(transaction.currency, transaction.normalized_reference)].append(
                transaction
            )
    for transactions in by_currency.values():
        transactions.sort(key=lambda tx: (tx.timestamp, tx.id))

    candidates: list[Candidate] = []
    tolerance = timedelta(seconds=rules.timestamp_tolerance_seconds)
    for internal_tx in internal:
        currency_transactions = by_currency.get(internal_tx.currency, [])
        timestamps = [transaction.timestamp for transaction in currency_transactions]
        start = bisect_left(timestamps, internal_tx.timestamp - tolerance)
        end = bisect_right(timestamps, internal_tx.timestamp + tolerance)
        possible = {transaction.id: transaction for transaction in currency_transactions[start:end]}
        if internal_tx.normalized_reference is not None:
            for transaction in by_reference.get(
                (internal_tx.currency, internal_tx.normalized_reference), []
            ):
                possible[transaction.id] = transaction

        for external_tx in possible.values():
            amount_difference = abs(internal_tx.amount - external_tx.amount)
            time_difference = int(
                abs((internal_tx.timestamp - external_tx.timestamp).total_seconds())
            )
            reference_equal = (
                internal_tx.normalized_reference is not None
                and internal_tx.normalized_reference == external_tx.normalized_reference
            )
            amount_close = amount_difference <= rules.amount_tolerance
            time_close = time_difference <= rules.timestamp_tolerance_seconds
            if not reference_equal and not (amount_close and time_close):
                continue
            score = (
                (rules.exact_reference_weight if reference_equal else 0)
                + (rules.amount_weight if amount_close else 0)
                + (rules.timestamp_weight if time_close else 0)
            )
            candidates.append(
                Candidate(
                    internal_id=internal_tx.id,
                    external_id=external_tx.id,
                    score=score,
                    reference_equal=reference_equal,
                    amount_difference=amount_difference,
                    time_difference_seconds=time_difference,
                    amount_within_tolerance=amount_close,
                    time_within_tolerance=time_close,
                )
            )
    return tuple(
        sorted(candidates, key=lambda edge: (-edge.score, edge.internal_id, edge.external_id))
    )


def _resolve_candidates(
    candidates: tuple[Candidate, ...],
) -> tuple[list[Candidate], list[ReconciliationItem], set[str], set[str]]:
    remaining = list(candidates)
    matches: list[Candidate] = []
    resolved_internal: set[str] = set()
    resolved_external: set[str] = set()

    while remaining:
        unique_internal = _unique_best(remaining, by_internal=True)
        unique_external = _unique_best(remaining, by_internal=False)
        mutual = [
            edge
            for edge in remaining
            if unique_internal.get(edge.internal_id) == edge
            and unique_external.get(edge.external_id) == edge
        ]
        if not mutual:
            break
        matched_internal = {edge.internal_id for edge in mutual}
        matched_external = {edge.external_id for edge in mutual}
        matches.extend(mutual)
        resolved_internal.update(matched_internal)
        resolved_external.update(matched_external)
        remaining = [
            edge
            for edge in remaining
            if edge.internal_id not in matched_internal and edge.external_id not in matched_external
        ]

    ambiguous_items: list[ReconciliationItem] = []
    for component in _candidate_components(remaining):
        internal_ids = tuple(sorted({edge.internal_id for edge in component}))
        external_ids = tuple(sorted({edge.external_id for edge in component}))
        resolved_internal.update(internal_ids)
        resolved_external.update(external_ids)
        ambiguous_items.append(
            ReconciliationItem(
                status=Status.AMBIGUOUS,
                internal_ids=internal_ids,
                external_ids=external_ids,
                score=max(edge.score for edge in component),
                evidence=("no unique mutual-best one-to-one assignment",),
            )
        )
    return matches, ambiguous_items, resolved_internal, resolved_external


def _unique_best(candidates: list[Candidate], *, by_internal: bool) -> dict[str, Candidate]:
    grouped: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        key = candidate.internal_id if by_internal else candidate.external_id
        grouped[key].append(candidate)

    result: dict[str, Candidate] = {}
    for key, edges in grouped.items():
        best_score = max(edge.score for edge in edges)
        best = [edge for edge in edges if edge.score == best_score]
        if len(best) == 1:
            result[key] = best[0]
    return result


def _candidate_components(candidates: list[Candidate]) -> list[list[Candidate]]:
    edges_by_node: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        edges_by_node["i:" + candidate.internal_id].append(candidate)
        edges_by_node["e:" + candidate.external_id].append(candidate)

    components: list[list[Candidate]] = []
    visited: set[str] = set()
    for start in sorted(edges_by_node):
        if start in visited:
            continue
        queue = deque([start])
        component_edges: set[Candidate] = set()
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            for edge in edges_by_node[node]:
                component_edges.add(edge)
                neighbors = ("i:" + edge.internal_id, "e:" + edge.external_id)
                queue.extend(neighbor for neighbor in neighbors if neighbor not in visited)
        if component_edges:
            components.append(
                sorted(component_edges, key=lambda edge: (edge.internal_id, edge.external_id))
            )
    return components


def _matched_item(candidate: Candidate, rules: Rules) -> ReconciliationItem:
    if not candidate.amount_within_tolerance:
        status = Status.AMOUNT_MISMATCH
    elif not candidate.reference_equal:
        status = Status.REFERENCE_MISMATCH
    else:
        status = Status.MATCHED

    evidence = [f"amount difference {candidate.amount_difference}"]
    if candidate.reference_equal:
        evidence.append("normalized reference equal")
    else:
        evidence.append("normalized reference differs or is missing")
    evidence.append(f"timestamp difference {candidate.time_difference_seconds}s")
    if not candidate.time_within_tolerance:
        evidence.append(
            f"timestamp outside configured {rules.timestamp_tolerance_seconds}s tolerance"
        )
    return ReconciliationItem(
        status=status,
        internal_ids=(candidate.internal_id,),
        external_ids=(candidate.external_id,),
        score=candidate.score,
        evidence=tuple(evidence),
    )


def _item_sort_key(item: ReconciliationItem) -> tuple[int, tuple[str, ...], tuple[str, ...]]:
    return (_STATUS_ORDER[item.status], item.internal_ids, item.external_ids)
