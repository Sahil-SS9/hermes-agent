"""P13 isolation proof for scripts/publish_to_postiz.sh.

Verifies the env override:
- POSTIZ_DRY_RUN=1 prints the dry-run line and exits 0 before invoking the
  Python publisher.
- The production content_engine / venv python is never reached.
"""
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "publish_to_postiz.sh"


def _run(env_extra=None):
    env = dict(os.environ)
    env.pop("POSTIZ_DRY_RUN", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env,
        cwd=str(REPO_ROOT), timeout=15,
    )


def test_dry_run_exits_zero_and_prints_plan(tmp_path):
    """POSTIZ_DRY_RUN=1 prints the plan and never reaches the publisher."""
    env = {"POSTIZ_DRY_RUN": "1", "HOME": str(tmp_path)}
    r = _run(env)
    assert r.returncode == 0, r.stderr
    assert "dry-run: would publish to Postiz" in r.stdout


def test_dry_run_never_invokes_python(tmp_path):
    """Dry-run must exit before the 'cd CE' + python publisher line.
    We prove this by pointing HOME to an empty dir — if the publisher ran it
    would fail on the missing content_engine, but dry-run exits 0 cleanly."""
    env = {"POSTIZ_DRY_RUN": "1", "HOME": str(tmp_path)}
    r = _run(env)
    assert r.returncode == 0, r.stderr
    # No traceback / no cd error because we short-circuit before cd.
    assert "No such file" not in r.stderr
    assert "Traceback" not in r.stderr
