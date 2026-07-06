#!/usr/bin/env python3
"""Kanban task notifier — polls all boards for ready+assigned tasks and
outputs structured Discord messages for new ones.

no_agent=True cron script: stdout is delivered verbatim to Discord.
Empty stdout = silent (no message posted).
Deduplicates via state file at ~/.hermes/data/kanban-notifier-state.json
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
KANBAN_BASE = Path.home() / '.hermes' / 'kanban'
BOARDS_DIR = KANBAN_BASE / 'boards'
STATE_FILE = Path.home() / '.hermes' / 'data' / 'kanban-notifier-state.json'
WRITE_LOCK = KANBAN_BASE / 'kanban-write.lock'

# ── Helpers ────────────────────────────────────────────────────────────────


def discover_boards() -> list[str]:
    """Return sorted list of board slugs (subdirs under boards/ that have a
    kanban.db)."""
    if not BOARDS_DIR.is_dir():
        return []
    boards = []
    for entry in sorted(BOARDS_DIR.iterdir()):
        if entry.is_dir() and (entry / 'kanban.db').is_file():
            boards.append(entry.name)
    return boards


def load_state() -> dict[str, list[str]]:
    """Load dedup state: {board_slug: [task_id, ...]}."""
    if STATE_FILE.is_file():
        try:
            raw = STATE_FILE.read_text(encoding='utf-8').strip()
            if raw:
                return json.loads(raw)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_state(state: dict[str, list[str]]) -> None:
    """Persist dedup state atomically."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, sort_keys=True), encoding='utf-8')
    tmp.replace(STATE_FILE)


def is_write_locked() -> bool:
    """Check if the global kanban write lock exists. Read-only check."""
    return WRITE_LOCK.is_file()


def fetch_ready_tasks(board: str) -> list[dict]:
    """Query a single board for ready+assigned tasks. Returns list of dicts."""
    db_path = BOARDS_DIR / board / 'kanban.db'
    if not db_path.is_file():
        return []

    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, title, body, assignee, priority
            FROM tasks
            WHERE status = 'ready'
              AND assignee IS NOT NULL
              AND assignee != ''
              AND assignee != 'default'
            ORDER BY id
            """,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def format_message(task: dict, board: str) -> str:
    """Format a single task as a structured Discord message block."""
    tid = task['id']
    assignee = task['assignee']
    title = task['title']
    body = task.get('body') or ''
    priority = task.get('priority', 0)

    # First 200 chars of body, stripped of excess whitespace
    brief = ' '.join(body.split())[:200].rstrip()
    if len(body) > 200:
        brief += '…'

    link = f'hermes kanban --board {board} show {tid}'

    return (
        f'📋 Task {tid} assigned to @{assignee}\n'
        f'Board: {board}\n'
        f'Title: {title}\n'
        f'Brief: {brief}\n'
        f'Priority: {priority}\n'
        f'Link: {link}'
    )


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    # Check write lock — if held, skip (read-only script respects it)
    if is_write_locked():
        # Silent exit — no output means no Discord message
        sys.exit(0)

    boards = discover_boards()
    if not boards:
        sys.exit(0)

    state = load_state()
    new_messages: list[str] = []

    for board in boards:
        tasks = fetch_ready_tasks(board)
        known = set(state.get(board, []))

        for task in tasks:
            tid = task['id']
            if tid not in known:
                new_messages.append(format_message(task, board))
                known.add(tid)

        # Update state for this board
        state[board] = sorted(known)

    if new_messages:
        save_state(state)
        print('\n---\n'.join(new_messages))
    # else: silent — no output


if __name__ == '__main__':
    main()
