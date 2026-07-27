"""P13 isolation proof for scripts/wiki_daily_sync.sh.

Verifies the dry-run flag:
- WIKI_SYNC_DRY_RUN=1 prints the planned commands, exits 0, never runs git
- WIKI_SYNC_DIR can be redirected so the production wiki tree is untouched
- a missing WIKI_SYNC_DIR is reported with exit 1
"""
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = REPO_ROOT / "scripts" / "wiki_daily_sync.sh"


def _run(env_extra: dict | None = None):
    env = dict(os.environ)
    env.pop("WIKI_SYNC_DRY_RUN", None)
    env.pop("WIKI_SYNC_DIR", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(WRAPPER)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=15,
    )


def test_dry_run_exits_zero_without_git(tmp_path):
    """WIKI_SYNC_DRY_RUN=1 prints the plan and never touches git."""
    fake_wiki = tmp_path / "wiki"
    fake_wiki.mkdir()
    r = _run({"WIKI_SYNC_DRY_RUN": "1", "WIKI_SYNC_DIR": str(fake_wiki)})
    assert r.returncode == 0, r.stderr
    assert "dry-run:" in r.stdout
    # Nothing mutated in the fake tree (no .git operations).
    assert not (fake_wiki / ".git").exists()


def test_dry_run_works_even_when_dir_missing(tmp_path):
    """Dry-run must short-circuit BEFORE the cd guard so a missing dir
    does not cause exit 1 (the point of dry-run is to plan without
    requiring the workspace to exist)."""
    missing = tmp_path / "does-not-exist"
    r = _run({"WIKI_SYNC_DRY_RUN": "1", "WIKI_SYNC_DIR": str(missing)})
    assert r.returncode == 0, r.stderr
    assert "dry-run:" in r.stdout


def test_missing_dir_without_dry_run_exits_nonzero(tmp_path):
    """Without dry-run, a missing wiki dir must report an error and exit 1."""
    missing = tmp_path / "does-not-exist"
    r = _run({"WIKI_SYNC_DIR": str(missing)})
    assert r.returncode == 1
    assert "cannot cd" in r.stderr or "cannot cd" in r.stdout
