#!/usr/bin/env python3
"""KENSEI blocked-task unblocker: data collector.

Runs as a no_agent=True script that collects all blocked tasks across all
boards and outputs structured JSON for the LLM cron to consume.

Output: JSON object with scanned_at, scanned_at_iso, total_blocked, truncated,
and tasks[] (board, id, title, assignee, age_seconds, age_hours, priority,
consecutive_failures, max_retries, is_sticky_blocked, body_snippet, status_reason).

Silent (exit 0) when no blocked tasks exist.
"""

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes"))
ESCALATION_AGE = int(os.environ.get("KENSEI_UNBLOCKER_AGE", "3600"))
MAX_TASKS = int(os.environ.get("KENSEI_UNBLOCKER_MAX", "50"))
# Only tasks that have failed / re-blocked this many times warrant a live
# escalation; everything else surfaces in the daily briefing instead.
STUCK_FAILURES = int(os.environ.get("KENSEI_UNBLOCKER_STUCK_FAILURES", "3"))
# Never re-ping the same stuck task more often than this.
DEDUP_HOURS = float(os.environ.get("KENSEI_UNBLOCKER_DEDUP_HOURS", "12"))
STATE_TTL_DAYS = 7
STATE_FILE = HERMES / "state" / "blocked-unblocker-dedup.json"
now = int(time.time())
blocked_tasks = []
errors = []
boards_scanned = 0
boards_skipped = 0


def discover_boards() -> dict[str, Path]:
    """Dynamically discover all kanban DBs with board identity."""
    dbs: dict[str, Path] = {}
    root = HERMES / "kanban.db"
    if root.exists():
        dbs["default"] = root
    boards_dir = HERMES / "kanban" / "boards"
    if boards_dir.exists():
        for board_dir in sorted(boards_dir.iterdir()):
            db = board_dir / "kanban.db"
            if db.exists():
                dbs[board_dir.name] = db
    return dbs


BOARDS = discover_boards()

for slug, db_path in sorted(BOARDS.items()):
    boards_scanned += 1
    if not db_path.exists():
        boards_skipped += 1
        continue
    try:
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro&timeout=5000", uri=True, timeout=5
        )
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT id, title, assignee, priority, status_reason,
                   created_at, updated_at,
                   consecutive_failures, max_retries,
                   substr(body, 1, 500) as body_snippet
            FROM tasks
            WHERE status = 'blocked'
            ORDER BY priority DESC, updated_at ASC
        """)
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        errors.append({"board": slug, "error": str(e)[:200]})
        boards_skipped += 1
        continue

    for row in rows:
        if len(blocked_tasks) >= MAX_TASKS:
            break
        updated = row["updated_at"] if row["updated_at"] is not None else row["created_at"]
        if updated is None:
            continue
        age = now - updated
        if age < ESCALATION_AGE:
            continue
        blocked_tasks.append({
            "board": slug,
            "id": row["id"],
            "title": row["title"],
            "assignee": row["assignee"] or "unassigned",
            "priority": row["priority"] or 0,
            "age_seconds": age,
            "age_hours": round(age / 3600.0, 1),
            "consecutive_failures": row["consecutive_failures"] or 0,
            "max_retries": row["max_retries"],
            "status_reason": row["status_reason"] or "",
            "body_snippet": row["body_snippet"] or "",
        })

# Log diagnostic info to stderr for cron capture
diag = {
    "boards_scanned": boards_scanned,
    "boards_skipped": boards_skipped,
    "blocked_found": len(blocked_tasks),
    "max_tasks": MAX_TASKS,
    "truncated": len(blocked_tasks) >= MAX_TASKS,
    "errors": errors,
}
print(json.dumps(diag), file=sys.stderr)

# Split blocked tasks into two intents:
#   routine: failed fewer than STUCK_FAILURES times, auto-recoverable, unblock SILENTLY.
#   stuck:   failed STUCK_FAILURES+ times, auto-repair has not held, escalate.
stuck = [t for t in blocked_tasks if t["consecutive_failures"] >= STUCK_FAILURES]
routine = [t for t in blocked_tasks if t["consecutive_failures"] < STUCK_FAILURES]


def _state_ts(v) -> int:
    """Coerce a stored state value to an epoch int, tolerating a hand-edited file."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    # Atomic write so two overlapping runs cannot leave a truncated file.
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state))
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        print(json.dumps({"state_save_error": str(e)[:200]}), file=sys.stderr)


# 12h dedup on escalations only: never re-ping the same stuck task within
# DEDUP_HOURS. Routine unblocks are silent so they need no dedup. JSON object
# keys are always strings, so key off str(id) on both read and write.
state = _load_state()
cutoff = now - int(DEDUP_HOURS * 3600)
escalate = [t for t in stuck if _state_ts(state.get(str(t["id"]), 0)) < cutoff]

if not routine and not escalate:
    # Nothing to unblock and nothing new to escalate: do not wake the agent.
    print(json.dumps({"wakeAgent": False}))
    sys.exit(0)

# Record escalation times for the deduped tasks and prune stale state entries.
if escalate:
    ttl_cutoff = now - STATE_TTL_DAYS * 86400
    state = {k: v for k, v in state.items() if _state_ts(v) >= ttl_cutoff}
    for t in escalate:
        state[str(t["id"])] = now
    _save_state(state)

print(json.dumps({
    "wakeAgent": True,
    "scanned_at": now,
    "scanned_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)),
    "total_blocked": len(blocked_tasks),
    "routine_unblock": routine,
    "escalate": escalate,
}, indent=2, ensure_ascii=False))
