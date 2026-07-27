from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cron_stale_monitor.py"


def _module():
    spec = importlib.util.spec_from_file_location("cron_stale_monitor", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_receipt_scope_reports_only_restored_p13_jobs(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    module = _module()
    jobs_file = tmp_path / "jobs.json"
    monkeypatch.setattr(module, "JOBS_FILE", jobs_file, raising=False)
    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path / "output", raising=False)
    jobs_file.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "p13-job",
                        "name": "P13 restored check",
                        "enabled": True,
                        "state": "scheduled",
                        "created_at": "2020-01-01T00:00:00+00:00",
                        "last_run_at": None,
                        "schedule": {"display": "every 1h"},
                    },
                    {
                        "id": "legacy-job",
                        "name": "Unrelated legacy check",
                        "enabled": True,
                        "state": "scheduled",
                        "created_at": "2020-01-01T00:00:00+00:00",
                        "last_run_at": None,
                        "schedule": {"display": "every 1h"},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    receipt = tmp_path / "p13-receipt.json"
    receipt.write_text(json.dumps({"jobs": [{"target_id": "p13-job"}]}), encoding="utf-8")

    assert module.main(receipt) == 0

    output = capsys.readouterr().out
    assert "P13 restored check" in output
    assert "Unrelated legacy check" not in output


def test_cli_accepts_receipt_path(tmp_path: Path) -> None:
    module = _module()
    receipt = tmp_path / "p13-receipt.json"

    assert module._parse_args(["--receipt", str(receipt)]).receipt == receipt
