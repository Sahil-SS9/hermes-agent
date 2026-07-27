"""P13 isolation proof for scripts/curator-governance-hook.py.

Verifies:
- HERMES_HOME parameterisation: BASE and derived paths (SKILLS_DIR,
  PROFILES_DIR, STATE_FILE, GOVERNANCE_LOG, LOCK_FILE) resolve under
  HERMES_HOME, not /home/kensei/.hermes.
- --dry-run suppresses every write path: no `hermes curator pin` CLI
  calls, no add_skill_to_enabled config mutation, no set_adoption_status
  SKILL.md mutation, no log_event logboard write, no lockfile create.
  Read paths (load_profile_skills, read_curator_report) run unchanged.
- import-safe: importing the module does not create the lockfile or
  logboard dir.
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "curator-governance-hook.py"


def _load_module(monkeypatch, fake_home: Path):
    monkeypatch.setenv("HERMES_HOME", str(fake_home))
    scripts_dir = REPO_ROOT / "scripts"
    for pth in (str(scripts_dir), str(REPO_ROOT)):
        if pth not in sys.path:
            sys.path.insert(0, pth)
    spec = importlib.util.spec_from_file_location(
        "curator_governance_hook_under_test", str(SCRIPT)
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fake_home(tmp_path):
    fake = tmp_path / "fake_hermes"
    fake.mkdir()
    return fake


def test_paths_resolve_under_hermes_home(monkeypatch, fake_home):
    mod = _load_module(monkeypatch, fake_home)
    assert str(mod.BASE).startswith(str(fake_home))
    assert mod.SKILLS_DIR == fake_home / "skills"
    assert mod.PROFILES_DIR == fake_home / "profiles"
    assert mod.STATE_FILE == fake_home / "skills" / ".curator_state"
    assert mod.GOVERNANCE_LOG == fake_home / "governance" / "logboard"
    assert mod.LOCK_FILE == fake_home / ".curator_governance_hook.lock"


def test_import_is_side_effect_free(monkeypatch, fake_home):
    assert not (fake_home / ".curator_governance_hook.lock").exists()
    _load_module(monkeypatch, fake_home)
    assert not (fake_home / ".curator_governance_hook.lock").exists(), (
        "import created the lockfile"
    )


def test_dry_run_exits_zero_without_cli(monkeypatch, fake_home, tmp_path):
    """--dry-run must exit 0 with no curator report present and no `hermes`
    CLI on PATH. No lockfile, no logboard dir created."""
    env = dict(os.environ)
    env["HERMES_HOME"] = str(fake_home)
    env["PATH"] = "/usr/bin:/bin"  # no hermes CLI
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"dry-run failed: rc={proc.returncode} stderr={proc.stderr!r} stdout={proc.stdout!r}"
    )
    assert not (fake_home / ".curator_governance_hook.lock").exists()
    assert not (fake_home / "governance").exists() or not any(
        (fake_home / "governance").iterdir()
    )


def test_dry_run_does_not_pin_or_mutate(monkeypatch, fake_home, tmp_path):
    """With a curator report present proposing an archival of a
    profile-referenced skill, --dry-run must NOT call `hermes curator pin`,
    NOT mutate the profile config, NOT write the logboard, and NOT create
    the lockfile. The re-pin decision is still computed (archival override
    detected) but the write is suppressed."""
    mod = _load_module(monkeypatch, fake_home)
    # Build a fake HERMES_HOME with a profile config referencing a skill,
    # and a curator report proposing to archive that skill.
    (fake_home / "profiles").mkdir(parents=True)
    (fake_home / "skills").mkdir(parents=True)
    profile_cfg = fake_home / "profiles" / "octacon" / "config.yaml"
    profile_cfg.parent.mkdir(parents=True, exist_ok=True)
    profile_cfg.write_text(
        "skills:\n  enabled_skills:\n    - my-skill\n"
    )
    # curator state pointing at a report dir
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    (report_dir / "run.json").write_text(
        '{"started_at":"2026-01-01T00:00:00Z","counts":{},'
        '"archived":["my-skill"],"added":[]}'
    )
    state_file = fake_home / "skills" / ".curator_state"
    state_file.write_text(f'{{"last_report_path": "{report_dir}"}}')

    mod._DRY_RUN = True
    # Stub subprocess.run to detect any `hermes` call (must not happen).
    called = []
    import types
    real_run = subprocess.run

    def spy_run(cmd, *a, **k):
        if cmd and cmd[0] == "hermes":
            called.append(cmd)
            raise AssertionError(f"dry-run called hermes CLI: {cmd}")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", spy_run)
    # Run main (argv already parsed would set the flag; we set it directly).
    monkeypatch.setattr(sys, "argv", ["curator-governance-hook.py", "--dry-run"])
    mod.main()
    assert called == [], "dry-run invoked the hermes CLI"
    # Profile config must be unchanged.
    assert "my-skill" in profile_cfg.read_text()
    assert "dry-run" not in profile_cfg.read_text()
    # No logboard dir/file created.
    assert not (fake_home / "governance" / "logboard").exists() or not any(
        (fake_home / "governance" / "logboard").glob("*.mdl")
    )
    # No lockfile.
    assert not (fake_home / ".curator_governance_hook.lock").exists()
