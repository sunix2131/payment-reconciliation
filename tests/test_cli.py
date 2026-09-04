from __future__ import annotations

import json
from pathlib import Path

from payment_reconciliation.cli import main


def test_example_cli_report(tmp_path: Path) -> None:
    project = Path(__file__).parents[1]
    output = tmp_path / "report.json"

    exit_code = main(
        [
            str(project / "examples/internal.csv"),
            str(project / "examples/external.csv"),
            "--rules",
            str(project / "examples/rules.yaml"),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["summary"]["MATCHED"] == 1
    assert payload["summary"]["AMOUNT_MISMATCH"] == 1
    assert payload["summary"]["MISSING_EXTERNAL"] == 1
    assert payload["summary"]["MISSING_INTERNAL"] == 1
