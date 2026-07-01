#!/usr/bin/env python3
"""
KENSEI Worker Failure Analysis Script

Scans the default Kanban DB plus every board DB, reconciles task status against
run outcomes, validates forced task skills against assignee profile visibility,
and emits:
- concise stdout for Discord cron delivery
- machine-readable JSON under the governance logboard
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import shutil
from collections import Counter
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

HERMES_HOME = Path("/home/kensei/.hermes")
# Canonical default board DB. Do not include ~/.hermes/kanban/kanban.db: on this
# VPS that path exists as an empty placeholder and would create noisy false
# warnings. Named boards are scanned from BOARDS_DIR below.
DEFAULT_DBS = [HERMES_HOME / "kanban.db"]
BOARDS_DIR = HERMES_HOME / "kanban" / "boards"
REQUIRED_BOARDS = ("ops", "research", "apps", "content-lead")
SMOKE_FIXTURE_TASK_IDS = ("t_9c935bab", "t_e4032b4b", "t_ea2483cd")
OUT_DIR = HERMES_HOME / "governance" / "logboard"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TZ = ZoneInfo("Europe/London")
TERMINAL_STATUSES = {"done", "completed", "archived"}
SAFE_FAILURE_STATUSES = {"blocked", "failed", "triage"}
FAILED_ONLY_OUTCOMES = {"crashed", "reclaimed", "blocked", "timed_out", "spawn_failed", "gave_up"}
SUCCESSFUL_RUN_MARKERS = {"completed", "success", "succeeded", "ok"}
COMPLETION_WORDS = ("complete", "completed", "done", "resolved", "fixed", "shipped", "success")


def now() -> dt.datetime:
    return dt.datetime.now(TZ)


def fmt_ts(value: int | str | None) -> str | None:
    if not value:
        return None
    # Board DBs store created_at inconsistently: some rows are int epochs, some
    # are ISO/text strings. Coerce defensively so a single string row cannot
    # crash the whole board scan (which previously surfaced as a false
    # "Integrity: FAIL" in the Discord summary).
    if not isinstance(value, (int, float)):
        text = str(value).strip()
        try:
            value = float(text)
        except (TypeError, ValueError):
            # Already a human/ISO timestamp; pass it through untouched.
            return text
    # Historic rows may be seconds; defensive support for ms.
    seconds = value / 1000 if value > 10_000_000_000 else value
    return dt.datetime.fromtimestamp(seconds, tz=TZ).strftime("%d/%m/%Y %H:%M:%S")


def display_now(ts: dt.datetime) -> str:
    return ts.strftime("%d/%m/%Y %H:%M:%S")


def discover_dbs() -> list[dict[str, Any]]:
    candidates: list[tuple[str, Path]] = []
    for path in DEFAULT_DBS:
        candidates.append(("default", path))
    for board in REQUIRED_BOARDS:
        candidates.append((board, BOARDS_DIR / board / "kanban.db"))

    # Scan profile-scoped boards (e.g. dezzy/ops, wesker/default) so that
    # task run/status drift across all profiles is caught, not just canonical boards.
    for profile_dir in sorted((HERMES_HOME / "profiles").iterdir()):
        profile = profile_dir.name
        if not profile_dir.is_dir():
            continue
        for board_dir in sorted(profile_dir.glob("kanban/boards/*/kanban.db")):
            candidates.append((f"{profile}/{board_dir.parent.name}", board_dir))

    seen: set[Path] = set()
    dbs: list[dict[str, Any]] = []
    for board, path in candidates:
        path = path.resolve()
        if path in seen or not path.exists():
            continue
        seen.add(path)
        dbs.append({"board": board, "path": str(path)})
    return dbs


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def fallback_snapshots(board: str, primary_path: str) -> list[Path]:
    """Return non-live snapshots for incident forensics when a board DB is malformed."""
    primary = Path(primary_path).resolve()
    board_dir = primary.parent
    candidates: list[Path] = []
    # Prefer clean recovery DBs over malformed backups. The backups remain useful
    # only when no recovered copy exists.
    candidates.extend(sorted(board_dir.glob("workspaces/*/recovery/*.db"), key=lambda p: p.stat().st_mtime, reverse=True))
    candidates.extend(sorted(board_dir.glob("workspaces/*/recovery/*.input"), key=lambda p: p.stat().st_mtime, reverse=True))
    candidates.extend(sorted(board_dir.glob("kanban.db.corrupt*.bak"), key=lambda p: p.stat().st_mtime, reverse=True))
    usable: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if resolved == primary or candidate.name.endswith(("-wal", "-shm")):
                continue
            with connect(str(resolved)) as conn:
                if {"tasks", "task_runs", "task_events"}.issubset(table_names(conn)):
                    usable.append(resolved)
        except Exception:
            continue
    return usable


def table_names(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def safe_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def as_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def parse_skills(value: Any) -> list[str]:
    parsed = safe_json(value)
    if isinstance(parsed, list):
        return [str(x) for x in parsed if x]
    if isinstance(parsed, dict) and isinstance(parsed.get("skills"), list):
        return [str(x) for x in parsed["skills"] if x]
    if isinstance(parsed, str) and parsed.strip():
        # Support legacy comma/newline separated strings.
        bits = parsed.replace("\n", ",").split(",")
        return [b.strip() for b in bits if b.strip()]
    return []


def forced_skills_from_created_events(events: list[dict[str, Any]]) -> list[str]:
    skills: list[str] = []
    for event in events:
        if event.get("kind") != "created":
            continue
        payload = safe_json(event.get("payload"))
        if isinstance(payload, dict):
            skills.extend(parse_skills(payload.get("skills")))
    # Preserve order, drop duplicates.
    return list(dict.fromkeys(skills))


def profile_skill_names(profile: str) -> set[str]:
    if not profile:
        return set()
    skill_root = HERMES_HOME / "profiles" / profile / "skills"
    names: set[str] = set()
    if not skill_root.exists():
        return names
    for skill_file in skill_root.rglob("SKILL.md"):
        names.add(skill_file.parent.name)
        try:
            for line in skill_file.read_text(encoding="utf-8", errors="ignore").splitlines()[:20]:
                if line.strip().startswith("name:"):
                    names.add(line.split(":", 1)[1].strip().strip('"\''))
                    break
        except Exception:
            pass
    return names


def global_skill_names() -> set[str]:
    names: set[str] = set()
    root = HERMES_HOME / "skills"
    if not root.exists():
        return names
    for skill_file in root.rglob("SKILL.md"):
        names.add(skill_file.parent.name)
        try:
            for line in skill_file.read_text(encoding="utf-8", errors="ignore").splitlines()[:20]:
                if line.strip().startswith("name:"):
                    names.add(line.split(":", 1)[1].strip().strip('"\''))
                    break
        except Exception:
            pass
    return names


def get_runs(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    cols = column_names(conn, "task_runs")
    select_cols = [c for c in ["id", "task_id", "profile", "status", "outcome", "summary", "error", "metadata", "started_at", "ended_at"] if c in cols]
    rows = conn.execute(
        f"SELECT {', '.join(select_cols)} FROM task_runs WHERE task_id = ? ORDER BY started_at, id",
        (task_id,),
    ).fetchall()
    return [as_dict(r) for r in rows]


def get_events(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT kind, payload, created_at FROM task_events WHERE task_id = ? ORDER BY created_at, id",
        (task_id,),
    ).fetchall()
    return [as_dict(r) for r in rows]


def successful_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        r
        for r in runs
        if (
            str(r.get("outcome") or "").lower() in SUCCESSFUL_RUN_MARKERS
            or str(r.get("status") or "").lower() in SUCCESSFUL_RUN_MARKERS
        )
    ]


def all_runs_are_crashed(runs: list[dict[str, Any]]) -> bool:
    if not runs:
        return False
    return all((r.get("outcome") == "crashed" or r.get("status") == "crashed") for r in runs)


def only_failed_runs(runs: list[dict[str, Any]]) -> bool:
    if not runs:
        return False
    for run in runs:
        outcome = run.get("outcome") or run.get("status")
        if outcome not in FAILED_ONLY_OUTCOMES:
            return False
    return True


def result_claims_completion(result: Any) -> bool:
    if not result:
        return False
    text = str(result).lower()
    return any(word in text for word in COMPLETION_WORDS)


def task_summary(task: dict[str, Any], board: str) -> dict[str, Any]:
    return {
        "board": board,
        "task_id": task.get("id"),
        "title": (task.get("title") or "")[:120],
        "assignee": task.get("assignee"),
        "status": task.get("status"),
        "created_at": fmt_ts(task.get("created_at")),
        "updated_at": fmt_ts(task.get("updated_at")),
        "completed_at": fmt_ts(task.get("completed_at")),
    }


def add_finding(findings: list[dict[str, Any]], kind: str, severity: str, task: dict[str, Any], board: str, detail: str, evidence: dict[str, Any]) -> None:
    findings.append({
        "kind": kind,
        "severity": severity,
        **task_summary(task, board),
        "detail": detail,
        "evidence": evidence,
    })


def analyse_db(db: dict[str, Any], global_skills: set[str], profile_skill_cache: dict[str, set[str]], allow_fallback: bool = True) -> dict[str, Any]:
    board = db["board"]
    path = db["path"]
    result: dict[str, Any] = {
        "board": board,
        "path": path,
        "integrity_check": None,
        "task_count": 0,
        "findings": [],
        "errors": [],
    }
    try:
        with connect(path) as conn:
            result["integrity_check"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
            tables = table_names(conn)
            if not {"tasks", "task_runs", "task_events"}.issubset(tables):
                result["errors"].append("missing required Kanban tables or empty DB")
                return result

            task_cols = column_names(conn, "tasks")
            select_cols = [c for c in [
                "id", "title", "body", "assignee", "status", "created_at", "updated_at", "completed_at",
                "result", "skills", "status_reason", "last_failure_error", "current_run_id",
            ] if c in task_cols]
            rows = conn.execute(f"SELECT {', '.join(select_cols)} FROM tasks").fetchall()
            result["task_count"] = len(rows)

            for row in rows:
                task = as_dict(row)
                task_id = task["id"]
                status = (task.get("status") or "").lower()
                runs = get_runs(conn, task_id)
                events = get_events(conn, task_id)
                completed = successful_runs(runs)
                run_outcomes = [r.get("outcome") or r.get("status") for r in runs]

                if status in TERMINAL_STATUSES and not completed:
                    add_finding(
                        result["findings"],
                        "terminal_without_completed_run",
                        "critical",
                        task,
                        board,
                        "Task is terminal but has no completed/success run evidence.",
                        {"run_count": len(runs), "run_outcomes": run_outcomes},
                    )

                if all_runs_are_crashed(runs) and status not in SAFE_FAILURE_STATUSES:
                    add_finding(
                        result["findings"],
                        "all_runs_crashed_unprotected_status",
                        "critical" if status in TERMINAL_STATUSES else "high",
                        task,
                        board,
                        "Every recorded run crashed, but task status is not blocked/failed/triage.",
                        {"run_count": len(runs), "run_outcomes": run_outcomes},
                    )

                if result_claims_completion(task.get("result")) and only_failed_runs(runs) and not completed:
                    add_finding(
                        result["findings"],
                        "result_claims_complete_but_runs_failed",
                        "critical",
                        task,
                        board,
                        "Task result claims completion, but runs only show crashed/reclaimed/blocked-style outcomes.",
                        {"result": task.get("result"), "run_outcomes": run_outcomes},
                    )

                forced_sources = {
                    "task.skills": parse_skills(task.get("skills")),
                    "created_event.skills": forced_skills_from_created_events(events),
                }
                assignee = task.get("assignee") or ""
                if assignee not in profile_skill_cache:
                    profile_skill_cache[assignee] = profile_skill_names(assignee)
                visible = profile_skill_cache[assignee]
                for source, skills in forced_sources.items():
                    missing = [s for s in skills if s not in visible]
                    if missing:
                        add_finding(
                            result["findings"],
                            "forced_skill_not_visible_to_assignee_profile",
                            "critical",
                            task,
                            board,
                            f"Forced skills from {source} are not visible to assignee profile '{assignee}'.",
                            {
                                "source": source,
                                "missing_skills": missing,
                                "visible_in_global_default_skills": [s for s in missing if s in global_skills],
                                "profile_skill_count": len(visible),
                            },
                        )
    except Exception as exc:
        result["integrity_check"] = "scan_failed"
        result["errors"].append(f"scan failed: {type(exc).__name__}: {exc}")
        if allow_fallback:
            for fallback in fallback_snapshots(board, path):
                fallback_result = analyse_db(
                    {"board": board, "path": str(fallback)},
                    global_skills,
                    profile_skill_cache,
                    allow_fallback=False,
                )
                if fallback_result.get("findings"):
                    for finding in fallback_result["findings"]:
                        finding.setdefault("evidence", {})["fallback_snapshot"] = str(fallback)
                        finding.setdefault("evidence", {})["primary_scan_error"] = result["errors"][0]
                    result["findings"].extend(fallback_result["findings"])
                    result["task_count"] = fallback_result.get("task_count", 0)
                    result["errors"].append(f"used fallback snapshot for findings: {fallback}")
                    break
    return result


def main() -> int:
    scan_time = now()
    dbs = discover_dbs()
    global_skills = global_skill_names()
    profile_skill_cache: dict[str, set[str]] = {}

    board_results = [analyse_db(db, global_skills, profile_skill_cache) for db in dbs]
    findings = [f for board in board_results for f in board["findings"]]
    integrity_failures = [b for b in board_results if b.get("integrity_check") != "ok"]
    scan_errors = [b for b in board_results if b.get("errors")]

    by_kind = Counter(f["kind"] for f in findings)
    by_board = Counter(f["board"] for f in findings)
    by_severity = Counter(f["severity"] for f in findings)
    live_findings = [f for f in findings if f.get("status") not in TERMINAL_STATUSES]
    historical_findings = [f for f in findings if f.get("status") in TERMINAL_STATUSES]
    live_by_kind = Counter(f["kind"] for f in live_findings)
    live_by_severity = Counter(f["severity"] for f in live_findings)

    payload = {
        "timestamp": scan_time.isoformat(),
        "timestamp_display": display_now(scan_time),
        "scan_scope": {
            "db_count": len(dbs),
            "dbs": dbs,
            "terminal_statuses": sorted(TERMINAL_STATUSES),
        },
        "integrity": [{"board": b["board"], "path": b["path"], "result": b["integrity_check"], "errors": b["errors"]} for b in board_results],
        "summary": {
            "task_count": sum(b.get("task_count", 0) for b in board_results),
            "finding_count": len(findings),
            "live_finding_count": len(live_findings),
            "historical_terminal_finding_count": len(historical_findings),
            "by_kind": dict(by_kind),
            "by_board": dict(by_board),
            "by_severity": dict(by_severity),
            "live_by_kind": dict(live_by_kind),
            "live_by_severity": dict(live_by_severity),
            "integrity_failure_count": len(integrity_failures),
            "scan_error_count": len(scan_errors),
        },
        "findings": findings,
    }

    logfile = OUT_DIR / f"worker-failure-analysis-{scan_time.strftime('%Y%m%d-%H%M%S')}.json"
    logfile.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    latest = OUT_DIR / "worker-failure-analysis-latest.json"
    shutil.copy2(logfile, latest)

    if not findings and not integrity_failures and not scan_errors:
        return 0  # silent — nothing to report

    # Historical-only drift goes to JSON log only, not Discord.
    # Only deliver to Discord when there are live findings, integrity failures, or scan errors.
    if not live_findings and not integrity_failures and not scan_errors:
        return 0  # silent — historical drift is audit-only, logged to JSON

    # Lead with a severity marker so the delivery envelope can route correctly:
    # 🔴 actionable (live critical, or DB integrity/scan failures) pings; 🟡 live
    # non-critical posts quietly.
    if integrity_failures or scan_errors or live_by_severity.get("critical"):
        marker = "🔴"
    else:
        marker = "🟡"
    print(f"{marker} Worker Failure Analysis · {display_now(scan_time)}")
    print(
        f"DBs scanned: {len(dbs)} · tasks: {payload['summary']['task_count']} · "
        f"live findings: {len(live_findings)}"
    )
    if integrity_failures:
        print(f"Integrity: FAIL {len(integrity_failures)}")
    if live_by_severity:
        sev_bits = [f"{k}={v}" for k, v in sorted(live_by_severity.items())]
        print("Live severity: " + ", ".join(sev_bits))
    if live_by_kind:
        print("Live issue types: " + ", ".join(f"{k}={v}" for k, v in live_by_kind.most_common(5)))
    if live_findings:
        print("Highest-risk live examples:")
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        ordered = sorted(live_findings, key=lambda x: (sev_order.get(x["severity"], 9), x["board"], x["task_id"]))
        seen_ids = set()
        printed = 0
        for f in ordered:
            key = (f["board"], f["task_id"])
            if key in seen_ids:
                continue
            seen_ids.add(key)
            print(f"- {f['severity'].upper()} {f['board']}:{f['task_id']} {f['kind']} · {f['status']} · {f['title'][:80]}")
            printed += 1
            if printed >= 8:
                break
    if scan_errors:
        print("Scan warnings:")
        for b in scan_errors[:5]:
            print(f"- {b['board']}: {'; '.join(b['errors'])}")
    print(f"JSON: {logfile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
