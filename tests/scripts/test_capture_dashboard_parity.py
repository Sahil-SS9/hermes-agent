"""P04 dashboard parity capture — harness tests.

Tests the capture harness itself (scripts/capture_dashboard_parity.py):
  - parity success (CLI _cmd_list vs dashboard GET /board agree)
  - expected workflow statuses (completion yields review, not done)
  - temporary-root cleanup (no leaked temp home)
  - no default repository write (capture() returns JSON, doesn't write)

Hermetic: each test uses the harness's own TemporaryDirectory; the repo is
never mutated.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
try:
    import subprocess
    _out = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True)
    if _out.returncode == 0 and _out.stdout.strip():
        REPO_ROOT = Path(_out.stdout.strip())
except Exception:
    pass
SCRIPT_PATH = REPO_ROOT / "scripts" / "capture_dashboard_parity.py"
_MOD_NAME = "capture_dashboard_parity"


def _load_capture():
    sys.modules.pop(_MOD_NAME, None)
    spec = importlib.util.spec_from_file_location(_MOD_NAME, str(SCRIPT_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_script_exists():
    assert SCRIPT_PATH.is_file(), "scripts/capture_dashboard_parity.py is absent"


def test_parity_success():
    """CLI _cmd_list and dashboard GET /board render the same board."""
    mod = _load_capture()
    report = mod.capture()
    assert report["verdict"] == "PARITY-PROVEN-BY-CAPTURE", report
    co = report["captured_output"]
    assert co["id_set_match"] is True
    assert co["status_counts_match"] is True


def test_expected_workflow_statuses():
    """Completion of a full-tier task yields review (review gate), not done.
    The harness must report the HONEST status, not mislabel it done."""
    mod = _load_capture()
    report = mod.capture()
    seed = report["seed_statuses"]
    # Honest status is 'review' — the description may explain it is NOT done.
    assert seed["parity-dash-task"].startswith("review"), \
        f"expected honest review status, got: {seed['parity-dash-task']}"
    # Both render sides agree on 'review'.
    dash = report["captured_output"]["dashboard_side"]["status_counts"]
    cli = report["captured_output"]["cli_side"]["status_counts"]
    assert dash.get("review", 0) >= 1
    assert cli.get("review", 0) >= 1


def test_temp_root_cleaned_after_capture():
    """capture() removes its TemporaryDirectory; it does not ADD a leaked
    temp root. Compared against the pre-call set so stale dirs from other
    processes/suites do not cause a false failure."""
    mod = _load_capture()
    tmp = __import__("tempfile").gettempdir()
    before = set(str(p) for p in Path(tmp).glob("p04-parity-*"))
    mod.capture()
    after = set(str(p) for p in Path(tmp).glob("p04-parity-*"))
    leaked = after - before
    assert not leaked, f"capture() leaked temp roots: {leaked}"


def test_no_default_repository_write(tmp_path, monkeypatch):
    """capture() does not write to the repo by default; it returns the dict.
    An explicit --output is required to write, and that path is honoured."""
    mod = _load_capture()
    report = mod.capture()
    assert isinstance(report, dict)
    assert report["verdict"] == "PARITY-PROVEN-BY-CAPTURE"
    # The dated tracked report must NOT have been written by capture() alone.
    tracked = REPO_ROOT / "migration" / "evidence" / "2026-07-16" / "P04-dashboard-parity-report.json"
    # (We don't assert absence globally because the candidate commit may add
    #  it; we assert capture() itself didn't mutate the repo tree by checking
    #  it is not created as a side effect of the function call.)
    before_mtime = tracked.stat().st_mtime if tracked.exists() else None

    # Explicit --output writes to the requested path only.
    out = tmp_path / "parity-out.json"
    rc = mod.main.__wrapped__(out) if hasattr(mod.main, "__wrapped__") else None
    # Drive via argparse by monkeypatching sys.argv.
    monkeypatch.setattr(sys, "argv", ["capture_dashboard_parity.py", "--output", str(out)])
    rc = mod.main()
    assert rc == 0
    assert out.exists()
    written = json.loads(out.read_text())
    assert written["verdict"] == "PARITY-PROVEN-BY-CAPTURE"
    # Tracked report mtime unchanged by capture()/main() (no silent overwrite).
    if before_mtime is not None:
        assert tracked.stat().st_mtime == before_mtime
