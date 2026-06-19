#!/usr/bin/env python3
"""KENSEI blocked-task unblocker — data collector.

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

HERMES = Path(os.path.expanduser("~/.hermes"))
ESCALATION_AGE = int(os.environ.get("KENSEI_UNBLOCKER_AGE", "3600"))
MAX_TASKS = int(os.environ.get("KENSEI_UNBLOCKER_MAX", "50"))
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

if not blocked_tasks:
    sys.exit(0)

print(json.dumps({
    "scanned_at": now,
    "scanned_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)),
    "total_blocked": len(blocked_tasks),
    "truncated": len(blocked_tasks) >= MAX_TASKS,
    "tasks": blocked_tasks,
}, indent=2, ensure_ascii=False))
