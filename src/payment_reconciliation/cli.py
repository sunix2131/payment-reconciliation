from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from payment_reconciliation.config import load_rules
from payment_reconciliation.domain import Source
from payment_reconciliation.engine import reconcile
from payment_reconciliation.loaders import load_transactions
from payment_reconciliation.storage import save_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reconcile",
        description="Reconcile internal transactions against a bank or PSP statement.",
    )
    parser.add_argument("internal", type=Path, help="internal .csv or .json file")
    parser.add_argument("external", type=Path, help="external .csv or .json file")
    parser.add_argument("--rules", required=True, type=Path, help="matching rules YAML")
    parser.add_argument("--output", type=Path, help="write JSON report instead of stdout")
    parser.add_argument(
        "--database-url",
        help="optionally persist the run through SQLAlchemy (PostgreSQL recommended)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        rules = load_rules(args.rules)
        internal = load_transactions(args.internal, Source.INTERNAL)
        external = load_transactions(args.external, Source.EXTERNAL)
        report = reconcile(internal, external, rules)
        payload = report.as_dict()
        if args.database_url:
            payload["run_id"] = save_report(
                args.database_url,
                report,
                rules,
                args.internal,
                args.external,
            )
    except (OSError, ValueError) as error:
        parser.error(str(error))

    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
