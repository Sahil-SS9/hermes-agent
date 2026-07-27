"""P13 dry-run contract test for scripts/content_x_scout.sh.

CONTENT_SCOUT_DRY_RUN=1 must short-circuit before any xurl fetch or Discord
inbox post. The script also sources .env via HERMES_HOME, not a hardcoded path.
"""
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "content_x_scout.sh"


def _run(env_extra=None):
    env = dict(os.environ)
    env.pop("CONTENT_SCOUT_DRY_RUN", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True,
        env=env, cwd=str(REPO_ROOT), timeout=15,
    )


def test_dry_run_exits_zero_and_prints_plan(tmp_path):
    """CONTENT_SCOUT_DRY_RUN=1 prints the dry-run line and exits 0."""
    env = {"CONTENT_SCOUT_DRY_RUN": "1", "HOME": str(tmp_path)}
    r = _run(env)
    assert r.returncode == 0, r.stderr
    assert "dry-run: would run x_scout" in r.stdout


def test_dry_run_never_invokes_python(tmp_path):
    """Dry-run must exit before the cd content_engine + python3 x_scout.py."""
    env = {"CONTENT_SCOUT_DRY_RUN": "1", "HOME": str(tmp_path)}
    r = _run(env)
    assert r.returncode == 0, r.stderr
    assert "No such file" not in r.stderr
    assert "Traceback" not in r.stderr


def test_respects_hermes_home():
    """The .env source must use HERMES_HOME, not a hardcoded path."""
    text = SCRIPT.read_text()
    assert "source /home/kensei/.hermes/.env" not in text, (
        "content_x_scout.sh: hardcoded /home/kensei/.hermes/.env source"
    )
    assert "HERMES_HOME" in text, (
        "content_x_scout.sh: does not reference HERMES_HOME for .env source"
    )
