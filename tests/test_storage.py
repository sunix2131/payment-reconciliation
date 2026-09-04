from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select

from payment_reconciliation.config import Rules
from payment_reconciliation.domain import ReconciliationItem, ReconciliationReport, Status
from payment_reconciliation.storage import results, runs, save_report


def report() -> ReconciliationReport:
    return ReconciliationReport(
        (
            ReconciliationItem(
                Status.MATCHED,
                ("internal-1",),
                ("external-1",),
                170,
                ("normalized reference equal",),
            ),
        )
    )


def test_report_is_persisted_atomically_to_sqlite(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'runs.db'}"
    run_id = save_report(
        database_url,
        report(),
        Rules(),
        Path("internal.csv"),
        Path("external.csv"),
    )

    engine = create_engine(database_url)
    with engine.connect() as connection:
        stored_run = connection.execute(select(runs).where(runs.c.id == run_id)).one()
        result_count = connection.scalar(
            select(func.count()).select_from(results).where(results.c.run_id == run_id)
        )
    assert stored_run.summary[Status.MATCHED] == 1
    assert stored_run.rules["amount_tolerance"] == "0.01"
    assert result_count == 1


def test_empty_report_persists_without_synthetic_result(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'empty.db'}"
    run_id = save_report(
        database_url,
        ReconciliationReport(()),
        Rules(),
        Path("internal.csv"),
        Path("external.csv"),
    )

    engine = create_engine(database_url)
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(runs)) == 1
        assert (
            connection.scalar(
                select(func.count()).select_from(results).where(results.c.run_id == run_id)
            )
            == 0
        )


@pytest.mark.postgres
def test_report_is_persisted_to_postgres() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not configured")

    run_id = save_report(
        database_url,
        report(),
        Rules(),
        Path("internal.csv"),
        Path("external.csv"),
    )
    engine = create_engine(database_url)
    with engine.connect() as connection:
        assert (
            connection.scalar(
                select(func.count()).select_from(results).where(results.c.run_id == run_id)
            )
            == 1
        )
