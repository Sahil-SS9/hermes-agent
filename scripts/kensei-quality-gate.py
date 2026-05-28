#!/usr/bin/env python3
"""
KENSEI Quality Gate — picks up tasks in 'review' status and routes through Multi-Gate QA.
Runs as no_agent: true cron at 09:00, 13:00, 17:00, 21:00.
"""
import sqlite3, json, datetime as dt, sys, os
from pathlib import Path

HERMES_HOME = Path("/home/kensei/.hermes")
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
tasks_in_review = []
board_tasks = {}  # slug -> [task dicts]

for slug, db_path in BOARDS.items():
    if not db_path.is_file():
        continue
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

# --- 2. Determine gate requirements ---
def get_required_gates(title, body):
    """Determine which gates apply based on task type."""
    combined = (title or "") + " " + (body or "")
    combined_lower = combined.lower()

    gates = []

    # Config change — advisory only
    if any(k in combined_lower for k in ["config", "cron", "skill activation", "metadata"]):
        return [{"gate": "code_review", "worker": "quan-code", "advisory": True}]

    # Content change — no gates
    if any(k in combined_lower for k in ["content", "post", "copy", "draft", "article"]):
        return []

    # Security-sensitive
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

    # New feature — everything
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
            # No gates needed — complete directly
            conn.execute("UPDATE tasks SET status='done', result='No gates required (content/config/other)', completed_at=? WHERE id=?", 
                         (int(now.timestamp()), tid))
            conn.commit()
            results.append({"task": tid[:12], "board": board_slug, "gates": [], "outcome": "skip"})
            continue

        # Update task to note gates
        gate_names = ", ".join(g["gate"] for g in gates)
        conn.execute("UPDATE tasks SET status_reason=? WHERE id=?",
                     (f"QA: {gate_names}", tid))
        conn.commit()

        # Create gate sub-tasks
        parent_id = tid
        created_gates = []
        for gate in gates:
            worker = gate["worker"]
            gate_name = gate["gate"]
            advisory = gate["advisory"]

            gate_title = f"[QA:{gate_name}] {title[:40]}"
            gate_body = f"""## Gate: {gate_name}
**Original task:** {tid}
**Board:** {board_slug}
**Advisory:** {"Yes — human can override" if advisory else "No — mandatory pass"}
**Worker:** {worker}

Review the output of task {tid}. Apply the gate criteria from `/home/kensei/.hermes/governance/multi-gate-qa.md`.

**Output:**
- Verdict: pass / fail / conditional
- Findings: exact file + line + issue + severity
- If advisory pass, complete without blocking even if minor issues found
"""

            import uuid
            gate_id = "t_" + uuid.uuid4().hex[:12]
            now_ts = int(now.timestamp())

            conn.execute("""INSERT INTO tasks (id, title, body, assignee, status, created_by, created_at, updated_at, status_reason)
                            VALUES (?, ?, ?, ?, 'ready', 'kensei-quality-gate', ?, ?, ?)""",
                         (gate_id, gate_title, gate_body, worker, now_ts, now_ts, f"Gate: {gate_name} for {tid}"))

            conn.execute("INSERT OR IGNORE INTO task_links (parent_id, child_id) VALUES (?, ?)", (parent_id, gate_id))

            created_gates.append({"gate_id": gate_id[:12], "gate": gate_name, "worker": worker})

        conn.commit()
        results.append({"task": tid[:12], "board": board_slug, "gates": created_gates, "outcome": "dispatched"})
finally:
    for c in board_conns.values():
        c.close()

# --- 4. Output ---
count = len(tasks_in_review)
dispatched = len([r for r in results if r["outcome"] == "dispatched"])
skipped = len([r for r in results if r["outcome"] == "skip"])

# Save every run to logboard for auditability, but keep no_agent stdout silent
# when there is nothing to review.
log_entry = {
    "timestamp": now.isoformat(),
    "total_review": count,
    "dispatched": dispatched,
    "skipped": skipped,
    "results": results,
}
logfile = OUT_DIR / f"quality-gate-{now.strftime('%d-%m-%y-%H%M')}.json"
logfile.write_text(json.dumps(log_entry, indent=2, default=str))

if count == 0:
    sys.exit(0)

print(f"🔬 Quality gate · {now.strftime('%d/%m/%Y %H:%M:%S')}")
print(f"checked · {count} review tasks · {dispatched} gated / {skipped} skipped")

if results:
    print()
    for r in results:
        if r["outcome"] == "skip":
            print(f"• `{r['task']}` skipped — no gates required")
        else:
            gates_str = ", ".join(f"`{g['gate']}`→{g['worker']}" for g in r["gates"])
            print(f"• `{r['task']}` {' · '.join(gates_str)}")
