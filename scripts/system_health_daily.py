#!/usr/bin/env python3
"""
System Health Daily — consolidated health check.

Replaces: heartbeat audit (hourly LLM), WFA daily, WFA delta, blocked-task-escalator,
          triage-processor.

Runs daily at 08:00. Checks system resources, cron health, kanban pipeline,
process health. Files kanban tasks for issues. Escalates persistent issues.
Silent if healthy.

Design: one script, one cron, one message per day (or zero).
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

HERMES = Path("/home/kensei/.hermes")
STATE_FILE = HERMES / "governance" / "system-health-state.json"
LOG_DIR = HERMES / "governance" / "logboard"
JOBS_FILE = HERMES / "cron" / "jobs.json"
CRON_OUTPUT = HERMES / "cron" / "output"

TZ = ZoneInfo("Europe/London")

# Thresholds
MEM_THRESHOLD_MB = 500
DISK_THRESHOLD_PCT = 80
SWAP_THRESHOLD_PCT = 90
ESCALATION_DAYS = 3
CRON_GRACE_MIN = 10
STALE_RUN_DAYS = 3

TERMINAL_STATUSES = {"done", "completed", "archived"}
SAFE_FAILURE_STATUSES = {"blocked", "failed", "triage"}
FAILED_ONLY_OUTCOMES = {"crashed", "reclaimed", "blocked", "timed_out", "spawn_failed", "gave_up"}
SUCCESSFUL_RUN_MARKERS = {"completed", "success", "succeeded", "ok"}


def now() -> dt.datetime:
    return dt.datetime.now(TZ)


def run(cmd: list[str], timeout: int = 20) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as e:
        return 99, "", str(e)


def create_task(title: str, body: str, assignee: str, priority: str, key: str) -> str | None:
    # Priority: P1=1, P2=2, P3=3
    pnum = {"P1": "1", "P2": "2", "P3": "3"}.get(priority, "2")
    cmd = [
        "hermes", "kanban", "create", title,
        "--body", body,
        "--assignee", assignee,
        "--priority", pnum,
        "--triage",
        "--idempotency-key", key,
        "--created-by", "system-health",
        "--json",
    ]
    code, out, _ = run(cmd, timeout=30)
    if code != 0:
        return None
    try:
        data = json.loads(out)
        return data.get("task_id") or data.get("id")
    except Exception:
        return out.split()[0] if out else None


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"issues": {}, "last_run": None}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def file_finding(title: str, body: str, priority: str, slug: str) -> tuple[str | None, str, str]:
    """File a kanban task with escalation for persistent issues."""
    key = f"system-health-{slug}-{now().strftime('%Y%m%d')}"
    state = load_state()
    issue_key = slug

    if issue_key not in state.get("issues", {}):
        state.setdefault("issues", {})[issue_key] = {
            "first_seen": now().isoformat(),
            "last_seen": now().isoformat(),
            "escalated": False,
        }
    else:
        state["issues"][issue_key]["last_seen"] = now().isoformat()
        first = dt.datetime.fromisoformat(state["issues"][issue_key]["first_seen"])
        age_days = (now() - first).days
        if age_days >= ESCALATION_DAYS and not state["issues"][issue_key]["escalated"]:
            priority = "P1"
            body += f"\n\n**ESCALATED:** Issue persists for {age_days} days. Auto-escalated to P1."
            state["issues"][issue_key]["escalated"] = True
            title = f"[ESCALATED] {title}"

    save_state(state)
    task_id = create_task(title, body, "wesker", priority, key)
    return task_id, title, priority


# ────────────────────────── Checks ──────────────────────────


def check_memory() -> dict | None:
    code, out, _ = run(["free", "-m"], timeout=10)
    if code != 0:
        return {"title": "Memory check failed", "body": f"`free -m` exited {code}.", "priority": "P2", "slug": "memory-check-failed"}
    for line in out.splitlines():
        if line.startswith("Mem:"):
            parts = line.split()
            if len(parts) >= 7:
                avail = int(parts[6])
                total = int(parts[1])
                if avail < MEM_THRESHOLD_MB:
                    pct = int((total - avail) / total * 100)
                    return {
                        "title": f"Low memory: {avail}MB available",
                        "body": f"Available: {avail}MB (threshold {MEM_THRESHOLD_MB}MB). Total: {total}MB, usage: {pct}%.",
                        "priority": "P2",
                        "slug": "low-memory",
                    }
    return None


def check_disk() -> dict | None:
    code, out, _ = run(["df", "-h", "/"], timeout=10)
    if code != 0:
        return {"title": "Disk check failed", "body": f"`df -h /` exited {code}.", "priority": "P2", "slug": "disk-check-failed"}
    for line in out.splitlines():
        if line.startswith("/"):
            parts = line.split()
            if len(parts) >= 5:
                pct = int(parts[4].rstrip("%"))
                if pct > DISK_THRESHOLD_PCT:
                    return {
                        "title": f"Disk usage {pct}%",
                        "body": f"Root disk at {pct}% (threshold {DISK_THRESHOLD_PCT}%).",
                        "priority": "P2",
                        "slug": "disk-usage-high",
                    }
    return None


def check_swap() -> dict | None:
    code, out, _ = run(["free", "-m"], timeout=10)
    if code != 0:
        return None
    for line in out.splitlines():
        if line.startswith("Swap:"):
            parts = line.split()
            if len(parts) >= 3:
                total = int(parts[1])
                used = int(parts[2])
                if total > 0:
                    pct = int(used / total * 100)
                    if pct > SWAP_THRESHOLD_PCT:
                        return {
                            "title": f"Swap {pct}% full",
                            "body": f"Swap: {used}MB/{total}MB ({pct}%).",
                            "priority": "P2",
                            "slug": "swap-high",
                        }
    return None


def check_cron_gaps() -> dict | None:
    try:
        with open(JOBS_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        return None
    jobs = data.get("jobs", [])
    gaps = []
    grace = dt.timedelta(minutes=CRON_GRACE_MIN)
    n = now()
    for j in jobs:
        if not j.get("enabled"):
            continue
        schedule = j.get("schedule", {})
        expr = schedule.get("expr", "") if isinstance(schedule, dict) else str(schedule)
        if not expr or "*/" in expr or "interval" in str(schedule):
            continue
        next_run = j.get("next_run_at")
        if not next_run:
            continue
        try:
            next_dt = dt.datetime.fromisoformat(next_run)
            if n > next_dt + grace:
                name = j.get("name", "?")
                overdue = int((n - next_dt).total_seconds() / 60)
                gaps.append(f"`{name}` — overdue by {overdue}m")
        except Exception:
            continue
    if gaps:
        return {
            "title": f"{len(gaps)} cron(s) overdue",
            "body": "Overdue crons:\n" + "\n".join(gaps[:6]),
            "priority": "P2",
            "slug": "cron-gaps",
        }
    return None


def check_cron_errors() -> dict | None:
    try:
        with open(JOBS_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        return None
    jobs = data.get("jobs", [])
    failed = [j for j in jobs if j.get("enabled") and j.get("last_status") == "error"]
    if failed:
        lines = [f"`{j.get('name')}` — last_status error" for j in failed[:5]]
        return {
            "title": f"{len(failed)} cron(s) failed last run",
            "body": "Failed crons:\n" + "\n".join(lines),
            "priority": "P2",
            "slug": "cron-errors",
        }
    return None


def check_stale_crons() -> dict | None:
    """Crons whose last run is older than expected schedule window."""
    try:
        with open(JOBS_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        return None
    jobs = data.get("jobs", [])
    stale = []
    n = now()
    for j in jobs:
        if not j.get("enabled"):
            continue
        last = j.get("last_run_at")
        if not last:
            # Never run but enabled > 24h
            created = j.get("created_at", "")
            if created:
                try:
                    created_dt = dt.datetime.fromisoformat(created)
                    if (n - created_dt).days > 1:
                        stale.append(f"`{j.get('name')}` — never run, created {(n - created_dt).days}d ago")
                except:
                    pass
            continue
        try:
            last_dt = dt.datetime.fromisoformat(last)
            age_days = (n - last_dt).days
            schedule = j.get("schedule", {})
            expr = schedule.get("expr", "") if isinstance(schedule, dict) else str(schedule)
            # Daily crons stale if > 3 days, others if > 7
            threshold = 3 if expr and "* * *" in expr else 7
            if age_days > threshold:
                stale.append(f"`{j.get('name')}` — last run {age_days}d ago")
        except Exception:
            continue
    if stale:
        return {
            "title": f"{len(stale)} cron(s) stale",
            "body": "Stale crons:\n" + "\n".join(stale[:6]),
            "priority": "P2",
            "slug": "cron-stale",
        }
    return None


def check_gateway() -> dict | None:
    code, out, _ = run(["systemctl", "is-active", "hermes-gateway"], timeout=10)
    if code != 0 or "active" not in out:
        return {
            "title": "Gateway not active",
            "body": f"`systemctl is-active hermes-gateway` returned: `{out}`",
            "priority": "P1",
            "slug": "gateway-inactive",
        }
    # Orphan count
    code, out, _ = run(["pgrep", "-f", "hermes_cli.main gateway"], timeout=10)
    if code == 0:
        pids = [p for p in out.splitlines() if p.strip()]
        if len(pids) > 14:  # 1 primary + ~12 profiles + margin
            return {
                "title": f"{len(pids)} gateway processes (orphans likely)",
                "body": f"Expected ~12-13, found {len(pids)}. Orphan watchdog may be failing.",
                "priority": "P2",
                "slug": "gateway-orphans",
            }
    return None


def check_kanban() -> dict | None:
    boards = {"ops": HERMES / "kanban" / "boards" / "ops" / "kanban.db",
              "research": HERMES / "kanban" / "boards" / "research" / "kanban.db",
              "apps": HERMES / "kanban" / "boards" / "apps" / "kanban.db",
              "content-lead": HERMES / "kanban" / "boards" / "content-lead" / "kanban.db",
              "default": HERMES / "kanban.db"}

    triage_total = 0
    blocked_total = 0
    stale_total = 0
    stale_ts = int((now() - dt.timedelta(days=STALE_RUN_DAYS)).timestamp())

    for name, db_path in boards.items():
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM tasks WHERE status = 'triage'")
            triage_total += cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM tasks WHERE status = 'blocked'")
            blocked_total += cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM tasks WHERE status NOT IN ('done','archived') AND updated_at < ?", (stale_ts,))
            stale_total += cur.fetchone()[0]
            conn.close()
        except Exception:
            continue

    issues = []
    if triage_total > 0:
        issues.append(f"{triage_total} triage task(s) waiting classification")
    if blocked_total > 5:
        issues.append(f"{blocked_total} blocked task(s)")
    if stale_total > 0:
        issues.append(f"{stale_total} stale task(s) (>3d no update)")

    if issues:
        return {
            "title": f"Kanban: {len(issues)} issue(s)",
            "body": "\n".join(issues),
            "priority": "P2",
            "slug": "kanban-health",
        }
    return None


def check_wfa_live() -> dict | None:
    """Worker Failure Analysis — live tasks only. Historical drift ignored."""
    boards_dir = HERMES / "kanban" / "boards"
    dbs = [("default", HERMES / "kanban.db")]
    for b in ["ops", "research", "apps", "content-lead"]:
        dbs.append((b, boards_dir / b / "kanban.db"))

    live_findings = []
    for board, db_path in dbs:
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT id, title, assignee, status, result, skills FROM tasks WHERE status NOT IN ('done','completed','archived')")
            for row in cur.fetchall():
                task_id = row["id"]
                status = (row["status"] or "").lower()
                # Check runs
                cur.execute("SELECT status, outcome FROM task_runs WHERE task_id = ? ORDER BY started_at", (task_id,))
                runs = cur.fetchall()
                run_outcomes = [r["outcome"] or r["status"] for r in runs]

                # Terminal without completed run
                if status in TERMINAL_STATUSES:
                    completed = [r for r in runs if (r["outcome"] or r["status"]) in SUCCESSFUL_RUN_MARKERS]
                    if not completed:
                        live_findings.append({
                            "task": task_id,
                            "board": board,
                            "kind": "terminal_without_completed_run",
                            "title": row["title"],
                        })

                # All runs crashed
                if runs and all((r["outcome"] == "crashed" or r["status"] == "crashed") for r in runs):
                    if status not in SAFE_FAILURE_STATUSES:
                        live_findings.append({
                            "task": task_id,
                            "board": board,
                            "kind": "all_runs_crashed",
                            "title": row["title"],
                        })

                # Result claims completion but only failed runs
                result = row["result"] or ""
                if result and any(w in result.lower() for w in ("complete", "done", "resolved", "fixed", "shipped", "success")):
                    if runs and all((r["outcome"] or r["status"]) in FAILED_ONLY_OUTCOMES for r in runs):
                        completed = [r for r in runs if (r["outcome"] or r["status"]) in SUCCESSFUL_RUN_MARKERS]
                        if not completed:
                            live_findings.append({
                                "task": task_id,
                                "board": board,
                                "kind": "result_claims_complete_but_runs_failed",
                                "title": row["title"],
                            })
            conn.close()
        except Exception:
            continue

    if live_findings:
        by_kind = Counter(f["kind"] for f in live_findings)
        lines = [f"{k}: {v}" for k, v in by_kind.most_common()]
        # Show top 5 examples
        examples = live_findings[:5]
        detail = "\n".join(f"- {f['board']}:{f['task'][:10]} {f['kind']} · {f['title'][:60]}" for f in examples)
        return {
            "title": f"WFA: {len(live_findings)} live task/run drift",
            "body": f"By type:\n" + "\n".join(lines) + f"\n\nTop examples:\n{detail}",
            "priority": "P1" if any(f["kind"] == "terminal_without_completed_run" for f in live_findings) else "P2",
            "slug": "wfa-live-drift",
        }
    return None


# ────────────────────────── Main ──────────────────────────


def main() -> int:
    n = now()
    findings: list[dict] = []
    filed: list[tuple[str | None, str, str]] = []

    checks = [
        ("Memory", check_memory),
        ("Disk", check_disk),
        ("Swap", check_swap),
        ("Cron gaps", check_cron_gaps),
        ("Cron errors", check_cron_errors),
        ("Stale crons", check_stale_crons),
        ("Gateway", check_gateway),
        ("Kanban", check_kanban),
        ("WFA live", check_wfa_live),
    ]

    for name, check_fn in checks:
        result = check_fn()
        if result:
            findings.append(result)

    # File tasks
    for finding in findings:
        task_id, title, priority = file_finding(
            finding["title"], finding["body"], finding["priority"], finding["slug"]
        )
        filed.append((task_id, title, priority))

    # Update state
    state = load_state()
    state["last_run"] = n.isoformat()
    save_state(state)

    # Silent if healthy
    if not findings:
        return 0

    # Discord output
    stamp = n.strftime("%d/%m/%Y %H:%M:%S")
    print(f"System Health · {stamp}")
    p1_count = sum(1 for _, _, p in filed if p == "P1")
    p2_count = sum(1 for _, _, p in filed if p == "P2")
    print(f"Findings: {len(findings)} · P1: {p1_count} · P2: {p2_count}")
    for task_id, title, priority in filed:
        tid = task_id or "(failed to file)"
        print(f"• `{tid}` {title} · {priority}")

    # JSON log
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logfile = LOG_DIR / f"system-health-{n.strftime('%Y%m%d-%H%M%S')}.json"
    payload = {
        "timestamp": n.isoformat(),
        "findings": findings,
        "filed": [{"task_id": t, "title": tt, "priority": p} for t, tt, p in filed],
    }
    logfile.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"JSON: {logfile}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        n = now()
        try:
            create_task(
                "[CRITICAL] System health script crashed",
                f"Script failed at {n.strftime('%d/%m/%Y %H:%M:%S')}: {type(e).__name__}: {e}",
                "wesker",
                "P1",
                f"system-health-crash-{n.strftime('%Y%m%d')}",
            )
        except Exception:
            pass
        print(f"System Health CRASH · {n.strftime('%d/%m/%Y %H:%M:%S')}: {type(e).__name__}: {e}")
        raise SystemExit(1)
