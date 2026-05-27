#!/usr/bin/env python3
"""
KENSEI Quality Gate — picks up tasks in 'review' status and routes through Multi-Gate QA.
Runs as no_agent: true cron at 09:00, 13:00, 17:00, 21:00.
"""
import sqlite3, json, datetime as dt, sys, os
from pathlib import Path

DB = Path("/home/kensei/.hermes/kanban.db")
OUT_DIR = Path("/home/kensei/.hermes/governance/logboard")
OUT_DIR.mkdir(parents=True, exist_ok=True)

TZ = dt.timezone(dt.timedelta(hours=1))
now = dt.datetime.now(TZ)

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row

# --- 1. Find tasks in 'review' status ---
rows = conn.execute("""
    SELECT id, title, body, assignee, reviewer, status, created_at,
           updated_at, status_reason, current_step_key
    FROM tasks
    WHERE status = 'review'
    ORDER BY updated_at ASC
""").fetchall()

tasks_in_review = [dict(r) for r in rows]

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
results = []
for task in tasks_in_review:
    tid = task["id"]
    title = task["title"] or ""
    body = task["body"] or ""

    gates = get_required_gates(title, body)

    if not gates:
        # No gates needed — complete directly
        conn.execute("UPDATE tasks SET status='done', result='No gates required (content/config/other)', completed_at=? WHERE id=?", 
                     (int(now.timestamp()), tid))
        conn.commit()
        results.append({"task": tid[:12], "gates": [], "outcome": "skip"})
        continue

    # Update task to note gates
    gate_names = ", ".join(g["gate"] for g in gates)
    conn.execute("UPDATE tasks SET status_reason=? WHERE id=?",
                 (f"QA: {gate_names}", tid))
    conn.commit()

    # Create gate sub-tasks
    parent_id = tid
    created_gates = []
    for i, gate in enumerate(gates):
        worker = gate["worker"]
        gate_name = gate["gate"]
        advisory = gate["advisory"]

        gate_title = f"[QA:{gate_name}] {title[:40]}"
        gate_body = f"""## Gate: {gate_name}
**Original task:** {tid}
**Advisory:** {"Yes — human can override" if advisory else "No — mandatory pass"}
**Worker:** {worker}

Review the output of task {tid}. Apply the gate criteria from `/home/kensei/.hermes/governance/multi-gate-qa.md`.

**Output:**
- Verdict: pass / fail / conditional
- Findings: exact file + line + issue + severity
- If advisory pass, complete without blocking even if minor issues found
"""

        # Create via direct SQL (kanban_create isn't available in no_agent mode)
        import uuid
        gate_id = "t_" + uuid.uuid4().hex[:12]
        now_ts = int(now.timestamp())

        conn.execute("""INSERT INTO tasks (id, title, body, assignee, status, created_by, created_at, updated_at, status_reason)
                        VALUES (?, ?, ?, ?, 'ready', 'kensei-quality-gate', ?, ?, ?)""",
                     (gate_id, gate_title, gate_body, worker, now_ts, now_ts, f"Gate: {gate_name} for {tid}"))

        # Link as child of parent
        conn.execute("INSERT OR IGNORE INTO task_links (parent_id, child_id) VALUES (?, ?)", (parent_id, gate_id))

        created_gates.append({"gate_id": gate_id[:12], "gate": gate_name, "worker": worker})

    conn.commit()
    results.append({"task": tid[:12], "gates": created_gates, "outcome": "dispatched"})

conn.close()

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
