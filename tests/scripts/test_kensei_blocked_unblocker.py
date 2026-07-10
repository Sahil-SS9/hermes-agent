"""Invariants for the kensei-blocked-unblocker pre-check (human-owned skip).

The cron pre-check at ``scripts/kensei-blocked-unblocker.py`` runs as a
no_agent=True script that the scheduler invokes from
``HERMES_HOME/scripts/kensei-blocked-unblocker.py``. It is the gate that
decides whether the LLM agent that follows it gets woken up — so a bug
here either wakes the agent on garbage or, worse, makes it act on tasks
that are already human-owned.

These tests pin three contracts:

  1. **Unit tests for ``_classify_row``** — the row-classification
     helper that decides per-row whether to skip a human-owned task,
     skip a too-young task, stop at MAX_TASKS, or include the row. Loaded
     from the live script via importlib (so we test the file the cron
     actually runs, not a stale copy in the repo's scripts/ dir).

  2. **Integration test** — drives the real script as a subprocess
     against a fake HERMES_HOME with two blocked tasks (one
     human-owned, one auto-recoverable) and asserts the human-owned
     task is filtered out and the auto-recoverable one is in the JSON
     output.

  3. **status='blocked' filter** — the SQL pre-filter excludes the
     ``decision-needed`` status (a terminal human-gated state set by
     ``block_task``), so the script never even sees decision-needed
     tasks in its row loop. Tested via the live SQL.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

# Path to the LIVE script the cron scheduler runs (HERMES_HOME/scripts/
# in the scripts profile). This is intentionally NOT the repo's
# scripts/kensei-blocked-unblocker.py — those copies can diverge and the
# cron reads from HERMES_HOME, not from the repo. Tests load THIS file
# via importlib to exercise the production code path.
LIVE_SCRIPT = (
    Path.home() / ".hermes" / "profiles" / "scripts" / "kensei-blocked-unblocker.py"
)


def _load_live_module(monkeypatch, fake_home: Path):
    """Import the live script with HERMES pointed at fake_home.

    The script's top-level code reads ``HERMES = Path(os.path.expanduser
    ("~/.hermes"))`` and immediately calls ``discover_boards()`` +
    iterates per-board. We monkey-patch ``os.path.expanduser`` so the
    module thinks ``~`` is fake_home; non-tilde paths fall through to
    the real ``os.path.expanduser``.
    """
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("HERMES_HOME", str(fake_home))
    real_expanduser = os.path.expanduser
    monkeypatch.setattr(
        os.path, "expanduser",
        lambda p: str(fake_home) if p == "~" else real_expanduser(p),
    )
    spec = importlib.util.spec_from_file_location(
        "kensei_blocked_unblocker_under_test", str(LIVE_SCRIPT)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """An empty HERMES_HOME pointing at tmp_path. No real DBs are touched."""
    fake = tmp_path / "fake_hermes"
    fake.mkdir()
    return fake


@pytest.fixture
def live_module(fake_home, monkeypatch):
    """Load the live script with HERMES pointed at fake_home."""
    return _load_live_module(monkeypatch, fake_home)


def _row(**overrides):
    """A minimal blocked-task row matching the script's SELECT shape."""
    base = {
        "id": "t_test",
        "title": "Test task",
        "assignee": "tester",
        "priority": 0,
        "status_reason": "",
        "created_at": 0,
        "updated_at": 0,
        "consecutive_failures": 0,
        "max_retries": None,
        "escalation_target": None,
        "block_kind": None,
        "body_snippet": "",
    }
    base.update(overrides)
    return base


# ── Unit tests for _classify_row ────────────────────────────────────────────


def test_classify_skip_human_owned_when_escalation_target_set(live_module):
    """A blocked row with escalation_target set must be classified as
    skip_human_owned — the cron must not surface it for auto-unblock or
    escalation. This is the core contract the parent task added.
    """
    row = _row(escalation_target="sahil", block_kind="needs_input")
    action, payload = live_module._classify_row(row, now=1_000_000, max_tasks=50, blocked_tasks_len=0)
    assert action == "skip_human_owned"
    assert payload == {
        "escalation_target": "sahil",
        "block_kind": "needs_input",
    }


def test_classify_skip_human_owned_with_capability_block_kind(live_module):
    """The skip applies regardless of block_kind — a stakeholder
    escalation overrides any auto-recovery intent, even for capability
    blocks where auto-repair might otherwise be appropriate.
    """
    row = _row(escalation_target="sahil", block_kind="capability")
    action, _ = live_module._classify_row(row, now=1_000_000, max_tasks=50, blocked_tasks_len=0)
    assert action == "skip_human_owned"


def test_classify_skip_human_owned_with_empty_block_kind(live_module):
    """Older rows may have escalation_target set but block_kind NULL
    (legacy data). Skip must still fire.
    """
    row = _row(escalation_target="sahil", block_kind=None)
    action, payload = live_module._classify_row(row, now=1_000_000, max_tasks=50, blocked_tasks_len=0)
    assert action == "skip_human_owned"
    assert payload["block_kind"] == ""


def test_classify_include_when_escalation_target_null_and_old_enough(live_module):
    """A blocked row with escalation_target NULL and updated_at older
    than ESCALATION_AGE must be classified as include.
    """
    now = 1_000_000
    old = now - live_module.ESCALATION_AGE - 1
    row = _row(escalation_target=None, updated_at=old)
    action, _ = live_module._classify_row(row, now=now, max_tasks=50, blocked_tasks_len=0)
    assert action == "include"


def test_classify_skip_too_young_when_recently_updated(live_module):
    """A row updated more recently than ESCALATION_AGE is filtered out
    by the existing age check, not the new pre-check.
    """
    now = 1_000_000
    recent = now - 10  # 10 seconds old
    row = _row(escalation_target=None, updated_at=recent)
    action, _ = live_module._classify_row(row, now=now, max_tasks=50, blocked_tasks_len=0)
    assert action == "skip_too_young"


def test_classify_stop_when_max_tasks_reached(live_module):
    """The MAX_TASKS cap fires before any other check, so a human-owned
    row would not even be classified once the cap is hit (caller breaks
    out of the per-board loop).
    """
    row = _row(escalation_target=None, updated_at=0)
    action, _ = live_module._classify_row(row, now=1_000_000, max_tasks=10, blocked_tasks_len=10)
    assert action == "stop"


def test_classify_skip_when_timestamps_missing(live_module):
    """Defensive: if both updated_at and created_at are NULL, the row is
    dropped (no basis to compute age). Mirrors the pre-existing
    behaviour in the script.
    """
    row = _row(escalation_target=None, updated_at=None, created_at=None)
    action, _ = live_module._classify_row(row, now=1_000_000, max_tasks=50, blocked_tasks_len=0)
    assert action == "skip_too_young"


# ── SQL filter: status='blocked' excludes decision-needed ───────────────────


def test_classify_does_not_explicitly_check_status(live_module):
    """The status='blocked' filter lives in the SQL, not in
    _classify_row. _classify_row only sees rows that already passed the
    filter; this test pins that _classify_row is intentionally
    status-agnostic and the SQL is what enforces the decision-needed
    exclusion.
    """
    # A 'decision-needed' row passed in directly would be classified
    # based on its escalation_target / age — the SQL is what keeps it
    # out. This test documents that contract.
    row = _row(
        id="t_dec",
        escalation_target="sahil",  # the SQL filter would not show this
        block_kind="needs_input",
    )
    action, _ = live_module._classify_row(row, now=1_000_000, max_tasks=50, blocked_tasks_len=0)
    # The classifier still says skip_human_owned, but the SQL is the
    # primary gate for decision-needed status. The unit test for the
    # SQL itself is in tests/hermes_cli/test_kanban_db.py.
    assert action == "skip_human_owned"


# ── Integration test: end-to-end with a real DB ────────────────────────────


def _populate_board_db(path: Path, tasks: list[dict]) -> None:
    """Create a minimal kanban_tasks schema with the columns the
    script's SELECT reads, then insert the given tasks.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                title TEXT,
                assignee TEXT,
                priority INTEGER,
                status TEXT,
                status_reason TEXT,
                body TEXT,
                created_at INTEGER,
                updated_at INTEGER,
                consecutive_failures INTEGER,
                max_retries INTEGER,
                escalation_target TEXT,
                block_kind TEXT
            )
            """
        )
        for t in tasks:
            conn.execute(
                """
                INSERT INTO tasks (
                    id, title, assignee, priority, status, status_reason,
                    body, created_at, updated_at, consecutive_failures,
                    max_retries, escalation_target, block_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    t["id"],
                    t["title"],
                    t.get("assignee", "tester"),
                    t.get("priority", 0),
                    t["status"],
                    t.get("status_reason", ""),
                    t.get("body", ""),
                    t.get("created_at", 0),
                    t.get("updated_at", 0),
                    t.get("consecutive_failures", 0),
                    t.get("max_retries"),
                    t.get("escalation_target"),
                    t.get("block_kind"),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def test_integration_skips_human_owned_blocks_via_subprocess(tmp_path, monkeypatch):
    """Run the LIVE script as a subprocess against a fake HERMES_HOME
    with a board containing both a human-owned and an auto-recoverable
    blocked task. Assert the human-owned one is in stderr (skip log),
    the auto-recoverable one is in the JSON output, and the new
    skipped_human_owned diag field is set.
    """
    fake_home = tmp_path / "fake_hermes_root"
    fake_home.mkdir()
    # Script reads ``HERMES = Path(os.path.expanduser("~/.hermes"))``, so
    # with HOME=fake_home it will look under ``fake_home/.hermes/`` for
    # the kanban DB layout. Mirror that here.
    hermes_dir = fake_home / ".hermes"
    board_dir = hermes_dir / "kanban" / "boards" / "test_board"
    db_path = board_dir / "kanban.db"

    now = int(os.environ.get("SOURCE_DATE_EPOCH", "1700000000"))
    old_updated = now - 7200  # well past ESCALATION_AGE

    _populate_board_db(
        db_path,
        [
            {
                "id": "t_human",
                "title": "Stakeholder decision needed",
                "status": "blocked",
                "escalation_target": "sahil",
                "block_kind": "needs_input",
                "updated_at": old_updated,
            },
            {
                "id": "t_auto",
                "title": "Routine auto-recoverable",
                "status": "blocked",
                "escalation_target": None,
                "block_kind": "transient",
                "updated_at": old_updated,
            },
            {
                "id": "t_decision",
                "title": "Terminal decision-needed",
                "status": "decision-needed",
                "escalation_target": "sahil",
                "block_kind": "needs_input",
                "updated_at": old_updated,
            },
            {
                "id": "t_done",
                "title": "Already done",
                "status": "done",
                "escalation_target": None,
                "updated_at": old_updated,
            },
        ],
    )

    # Run the LIVE script with HOME pointed at fake_home. KENSEI env
    # vars are reset to defaults so ESCALATION_AGE / MAX_TASKS are
    # predictable.
    env = {
        **os.environ,
        "HOME": str(fake_home),
        "HERMES_HOME": str(fake_home),
        "KENSEI_UNBLOCKER_AGE": "3600",
        "KENSEI_UNBLOCKER_MAX": "50",
        "PYTHONPATH": "",  # avoid leaking the real project root
    }
    proc = subprocess.run(
        [sys.executable, str(LIVE_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    # The script exits 0 when there are tasks to act on.
    assert proc.returncode == 0, (
        f"script failed: stderr={proc.stderr!r} stdout={proc.stdout!r}"
    )

    # Parse stderr into per-line JSON records (the script emits one
    # JSON object per skip line + one diagnostic record at the end).
    stderr_lines = [line for line in proc.stderr.splitlines() if line.strip()]
    parsed = [json.loads(line) for line in stderr_lines]
    skip_lines = [p for p in parsed if "skip_human_owned" in p]
    diag = next((p for p in parsed if "blocked_found" in p), None)
    assert diag is not None, (
        f"no diag record found in stderr. full stderr={proc.stderr!r} "
        f"stdout={proc.stdout!r} boards={diag}"
    )

    # The human-owned blocked task must be in the skip log.
    human_skips = [s["skip_human_owned"] for s in skip_lines if s["skip_human_owned"]["id"] == "t_human"]
    assert len(human_skips) == 1, f"expected t_human to be skipped: {skip_lines!r}"
    assert human_skips[0]["escalation_target"] == "sahil"
    assert human_skips[0]["block_kind"] == "needs_input"
    assert human_skips[0]["board"] == "test_board"
    assert "human-owned" in human_skips[0]["reason"]

    # The decision-needed task must NOT appear in the skip log either —
    # the SQL pre-filter (status='blocked') already excluded it. This
    # is the contract: the human-owned pre-check only sees tasks that
    # passed the status filter, so it never sees decision-needed.
    assert all(s["skip_human_owned"]["id"] != "t_decision" for s in skip_lines)

    # The auto-recoverable task must be in the JSON output.
    assert proc.stdout.strip(), "no stdout JSON"
    out = json.loads(proc.stdout)
    task_ids = {t["id"] for t in out.get("tasks", [])}
    assert "t_auto" in task_ids
    assert "t_human" not in task_ids
    assert "t_decision" not in task_ids
    assert "t_done" not in task_ids

    # The diag record reflects the skip count.
    assert diag["skipped_human_owned"] == 1
    assert diag["blocked_found"] == 1
    assert diag["boards_scanned"] >= 1

    # The new fields appear in the per-task dict (caller can route on
    # escalation_target / block_kind).
    auto_task = next(t for t in out["tasks"] if t["id"] == "t_auto")
    assert "escalation_target" in auto_task
    assert "block_kind" in auto_task
    assert auto_task["escalation_target"] == ""
    assert auto_task["block_kind"] == "transient"
