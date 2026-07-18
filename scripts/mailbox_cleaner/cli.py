from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .clients import ReadAdapter
from .policy import AccountPolicy
from .runner import run_scheduled
from .state import StateStore


def _fixture_adapter(rows: list[dict[str, str]]) -> ReadAdapter:
    def read(operation: str, account: str) -> list[dict[str, str]]:
        if operation != "list_metadata":
            return []
        return [row for row in rows if row.get("account") == account]

    return read


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fixture-safe mailbox read-only report")
    parser.add_argument("--fixture", type=Path, required=True, help="local metadata JSON fixture")
    parser.add_argument("--state", type=Path, required=True, help="local private dedupe state")
    args = parser.parse_args(argv)
    rows = json.loads(args.fixture.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        parser.error("fixture must be a JSON list of metadata objects")
    policies = [
        AccountPolicy(account=str(row["account"]), provider=str(row["provider"]))
        for row in rows
    ]
    unique_policies = list(dict.fromkeys(policies))
    report = run_scheduled(unique_policies, _fixture_adapter(rows), StateStore(args.state))
    print(report.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
