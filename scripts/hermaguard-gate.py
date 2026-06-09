#!/usr/bin/env python3
"""
Hermaguard Gate — monitors tasks that require Gate 0 adversarial review.

Runs every 2 hours (08:00-20:00) as a no_agent cron. Scans kanban boards
for backend/frontend/security/new-feature tasks that reached review status
without Hermaguard evidence. Reports findings to #governance.

Silent when nothing found (cron output contract).
"""

import json
import sqlite3
import sys
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/home/kensei/.hermes"))
BOARDS = {
    "default": HERMES_HOME / "kanban.db",
    "apps": HERMES_HOME / "kanban" / "boards" / "apps" / "kanban.db",
    "content-lead": HERMES_HOME / "kanban" / "boards" / "content-lead" / "kanban.db",
    "ops": HERMES_HOME / "kanban" / "boards" / "ops" / "kanban.db",
    "research": HERMES_HOME / "kanban" / "boards" / "research" / "kanban.db",
}

OUT_DIR = HERMES_HOME / "governance" / "logboard"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TZ = timezone(timedelta(hours=1))
now = datetime.now(TZ)
WINDOW_HOURS = 3  # Look back 3 hours for review transitions


# --- Tasks that Gate 0 applies to ---
TIER_KEYWORDS = {
    "backend": ["backend", "api", "db ", "database", "migration", "server", "model", "logic"],
    "frontend": ["frontend", "ui", "ux", "component", "style", "layout", "mobile", "react", "screen"],
    "security": ["auth", "credential", "token", "key", "password", "security", "encrypt", "jwt"],
    "new-feature": ["feature", "integration", "new ", "add ", "implement"],
}


def _should_require_gate0(title: str, body: str) -> str | None:
    """Return tier name if this task should have Gate 0, else None."""
    combined = (title or "") + " " + (body or "")
    combined_lower = combined.lower()

    # Skip content/config/infra outright
    skip_kw = ["content", "post", "copy", "draft", "article", "config", "cron edit", "skill activation"]
    if any(k in combined_lower for k in skip_kw):
        return None

    for tier, keywords in TIER_KEYWORDS.items():
        if any(k in combined_lower for k in keywords):
            return tier
    return None


def _scan_boards():
    tasks = []
    cutoff = int((now - timedelta(hours=WINDOW_HOURS)).timestamp())

    for slug, db_path in BOARDS.items():
        if not db_path.is_file():
            continue
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            """
            SELECT id, title, body, assignee, status, tier, pipeline_stage,
                   created_at, updated_at, completed_at
            FROM tasks
            WHERE status IN ('review', 'running', 'done')
              AND updated_at >= ?
            ORDER BY updated_at DESC
            """,
            (cutoff,),
        ).fetchall()

        for r in rows:
            d = dict(r)
            d["_board_slug"] = slug
            d["_board_db"] = db_path
            tasks.append(d)

        conn.close()

    return tasks


def _has_hermaguard_evidence(task_id: str, db_path: Path) -> bool:
    """Check if task_events has any hermaguard or adversarial review entry."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Check title/body for hermaguard mention in events payload
    rows = conn.execute(
        """
        SELECT kind, payload FROM task_events
        WHERE task_id = ?
          AND (
            LOWER(kind) LIKE '%hermaguard%'
            OR LOWER(kind) LIKE '%adversarial%'
            OR LOWER(kind) LIKE '%review%'
          )
        LIMIT 5
        """,
        (task_id,),
    ).fetchall()

    conn.close()

    # Also check if result field contains hermaguard mention
    conn = sqlite3.connect(str(db_path))
    result = conn.execute(
        "SELECT result FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    conn.close()

    if result and result[0]:
        text = str(result[0]).lower()
        if "hermaguard" in text or "adversarial" in text:
            return True

    for r in rows:
        payload = (r["payload"] or "").lower()
        if "hermaguard" in payload or "adversarial" in payload:
            return True

    return False


def main():
    tasks = _scan_boards()
    flagged = []
    skipped_tier = []
    compliant = []

    for task in tasks:
        tier_tag = _should_require_gate0(task["title"], task["body"])
        if not tier_tag:
            skipped_tier.append(task)
            continue

        has_evidence = _has_hermaguard_evidence(task["id"], task["_board_db"])

        if has_evidence:
            compliant.append({"task": task, "tier_tag": tier_tag})
        else:
            flagged.append({"task": task, "tier_tag": tier_tag})

    # Always log to logboard for audit
    log_entry = {
        "gate_name": "hermaguard-gate",
        "timestamp": now.isoformat(),
        "window_hours": WINDOW_HOURS,
        "scanned": len(tasks),
        "compliant": len(compliant),
        "flagged": len(flagged),
        "skipped_tier": len(skipped_tier),
        "flagged_tasks": [
            {
                "id": f["task"]["id"],
                "board": f["task"]["_board_slug"],
                "title": f["task"]["title"][:80],
                "status": f["task"]["status"],
                "tier_tag": f["tier_tag"],
                "updated_at": datetime.fromtimestamp(
                    f["task"]["updated_at"], tz=timezone(timedelta(hours=1))
                ).isoformat(),
            }
            for f in flagged
        ],
        "compliant_tasks": [
            {
                "id": c["task"]["id"],
                "board": c["task"]["_board_slug"],
                "title": c["task"]["title"][:80],
                "status": c["task"]["status"],
                "tier_tag": c["tier_tag"],
            }
            for c in compliant[:10]  # Cap for brevity
        ],
    }
    logfile = OUT_DIR / f"hermaguard-gate-{now.strftime('%Y%m%d-%H%M%S')}.json"
    logfile.write_text(json.dumps(log_entry, indent=2, default=str))

    # Silent when nothing flagged
    if not flagged:
        sys.exit(0)

    # Deliver report
    print(f"**Gate 0 (Adversarial Review) Compliance Report**")
    print(f"Window: last {WINDOW_HOURS}h  |  {now.strftime('%d/%m/%Y %H:%M:%S')}")
    print()
    print(f"Scanned: {len(tasks)} tasks  |  Compliant: {len(compliant)}  |  **Missing Gate 0: {len(flagged)}**")
    print()

    for f in flagged:
        t = f["task"]
        tag = f["tier_tag"]
        print(
            f"- `{t['id'][:12]}` ({t['_board_slug']}) [{tag}] `{t['status']}` — "
            f"{t['title'][:70]}"
        )

    print()
    print("**Action:** If in review, run `/hermaguard` before approving. "
          "If already done, log to self-eval and tighten task routing.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
