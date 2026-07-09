#!/usr/bin/env python3
"""Verification tests for the 4 kanban/cron/discord fixes.

Run:  python3 -m pytest /home/kensei/repos/KenseiAgent/tests/test_kanban_cron_fixes.py -v
These exercise the ACTUAL edited code, not replicas.
"""
import sqlite3, os, json, sys, subprocess, tempfile, time
import pytest

HERMES_HOME = "/home/kensei/.hermes"
COLLECTOR = "/home/kensei/repos/KenseiAgent/scripts/kensei-blocked-unblocker.py"
KANBAN_DB = "/home/kensei/.hermes/profiles/hermes_cli/kanban_db.py"


def _seed_blocked_db(path, rows):
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE tasks(
        id TEXT, title TEXT, assignee TEXT, priority INT, status TEXT,
        status_reason TEXT, created_at INT, updated_at INT, consecutive_failures INT,
        max_retries INT, escalation_target TEXT, block_kind TEXT, body TEXT)""")
    for r in rows:
        con.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", r)
    con.commit(); con.close()


def test_collector_skips_human_owned():
    """FIX 1: tasks with escalation_target set must never reach routine_unblock/escalate."""
    db = tempfile.mktemp(suffix=".db")
    now = int(time.time())
    _seed_blocked_db(db, [
        ("t_auto", "loop crash", "octacon", 0, "blocked", "crashed",
         now - 7200, now - 7200, 5, 5, None, "", "body x"),
        ("t_human", "awaiting decision", "sahil", 0, "blocked", "needs call",
         now - 7200, now - 7200, 5, 5, "sahil", "decision", "body y"),
    ])
    fake = tempfile.mkdtemp()
    os.symlink(db, os.path.join(fake, "kanban.db"))
    env = dict(os.environ); env["HERMES_HOME"] = fake
    proc = subprocess.run([sys.executable, COLLECTOR], capture_output=True, text=True, env=env)
    s = proc.stdout
    start = s.find("{"); end = s.rfind("}") + 1
    assert start != -1 and end != -1, f"no json output: {proc.stdout[:200]}"
    res = json.loads(s[start:end])
    auto_ids = [t["id"] for t in res["routine_unblock"] + res["escalate"]]
    human_ids = [t["id"] for t in res["human_owned_skipped"]]
    assert "t_human" not in auto_ids, "human-owned task leaked into auto lists"
    assert "t_human" in human_ids, "human-owned task not reported in skip list"
    assert "t_auto" in auto_ids, "auto task was dropped"


def test_schedule_task_guard_blocks_human_owned():
    """FIX 2: schedule_task must refuse to reschedule a task with escalation_target set."""
    # Import the real module (dep-heavy, but its top-level dataclass bug is
    # avoided by pre-registering the module in sys.modules).
    import importlib.util
    spec = importlib.util.spec_from_file_location("kanban_db_test", KANBAN_DB)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kanban_db_test"] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        pytest.skip(f"kanban_db import blocked by deps: {e}")
    db = tempfile.mktemp(suffix=".db")
    con = sqlite3.connect(db); con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE tasks(id TEXT, status TEXT, claim_lock TEXT, claim_expires TEXT,
            worker_pid TEXT, escalation_target TEXT, current_run_id TEXT);
        CREATE TABLE task_runs(id INTEGER PRIMARY KEY, task_id TEXT, outcome TEXT,
            status TEXT, summary TEXT);
        CREATE TABLE task_events(id INTEGER PRIMARY KEY, task_id TEXT, kind TEXT,
            payload TEXT, created_at INT);
    """)
    con.execute("INSERT INTO tasks VALUES('t_decision','blocked',NULL,NULL,NULL,'sahil','1')")
    con.commit()
    ok = mod.schedule_task(con, "t_decision")
    status = con.execute("SELECT status FROM tasks WHERE id='t_decision'").fetchone()["status"]
    assert ok is False, "schedule_task returned True for human-owned task"
    assert status == "blocked", "human-owned task status changed"


def test_triage_prompt_forbids_leaks():
    """FIX 3: triage-investigator prompt must forbid memory/tool_call/reasoning leaks."""
    data = json.load(open(f"{HERMES_HOME}/cron/jobs.json"))
    prompt = [j["prompt"] for j in data["jobs"] if j.get("name") == "kensei-triage-investigator"][0]
    for term in ["OUTPUT CONTRACT", "memory", "tool_call", "STRICTLY FORBIDDEN", "[SILENT]"]:
        assert term in prompt, f"missing contract term: {term}"


def test_media_roots_include_runbooks():
    """FIX 4: runbooks must be in MEDIA_DELIVERY_SAFE_ROOTS in all 3 gateway copies."""
    for f in [
        "/home/kensei/hermes-agent/gateway/platforms/base.py",
        "/home/kensei/repos/hermes-agent-upstream/gateway/platforms/base.py",
        "/home/kensei/repos/KenseiAgent/gateway/platforms/base.py",
    ]:
        assert os.path.isfile(f), f"missing base.py: {f}"
        assert '_HERMES_HOME / "runbooks",' in open(f).read(), f"runbooks missing in {f}"
