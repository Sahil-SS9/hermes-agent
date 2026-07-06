#!/usr/bin/env python3
"""
Routing safety-net cron (Phase 3).

Scans all kanban boards for:
  1. Triage tasks without assignees -> auto-assign via keyword matching
  2. Tasks in ready status for >4h with no pickup -> flag
  3. Tasks blocked for >24h -> flag

Runs as no_agent=true — deterministic, zero LLM cost per tick.
Silent when nothing to report.
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
STALE_READY_HOURS = 4
STALE_BLOCKED_HOURS = 24

# Board slugs -> DB paths
# default is the root kanban.db; others are under kanban/boards/<slug>/
BOARDS = {
    "default": os.path.join(HERMES_HOME, "kanban.db"),
    "ops": os.path.join(HERMES_HOME, "kanban", "boards", "ops", "kanban.db"),
    "research": os.path.join(HERMES_HOME, "kanban", "boards", "research", "kanban.db"),
    "apps": os.path.join(HERMES_HOME, "kanban", "boards", "apps", "kanban.db"),
    "content-lead": os.path.join(HERMES_HOME, "kanban", "boards", "content-lead", "kanban.db"),
}

# Routing heuristics (mirrors kanban-router skill)
ROUTING_RULES = [
    # ops board tasks -> wesker
    (["ops"], ["cron", "infra", "service", "gateway", "memory", "disk", "swap",
               "backup", "process", "port", "mcp", "credential", "secret", "auth",
               "security", "audit", "log", "error", "timeout", "restart", "nginx"], "wesker"),
    # research board -> remii
    (["research"], ["tool", "library", "framework", "benchmark", "evaluate",
                    "compare", "architecture", "protocol", "standard",
                    "deep dive", "paper", "arxiv", "git repository",
                    "research", "analysis"], "remii"),
    # apps board -> octacon
    (["apps"], ["bug", "feature", "api", "database", "schema", "component",
                "screen", "navigation", "build", "deploy", "pr", "pull request",
                "implementation", "plenishd", "coachos", "matchdaymaestro",
                "kicktionary", "octacon"], "octacon"),
    # content-lead board -> ceecee
    (["content-lead"], ["content", "social", "post", "thread", "linkedin",
                        "twitter", "brand", "voice", "draft", "campaign",
                        "strategy", "engagement", "publish", "postiz",
                        "approve", "caption"], "ceecee"),
    # research board with market keywords -> market-scanner
    (["research"], ["market", "trend", "landscape", "job", "hiring",
                    "salary", "competitor", "industry", "growth",
                    "funding", "acquisition"], "market-scanner"),
    # research board with design keywords -> design-lead
    (["research"], ["ui", "ux", "design", "mockup", "wireframe", "component",
                    "token", "colour", "typography", "accessibility",
                    "responsive", "brand system"], "design-lead"),
    # default board -> gojo (catch-all)
    ([], ["admin", "calendar", "email", "booking", "logistics",
          "general", "personal", "job hunt", "inbox"], "gojo"),
]


def get_boards():
    """Return list of (slug, path) tuples for boards that exist."""
    result = []
    for slug, path in BOARDS.items():
        if os.path.isfile(path):
            # Quick integrity check
            try:
                conn = sqlite3.connect(path)
                conn.execute("PRAGMA quick_check")
                conn.close()
                result.append((slug, path))
            except sqlite3.DatabaseError:
                continue
    return result


def query_triage_tasks(board_slug, db_path):
    """Return list of triage tasks without assignees."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """SELECT id, title, body, status, created_at, assignee
               FROM tasks
               WHERE status = 'triage'
                 AND (assignee IS NULL OR assignee = '')
               ORDER BY created_at ASC"""
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except sqlite3.OperationalError:
        return []
    except Exception:
        return []


def query_stale_ready(db_path):
    """Return tasks in 'ready' status older than STALE_READY_HOURS."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cutoff = time.time() - (STALE_READY_HOURS * 3600)
        cur.execute(
            """SELECT id, title, status, assignee, created_at
               FROM tasks
               WHERE status = 'ready'
                 AND created_at < ?
               ORDER BY created_at ASC""",
            (cutoff,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except sqlite3.DatabaseError:
        return []
    except Exception:
        return []


def query_stale_blocked(db_path):
    """Return tasks blocked for >STALE_BLOCKED_HOURS."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cutoff = time.time() - (STALE_BLOCKED_HOURS * 3600)
        cur.execute(
            """SELECT id, title, status, assignee, created_at
               FROM tasks
               WHERE status = 'blocked'
                 AND created_at < ?
               ORDER BY created_at ASC""",
            (cutoff,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except sqlite3.DatabaseError:
        return []
    except Exception:
        return []


def match_profile(title, body, board_slug):
    """Match a task to a profile using keyword heuristics."""
    combined = f"{title or ''} {body or ''}".lower()
    matched = []

    for boards, keywords, profile in ROUTING_RULES:
        # Check board match
        if boards and board_slug not in boards:
            continue
        # Check keyword match
        for kw in keywords:
            if kw.lower() in combined:
                matched.append(profile)
                break

    return matched[0] if matched else None


def assign_task(board_slug, task_id, profile):
    """Assign a task to a profile using hermes kanban reassign."""
    try:
        result = subprocess.run(
            ["hermes", "kanban", "--board", board_slug,
             "reassign", task_id, profile,
             "--reason", "Auto-routed by safety-net cron (keyword match)"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        return False, str(e)


def fmt_ts(unix_ts):
    """Format a unix timestamp to readable datetime."""
    if not unix_ts:
        return "unknown"
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    return dt.strftime("%d %b %H:%M")


def main():
    reports = []
    total_assigned = 0
    total_stale_ready = 0
    total_stale_blocked = 0

    for board_slug, db_path in get_boards():
        # --- 1. Auto-assign unassigned triage tasks ---
        triage_tasks = query_triage_tasks(board_slug, db_path)
        for task in triage_tasks:
            profile = match_profile(
                task.get("title", ""),
                task.get("body", ""),
                board_slug,
            )
            if profile:
                ok, msg = assign_task(board_slug, task["id"], profile)
                if ok:
                    reports.append(
                        f"ASSIGN {task['id'][:10]} on {board_slug} "
                        f"→ {profile}: {task.get('title', '')[:60]}"
                    )
                    total_assigned += 1
                else:
                    reports.append(
                        f"FAIL  {task['id'][:10]} on {board_slug} "
                        f"→ {profile}: {msg[:80]}"
                    )
            else:
                reports.append(
                    f"SKIP  {task['id'][:10]} on {board_slug}: "
                    f"No matching profile for '{task.get('title', '')[:60]}'"
                )

        # --- 2. Stale ready tasks ---
        stale_ready = query_stale_ready(db_path)
        for task in stale_ready:
            assignee = task.get("assignee") or "unassigned"
            reports.append(
                f"STALE {task['id'][:10]} on {board_slug}: ready since "
                f"{fmt_ts(task['created_at'])} → {assignee} hasn't picked up"
            )
            total_stale_ready += 1

        # --- 3. Stale blocked tasks ---
        stale_blocked = query_stale_blocked(db_path)
        for task in stale_blocked:
            assignee = task.get("assignee") or "unassigned"
            reports.append(
                f"STALL {task['id'][:10]} on {board_slug}: blocked since "
                f"{fmt_ts(task['created_at'])} → {assignee}"
            )
            total_stale_blocked += 1

    # --- Output ---
    if not reports:
        # Silent — nothing to report
        return

    lines = ["## Routing Safety-Net Scan", ""]
    lines.append(f"**{total_assigned} assigned, {total_stale_ready} stale ready, "
                 f"{total_stale_blocked} stale blocked**")
    lines.append("")
    lines.append("```")
    for r in reports:
        lines.append(r)
    lines.append("```")
    lines.append("")
    lines.append("*Runs every 6h. Silent when nothing to report.*")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
