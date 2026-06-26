#!/usr/bin/env python3
"""
KENSEI Quality Gate - picks up tasks in 'review' status and routes through Multi-Gate QA.
Runs as no_agent: true cron at 09:00, 13:00, 17:00, 21:00.

NOTE: As of 04/06/26 the canonical review path is the sdlc-review skill loaded
by the kanban dispatcher (kanban_db.py:7152). This script is retained as a
backstop that feeds findings into the review column; its gate-creation logic
will be folded into the review column in a future pass (Audit M5 roadmap).
"""
import sqlite3
import json
import datetime as dt
import sys
import os
import secrets
from pathlib import Path

# Cross-process write lock - prevents WAL checkpoint races
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    from kanban_write_lock import write_lock
except ImportError:
    write_lock = None

HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/home/kensei/.hermes"))
OUT_DIR = HERMES_HOME / "governance" / "logboard"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BOARDS = {
    "default": HERMES_HOME / "kanban.db",
    "apps": HERMES_HOME / "kanban" / "boards" / "apps" / "kanban.db",
    "content-lead": HERMES_HOME / "kanban" / "boards" / "content-lead" / "kanban.db",
    "ops": HERMES_HOME / "kanban" / "boards" / "ops" / "kanban.db",
    "research": HERMES_HOME / "kanban" / "boards" / "research" / "kanban.db",
}

TZ = dt.timezone(dt.timedelta(hours=1))
now = dt.datetime.now(TZ)


# --- 1. Find tasks in 'review' status across all boards ---
def _scan_boards():
    tasks_in_review = []
    board_tasks = {}

    for slug, db_path in BOARDS.items():
        if not db_path.is_file():
            continue
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT id, title, body, assignee, reviewer, status, created_at,
                       updated_at, status_reason, current_step_key
                FROM tasks
                WHERE status = 'review'
                ORDER BY updated_at ASC
            """).fetchall()
            board_rows = [dict(r) for r in rows]
            for r in board_rows:
                r["_board_slug"] = slug
                r["_board_db"] = db_path
            board_tasks[slug] = board_rows
            tasks_in_review.extend(board_rows)
            conn.close()
        except sqlite3.OperationalError as e:
            # Schema mismatch (e.g. missing updated_at on a freshly
            # auto-recreated empty board). Skip this board, don't kill
            # the whole scan — same self-healing pattern as
            # feature-completion-notify.py
            print(f"  [skip] {slug}: {e}", file=sys.stderr)

    return tasks_in_review, board_tasks


# --- 2. Determine gate requirements ---
def get_required_gates(title, body):
    """Determine which gates apply based on task type."""
    combined = (title or "") + " " + (body or "")
    combined_lower = combined.lower()

    # Config change - advisory only
    if any(k in combined_lower for k in ["config", "cron", "skill activation", "metadata"]):
        return [{"gate": "code_review", "worker": "quan-code", "advisory": True}]

    # Content change - no gates
    if any(k in combined_lower for k in ["content", "post", "copy", "draft", "article"]):
        return []

    # Security-sensitive
    gates = []
    if any(k in combined_lower for k in ["auth", "credential", "token", "key", "password", "security"]):
        gates.append({"gate": "security", "worker": "quan-security", "advisory": False})

    # Infrastructure
    if any(k in combined_lower for k in ["docker", "deploy", "dns", "infra", "vps", "nginx"]):
        gates.append({"gate": "database_arch", "worker": "quan-arch", "advisory": False})
        return gates

    # Default: full backend code
    if any(k in combined_lower for k in ["backend", "api", "db", "database", "migration", "server", "model"]):
        gates = [
            {"gate": "code_review", "worker": "quan-code", "advisory": False},
            {"gate": "code_simplify", "worker": "quan-code", "advisory": False},
            {"gate": "database_arch", "worker": "quan-arch", "advisory": False},
            {"gate": "performance", "worker": "quan-perf", "advisory": False},
            {"gate": "security", "worker": "quan-security", "advisory": False},
        ]
        return gates

    # Frontend
    if any(k in combined_lower for k in ["frontend", "ui", "ux", "component", "style", "layout", "mobile"]):
        gates = [
            {"gate": "code_review", "worker": "quan-code", "advisory": False},
            {"gate": "performance", "worker": "quan-perf", "advisory": False},
            {"gate": "ux", "worker": "quan-ux", "advisory": False},
        ]
        return gates

    # New feature - everything
    gates = [
        {"gate": "code_review", "worker": "quan-code", "advisory": False},
        {"gate": "code_simplify", "worker": "quan-code", "advisory": False},
        {"gate": "database_arch", "worker": "quan-arch", "advisory": False},
        {"gate": "performance", "worker": "quan-perf", "advisory": False},
        {"gate": "security", "worker": "quan-security", "advisory": False},
        {"gate": "ux", "worker": "quan-ux", "advisory": False},
    ]
    return gates


# --- 3. Process each task ---
def _make_gate_id():
    """Generate canonical 10-char task ID: t_ + 8 hex chars."""
    return "t_" + secrets.token_hex(4)


def process_tasks(tasks_in_review):
    # Cache open board connections to avoid reconnecting per task
    board_conns = {}
    results = []

    try:
        for task in tasks_in_review:
            tid = task["id"]
            title = task["title"] or ""
            body = task["body"] or ""
            board_slug = task["_board_slug"]
            board_db = task["_board_db"]

            # Get or create connection for this board
            if board_slug not in board_conns:
                c = sqlite3.connect(str(board_db))
                c.row_factory = sqlite3.Row
                board_conns[board_slug] = c
            conn = board_conns[board_slug]

            gates = get_required_gates(title, body)

            if not gates:
                # No gates needed - complete directly (wrapped in txn)
                if write_lock is not None:
                    with write_lock(conn):
                        conn.execute(
                            "UPDATE tasks SET status='done', "
                            "result='No gates required (content/config/other)', "
                            "completed_at=? WHERE id=?",
                            (int(now.timestamp()), tid),
                        )
                else:
                    with conn:
                        conn.execute(
                            "UPDATE tasks SET status='done', "
                            "result='No gates required (content/config/other)', "
                            "completed_at=? WHERE id=?",
                            (int(now.timestamp()), tid),
                        )
                results.append({"task": tid[:12], "board": board_slug, "gates": [], "outcome": "skip"})
                continue

            # Update task to note gates, then create sub-tasks - single txn
            if write_lock is not None:
                with write_lock(conn):
                    gate_names = ", ".join(g["gate"] for g in gates)
                    conn.execute(
                        "UPDATE tasks SET status_reason=? WHERE id=?",
                        (f"QA: {gate_names}", tid),
                    )
                    created_gates = []
                    for gate in gates:
                        worker = gate["worker"]
                        gate_name = gate["gate"]
                        advisory = gate["advisory"]
                        gate_title = f"[QA:{gate_name}] {title[:40]}"
                        gate_body = (
                            f"## Gate: {gate_name}\n"
                            f"**Original task:** {tid}\n"
                            f"**Board:** {board_slug}\n"
                            f"**Advisory:** {'Yes - human can override' if advisory else 'No - mandatory pass'}\n"
                            f"**Worker:** {worker}\n\n"
                            f"Review the output of task {tid}. "
                            f"Apply the gate criteria from "
                            f"{HERMES_HOME}/governance/multi-gate-qa.md.\n\n"
                            f"**Output:**\n"
                            f"- Verdict: pass / fail / conditional\n"
                            f"- Findings: exact file + line + issue + severity\n"
                            f"- If advisory pass, complete without blocking even if minor issues found\n"
                        )
                        gate_id = _make_gate_id()
                        now_ts = int(now.timestamp())
                        conn.execute(
                            "INSERT INTO tasks (id, title, body, assignee, status, "
                            "created_by, created_at, updated_at, status_reason) "
                            "VALUES (?, ?, ?, ?, 'ready', 'kensei-quality-gate', ?, ?, ?)",
                            (gate_id, gate_title, gate_body, worker, now_ts, now_ts,
                             f"Gate: {gate_name} for {tid}"),
                        )
                        conn.execute(
                            "INSERT OR IGNORE INTO task_links (parent_id, child_id) "
                            "VALUES (?, ?)",
                            (tid, gate_id),
                        )
                        created_gates.append({"gate_id": gate_id[:12], "gate": gate_name, "worker": worker})
            else:
                with conn:
                    gate_names = ", ".join(g["gate"] for g in gates)
                    conn.execute(
                        "UPDATE tasks SET status_reason=? WHERE id=?",
                        (f"QA: {gate_names}", tid),
                    )
                    created_gates = []
                    for gate in gates:
                        worker = gate["worker"]
                        gate_name = gate["gate"]
                        advisory = gate["advisory"]
                        gate_title = f"[QA:{gate_name}] {title[:40]}"
                        gate_body = (
                            f"## Gate: {gate_name}\n"
                            f"**Original task:** {tid}\n"
                            f"**Board:** {board_slug}\n"
                            f"**Advisory:** {'Yes - human can override' if advisory else 'No - mandatory pass'}\n"
                            f"**Worker:** {worker}\n\n"
                            f"Review the output of task {tid}. "
                            f"Apply the gate criteria from "
                            f"{HERMES_HOME}/governance/multi-gate-qa.md.\n\n"
                            f"**Output:**\n"
                            f"- Verdict: pass / fail / conditional\n"
                            f"- Findings: exact file + line + issue + severity\n"
                            f"- If advisory pass, complete without blocking even if minor issues found\n"
                        )
                        gate_id = _make_gate_id()
                        now_ts = int(now.timestamp())
                        conn.execute(
                            "INSERT INTO tasks (id, title, body, assignee, status, "
                            "created_by, created_at, updated_at, status_reason) "
                            "VALUES (?, ?, ?, ?, 'ready', 'kensei-quality-gate', ?, ?, ?)",
                            (gate_id, gate_title, gate_body, worker, now_ts, now_ts,
                             f"Gate: {gate_name} for {tid}"),
                        )
                        conn.execute(
                            "INSERT OR IGNORE INTO task_links (parent_id, child_id) "
                            "VALUES (?, ?)",
                            (tid, gate_id),
                        )
                        created_gates.append({"gate_id": gate_id[:12], "gate": gate_name, "worker": worker})

            results.append({"task": tid[:12], "board": board_slug, "gates": created_gates, "outcome": "dispatched"})
    finally:
        for c in board_conns.values():
            c.close()

    return results


# --- 4. Main ---
def main():
    tasks_in_review, _ = _scan_boards()
    results = process_tasks(tasks_in_review)

    count = len(tasks_in_review)
    dispatched = len([r for r in results if r["outcome"] == "dispatched"])
    skipped = len([r for r in results if r["outcome"] == "skip"])

    # Save every run to logboard for auditability
    log_entry = {
        "timestamp": now.isoformat(),
        "total_review": count,
        "dispatched": dispatched,
        "skipped": skipped,
        "results": results,
    }
    logfile = OUT_DIR / f"quality-gate-{now.strftime('%d-%m-%y-%H%M')}.json"
    logfile.write_text(json.dumps(log_entry, indent=2, default=str))

    # Silent unless QA gates were actually dispatched. An empty review queue,
    # or a queue where every task needed no gates, is routine pipeline churn:
    # it should not post to Discord (it rolls into the daily briefing instead).
    # The logboard JSON above still records every run for auditability.
    if dispatched == 0:
        sys.exit(0)

    print(f"Quality gate · {now.strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"checked · {count} review tasks · {dispatched} gated / {skipped} skipped")

    if results:
        print()
        for r in results:
            if r["outcome"] == "skip":
                print(f"  `{r['task']}` skipped - no gates required")
            else:
                gates_str = ", ".join(f"`{g['gate']}`->{g['worker']}" for g in r["gates"])
                print(f"  `{r['task']}` {gates_str}")


if __name__ == "__main__":
    main()
