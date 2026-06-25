#!/usr/bin/env python3
"""
Feature-completion auto-close + notify.

Scans all kanban boards for parent tasks where:
- Parent is in 'todo', 'blocked', 'scheduled', or 'running'
- Every linked child is 'done' or 'archived'
- Parent has at least 1 child (safety: no orphans)

When found: auto-completes the parent, which triggers any
notify-subscribe subscriptions Sahil registered on that task.

Runs as no_agent cron — zero token cost.
State tracked in /home/kensei/.hermes/data/feature-completion-state.json
to avoid double-closing.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Cross-process write lock to prevent WAL checkpoint races under concurrent write load
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
try:
    from kanban_write_lock import write_lock
except ImportError:
    write_lock = None

BOARDS_ROOT = Path(os.path.expanduser("~/.hermes/kanban/boards"))
STATE_FILE = Path(os.path.expanduser("~/.hermes/data/feature-completion-state.json"))

def get_parents_with_children(db_path: Path) -> dict[str, list[str]]:
    """Return {parent_id: [child_ids]} for all parent-child links."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT parent_id, child_id FROM task_links"
    ).fetchall()
    conn.close()
    result: dict[str, list[str]] = {}
    for row in rows:
        pid = row["parent_id"]
        cid = row["child_id"]
        result.setdefault(pid, []).append(cid)
    return result

def get_task_statuses(db_path: Path, task_ids: list[str]) -> dict[str, str]:
    """Return {task_id: status} for given task IDs."""
    if not task_ids:
        return {}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(task_ids))
    rows = conn.execute(
        f"SELECT id, status FROM tasks WHERE id IN ({placeholders})",
        task_ids
    ).fetchall()
    conn.close()
    return {r["id"]: r["status"] for r in rows}

def get_task_title(db_path: Path, task_id: str) -> Optional[str]:
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT title FROM tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    return row[0] if row else None

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}

def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def main():
    state = load_state()
    new_completions = []

    for board_dir in sorted(BOARDS_ROOT.iterdir()):
        if not board_dir.is_dir():
            continue
        db_path = board_dir / "kanban.db"
        if not db_path.exists():
            continue

        parents = get_parents_with_children(db_path)
        if not parents:
            continue

        all_child_ids = [cid for children in parents.values() for cid in children]
        all_ids = list(parents.keys()) + all_child_ids
        statuses = get_task_statuses(db_path, all_ids)

        for parent_id, child_ids in parents.items():
            parent_status = statuses.get(parent_id, "unknown")
            child_statuses = [statuses.get(cid, "unknown") for cid in child_ids]

            # Parent must NOT already be terminal
            terminal = {"done", "archived", "completed"}
            if parent_status in terminal:
                continue
            # Parent must be in a completable state
            completable = {"todo", "blocked", "scheduled", "running", "ready"}
            if parent_status not in completable:
                continue
            # All children must be terminal
            if not all(cs in terminal for cs in child_statuses):
                continue

            # Safety: must have at least 1 child
            if not child_ids:
                continue

            # Already completed in a prior run?
            if parent_id in state:
                continue

            # Auto-complete (under cross-process write lock)
            title = get_task_title(db_path, parent_id) or parent_id
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            if write_lock is not None:
                with write_lock(conn):
                    now_ts = int(datetime.now(timezone.utc).timestamp())
                    conn.execute(
                        "UPDATE tasks SET status='done', completed_at=? WHERE id=?",
                        (now_ts, parent_id)
                    )
                    conn.commit()
            else:
                now_ts = int(datetime.now(timezone.utc).timestamp())
                conn.execute(
                    "UPDATE tasks SET status='done', completed_at=? WHERE id=?",
                    (now_ts, parent_id)
                )
                conn.commit()
            conn.close()

            state[parent_id] = {
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "children": child_ids,
                "title": title,
                "board": board_dir.name,
            }
            new_completions.append(f"{board_dir.name}/{parent_id}: {title}")

    save_state(state)

    if new_completions:
        summary = "\n".join(f"  - {c}" for c in new_completions)
        print(f"Feature-completion: {len(new_completions)} parent(s) auto-closed:\n{summary}")
    # Silent when nothing to report.

if __name__ == "__main__":
    main()
