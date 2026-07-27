"""P13 isolation proof for scripts/config-drift-check.py.

Verifies config-drift-check.py:
- reads HERMES_HOME-derived config.yaml (not a hard-coded absolute path)
- silent + exit 0 when enabled_skills exactly matches the expected set
- reports drift labels + exit 1 when one missing + one extra
- prints "[DRIFT] Check failed:" + exit 2 on malformed YAML
- never mutates the config file (hash fixture before/after)
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "config-drift-check.py"

# The expected set must mirror the script's own `expected` literal. We assert
# a contract: with the exact set, exit 0 and empty stdout. We do NOT freeze the
# literal contents here (the script's expected set is intentionally editable);
# we import it to reuse the current value.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("_drift_probe", SCRIPT)
_probe = importlib.util.module_from_spec(_spec)
# Stop exec at import — the script runs code at module top level, so we exec it
# in a sandboxed env where the open() raises FileNotFoundError, then read the
# `expected` constant. Simpler: parse the literal via a temp HERMES_HOME.
# Instead, exec the module with a bogus config path so the try/except catches.
_orig_open = open
def _bump(*a, **k):
    raise FileNotFoundError("sandbox")
import builtins
builtins.open = _bump
try:
    _spec.loader.exec_module(_probe)
except SystemExit:
    pass
finally:
    builtins.open = _orig_open
EXPECTED_SET = _probe.expected


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _run(hermes_home: Path):
    env = dict(os.environ)
    env["HERMES_HOME"] = str(hermes_home)
    # Strip a possibly-inherited HERMES_KANBAN_DB so no leak.
    env.pop("HERMES_KANBAN_DB", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(REPO_ROOT),
    )


def _write_config(hermes_home: Path, skills: list[str]) -> Path:
    cfg = hermes_home / "config.yaml"
    import yaml
    cfg.write_text(yaml.safe_dump({"skills": {"enabled_skills": skills}}))
    return cfg


def test_exact_expected_set_is_silent_exit_0(tmp_path):
    home = tmp_path / "hermes"
    home.mkdir()
    cfg = _write_config(home, sorted(EXPECTED_SET))
    before = _sha(cfg)
    r = _run(home)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""
    assert _sha(cfg) == before, "config mutated"


def test_one_missing_one_extra_reports_drift_exit_1(tmp_path):
    home = tmp_path / "hermes"
    home.mkdir()
    # remove one expected, add one unknown
    skills = sorted(EXPECTED_SET - {"arxiv"} | {"bogus-extra-skill"})
    cfg = _write_config(home, skills)
    before = _sha(cfg)
    r = _run(home)
    assert r.returncode == 1, r.stderr
    assert "[DRIFT]" in r.stdout
    assert "arxiv" in r.stdout, "missing skill not named"
    assert "bogus-extra-skill" in r.stdout, "extra skill not named"
    assert _sha(cfg) == before


def test_malformed_yaml_reports_check_failed_exit_2(tmp_path):
    home = tmp_path / "hermes"
    home.mkdir()
    cfg = home / "config.yaml"
    cfg.write_text("skills: {enabled_skills: [unterminated\n")
    before = _sha(cfg)
    r = _run(home)
    assert r.returncode == 2, r.stderr
    assert "[DRIFT] Check failed" in r.stdout
    assert _sha(cfg) == before


def test_resolves_via_hermes_home_env_not_hardcoded_path(tmp_path):
    """If the script still hard-codes /home/kensei/.hermes/config.yaml it will
    either FileNotFoundError (no such file under the temp) or read the real
    file. Either way the exact-match case fails. This is the RED guard."""
    home = tmp_path / "hermes"
    home.mkdir()
    _write_config(home, sorted(EXPECTED_SET))
    r = _run(home)
    # Must succeed against the temp HERMES_HOME, proving env-resolution.
    assert r.returncode == 0, (
        f"script did not honour HERMES_HOME (hard-coded path?). "
        f"rc={r.returncode} stdout={r.stdout!r} stderr={r.stderr!r}"
    )
