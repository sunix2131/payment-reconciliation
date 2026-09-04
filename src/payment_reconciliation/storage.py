from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
)

from payment_reconciliation.config import Rules
from payment_reconciliation.domain import ReconciliationReport

metadata = MetaData()

runs = Table(
    "reconciliation_run",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("internal_source", String(500), nullable=False),
    Column("external_source", String(500), nullable=False),
    Column("rules", JSON, nullable=False),
    Column("summary", JSON, nullable=False),
)

results = Table(
    "reconciliation_result",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "run_id",
        String(36),
        ForeignKey("reconciliation_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("status", String(40), nullable=False, index=True),
    Column("internal_ids", JSON, nullable=False),
    Column("external_ids", JSON, nullable=False),
    Column("score", Integer),
    Column("evidence", JSON, nullable=False),
)


def save_report(
    database_url: str,
    report: ReconciliationReport,
    rules: Rules,
    internal_source: Path,
    external_source: Path,
) -> str:
    engine = create_engine(database_url, pool_pre_ping=True)
    run_id = str(uuid4())
    serialized_rules = _json_value(asdict(rules))
    try:
        metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(
                insert(runs),
                {
                    "id": run_id,
                    "created_at": datetime.now(UTC),
                    "internal_source": internal_source.name,
                    "external_source": external_source.name,
                    "rules": serialized_rules,
                    "summary": report.summary(),
                },
            )
            serialized_results = [
                {
                    "run_id": run_id,
                    "status": item.status.value,
                    "internal_ids": list(item.internal_ids),
                    "external_ids": list(item.external_ids),
                    "score": item.score,
                    "evidence": list(item.evidence),
                }
                for item in report.items
            ]
            if serialized_results:
                connection.execute(insert(results), serialized_results)
    finally:
        engine.dispose()
    return run_id


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value
