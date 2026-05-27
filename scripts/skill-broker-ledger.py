#!/usr/bin/env python3
"""
Skill Borrow Ledger Management Script

Append-only JSONL at /home/kensei/.hermes/governance/skill-broker-ledger.jsonl

Usage:
  python3 skill-broker-ledger.py borrow <profile> <skill> <task_id> [board]
  python3 skill-broker-ledger.py revoke <event_id> <task_result> [recommendation]
  python3 skill-broker-ledger.py count <profile> <skill> [months]
  python3 skill-broker-ledger.py deny <profile> <skill> <task_id> <reason> [board]
  python3 skill-broker-ledger.py list [--profile <p>] [--skill <s>] [--limit <n>]
  python3 skill-broker-ledger.py review [--months <n>]
  python3 skill-broker-ledger.py status  # Quick summary of recent activity
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LEDGER_PATH = Path("/home/kensei/.hermes/governance/skill-broker-ledger.jsonl")

# ---- Safety Lists ----

NEVER_GRANT = {
    # Skills that modify configs, auth, or service state
    "governance",  # Only Denji
    "profile-config-mutator",  # Changes other profiles' configs
    "service-restarter",  # Restarts services
    "provider-editor",  # Modifies provider/auth/routing
    "auth-editor",  # Modifies auth configs
    "routing-editor",  # Modifies routing configs
    # Admin-level operations
    "kanban-ops",  # Direct DB manipulation
    "soyl-editor",  # Modifies other profile SOUL.md files
}

SAFE_TO_GRANT = {
    # Research skills
    "arxiv", "blogwatcher", "market-research", "llm-wiki",
    # Coding skills
    "test-driven-development", "github-pr-workflow", "github-code-review",
    "github-issues", "subagent-driven-development",
    # Content skills
    "social-content", "avoid-ai-writing", "design-md",
    # Tool/domain skills
    "code-discovery-pipeline", "external-skill-integration",
    "gbrain-knowledge", "spotify", "maps", "youtube-content",
    "huggingface-hub", "webhook-subscriptions",
}

# ---- Ledger Operations ----

def _read_ledger():
    """Read all entries from the ledger."""
    if not LEDGER_PATH.exists():
        return []
    entries = []
    with open(LEDGER_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _append_to_ledger(entry):
    """Append one entry to the ledger."""
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def _next_event_id():
    """Generate a sequential event ID based on today's date."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    existing = _read_ledger()
    today_events = [e for e in existing if e.get("event_id", "").startswith(f"borrow-{today}")]
    seq = len(today_events) + 1
    return f"borrow-{today}-{seq:03d}"


def _now_ts():
    return int(time.time())


def cmd_borrow(profile, skill, task_id, board="ops"):
    """Record a temporary skill grant."""
    now_ts = _now_ts()
    
    # First, create the borrow entry
    event_id = _next_event_id()
    entry = {
        "event_id": event_id,
        "ts": now_ts,
        "task_id": task_id,
        "board": board,
        "worker_profile": profile,
        "skill_borrowed": skill,
        "grant_type": "temporary",
        "grant_expiry": "task_completion",
        "success": True,
        "task_result": None,
        "revoked_at": None,
        "recommendation": None,
    }
    _append_to_ledger(entry)
    print(json.dumps({"event_id": event_id, "status": "granted", "entry": entry}))
    return event_id


def cmd_revoke(event_id, task_result="completed"):
    """Mark a borrow event as revoked upon task completion."""
    entries = _read_ledger()
    now_ts = _now_ts()
    found = False
    
    new_entries = []
    for entry in entries:
        if entry.get("event_id") == event_id and entry.get("revoked_at") is None:
            entry["task_result"] = task_result
            entry["revoked_at"] = now_ts
            found = True
        new_entries.append(entry)
    
    if not found:
        print(json.dumps({"error": f"event_id {event_id} not found or already revoked"}))
        return 1
    
    # Rewrite the entire ledger
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "w", encoding="utf-8") as f:
        for entry in new_entries:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
    
    print(json.dumps({"event_id": event_id, "status": "revoked", "revoked_at": now_ts}))
    return 0


def cmd_count(profile, skill, months=1):
    """Count borrows of a skill by a profile in the last N months."""
    entries = _read_ledger()
    cutoff = time.time() - (months * 30 * 24 * 3600)
    
    count = 0
    for entry in entries:
        if (entry.get("worker_profile") == profile
                and entry.get("skill_borrowed") == skill
                and entry.get("ts", 0) >= cutoff
                and entry.get("grant_type") == "temporary"):
            count += 1
    
    print(json.dumps({"profile": profile, "skill": skill, "months": months, "borrows": count}))
    return 0


def cmd_deny(profile, skill, task_id, reason, board="ops"):
    """Log a denied borrow request."""
    now_ts = _now_ts()
    event_id = _next_event_id()
    entry = {
        "event_id": event_id,
        "ts": now_ts,
        "task_id": task_id,
        "board": board,
        "worker_profile": profile,
        "skill_borrowed": skill,
        "grant_type": "temporary",
        "grant_expiry": "task_completion",
        "success": False,
        "task_result": "denied",
        "revoked_at": None,
        "recommendation": f"denied: {reason}",
    }
    _append_to_ledger(entry)
    print(json.dumps({"event_id": event_id, "status": "denied", "entry": entry}))
    return 0


def cmd_list(profile=None, skill=None, limit=20):
    """List recent ledger entries."""
    entries = _read_ledger()
    if profile:
        entries = [e for e in entries if e.get("worker_profile") == profile]
    if skill:
        entries = [e for e in entries if e.get("skill_borrowed") == skill]
    
    entries.sort(key=lambda e: e.get("ts", 0), reverse=True)
    entries = entries[:limit]
    print(json.dumps(entries, indent=2))
    return 0


def cmd_review(months=3):
    """Generate skill-borrow analysis summary."""
    entries = _read_ledger()
    cutoff = time.time() - (months * 30 * 24 * 3600)
    recent = [e for e in entries if e.get("ts", 0) >= cutoff]
    
    # Group by (profile, skill)
    from collections import defaultdict
    groups = defaultdict(list)
    for entry in recent:
        key = (entry.get("worker_profile"), entry.get("skill_borrowed"))
        groups[key].append(entry)
    
    review = []
    for (profile, skill), group in sorted(groups.items(), key=lambda x: len(x[1]), reverse=True):
        count = len(group)
        success_count = sum(1 for e in group if e.get("success"))
        action = "monitor"
        if count >= 6:
            action = "ESCALATE: recommend permanent add"
        elif count >= 4:
            action = "flag Denji for review"
        review.append({
            "profile": profile,
            "skill": skill,
            "borrows": count,
            "successes": success_count,
            "action": action,
        })
    
    print(json.dumps({"period_months": months, "entries_analysed": len(recent), "findings": review}, indent=2))
    return 0


def cmd_status():
    """Quick summary."""
    entries = _read_ledger()
    total = len(entries)
    active = sum(1 for e in entries if e.get("success") and e.get("revoked_at") is None)
    denied = sum(1 for e in entries if e.get("success") is False)
    
    now_ts = _now_ts()
    month_ago = now_ts - (30 * 24 * 3600)
    recent = sum(1 for e in entries if e.get("ts", 0) >= month_ago)
    
    top_borrowers = {}
    for e in entries:
        if e.get("success"):
            p = e.get("worker_profile", "?")
            top_borrowers[p] = top_borrowers.get(p, 0) + 1
    
    sorted_top = sorted(top_borrowers.items(), key=lambda x: x[1], reverse=True)[:5]
    
    print(json.dumps({
        "total_entries": total,
        "active_borrows": active,
        "denied": denied,
        "last_30_days": recent,
        "top_borrower_profiles": [{"profile": p, "count": c} for p, c in sorted_top],
        "ledger_path": str(LEDGER_PATH),
    }, indent=2))
    return 0


# ---- Entry Point ----

def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        return 1
    
    cmd = sys.argv[1]
    
    if cmd == "borrow":
        if len(sys.argv) < 5:
            print("Usage: ... borrow <profile> <skill> <task_id> [board]")
            return 1
        profile = sys.argv[2]
        skill = sys.argv[3]
        task_id = sys.argv[4]
        board = sys.argv[5] if len(sys.argv) > 5 else "ops"
        
        # Check safety
        if skill in NEVER_GRANT:
            cmd_deny(profile, skill, task_id, f"skill '{skill}' is on the NEVER_GRANT list", board)
            return 0
        
        # Check frequency
        count_entries = _read_ledger()
        cutoff = time.time() - (30 * 24 * 3600)
        freq_count = sum(1 for e in count_entries
                         if e.get("worker_profile") == profile
                         and e.get("skill_borrowed") == skill
                         and e.get("ts", 0) >= cutoff)
        
        if freq_count >= 6:
            cmd_deny(profile, skill, task_id,
                     f"frequency limit exceeded: {freq_count} borrows in last 30 days (max 5)", board)
            return 0
        
        cmd_borrow(profile, skill, task_id, board)
        
        # If 4-5, also print a flag note
        if freq_count >= 3:
            print(json.dumps({"warning": f"frequency_flag: {freq_count + 1} borrows this month — flag Denji for review if this exceeds 3"}))
        
        return 0
    
    elif cmd == "revoke":
        if len(sys.argv) < 3:
            print("Usage: ... revoke <event_id> [task_result]")
            return 1
        event_id = sys.argv[2]
        task_result = sys.argv[3] if len(sys.argv) > 3 else "completed"
        return cmd_revoke(event_id, task_result)
    
    elif cmd == "count":
        if len(sys.argv) < 4:
            print("Usage: ... count <profile> <skill> [months]")
            return 1
        profile = sys.argv[2]
        skill = sys.argv[3]
        months = int(sys.argv[4]) if len(sys.argv) > 4 else 1
        return cmd_count(profile, skill, months)
    
    elif cmd == "deny":
        if len(sys.argv) < 6:
            print("Usage: ... deny <profile> <skill> <task_id> <reason> [board]")
            return 1
        profile = sys.argv[2]
        skill = sys.argv[3]
        task_id = sys.argv[4]
        reason = sys.argv[5]
        board = sys.argv[6] if len(sys.argv) > 6 else "ops"
        return cmd_deny(profile, skill, task_id, reason, board)
    
    elif cmd == "list":
        profile = None
        skill = None
        limit = 20
        args = sys.argv[2:]
        for i, a in enumerate(args):
            if a == "--profile" and i + 1 < len(args):
                profile = args[i + 1]
            elif a == "--skill" and i + 1 < len(args):
                skill = args[i + 1]
            elif a == "--limit" and i + 1 < len(args):
                limit = int(args[i + 1])
        return cmd_list(profile, skill, limit)
    
    elif cmd == "review":
        months = 3
        args = sys.argv[2:]
        for i, a in enumerate(args):
            if a == "--months" and i + 1 < len(args):
                months = int(args[i + 1])
        return cmd_review(months)
    
    elif cmd == "status":
        return cmd_status()
    
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__.strip())
        return 1


if __name__ == "__main__":
    sys.exit(main())
