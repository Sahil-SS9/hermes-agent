#!/usr/bin/env python3
"""
WFA Delta Runner — wraps denji-wfa.py with state-file dedup.

Runs the full WFA scan every invocation but only emits output
when the set of findings has changed since the last delivery.
A finding is keyed by (task_id, issue_type, severity).

Intended cron: every 30 minutes, no-agent, zero token cost.
State file: /home/kensei/.hermes/governance/wfa-delta-state.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WFA_SCRIPT = "/home/kensei/.hermes/scripts/denji-wfa.py"
STATE_FILE = Path("/home/kensei/.hermes/governance/wfa-delta-state.json")
LOG_DIR = Path("/home/kensei/.hermes/governance/logboard")

TZ = timezone.utc


def run_wfa() -> tuple[str, dict | None]:
    """Run the WFA script, return stdout + parsed JSON if available."""
    try:
        result = subprocess.run(
            [sys.executable, WFA_SCRIPT],
            capture_output=True,
            text=True,
            timeout=120,
        )
        stdout = result.stdout.strip()
    except Exception as exc:
        return f"WFA runner error: {exc}", None

    # Find the JSON file that WFA writes
    json_path = None
    try:
        for line in stdout.split("\n"):
            if "JSON:" in line:
                json_path = Path(line.split("JSON:")[-1].strip())
                break
    except Exception:
        pass

    parsed = None
    if json_path and json_path.exists():
        try:
            parsed = json.loads(json_path.read_text())
        except Exception:
            pass

    return stdout, parsed


def build_finding_key(finding: dict) -> str:
    """Stable key for dedup: task_id + issue_type + severity."""
    tid = finding.get("task_id", finding.get("id", "?"))
    itype = finding.get("issue_type", finding.get("type", "?"))
    sev = finding.get("severity", "?")
    return f"{tid}|{itype}|{sev}"


def is_worse(old_sev: str, new_sev: str) -> bool:
    """Check if severity escalated."""
    order = {"info": 0, "notice": 1, "warning": 2, "error": 3, "critical": 4}
    return order.get(new_sev, 0) > order.get(old_sev, 0)


def compare_findings(old_keys: set, new_findings: list) -> dict:
    """Compare old vs new finding keys. Returns delta report."""
    new_keys = {build_finding_key(f) for f in new_findings}
    added = new_keys - old_keys
    removed = old_keys - new_keys
    # Check for severity escalation
    escalated = []
    old_map = {}
    if STATE_FILE.exists():
        try:
            # rebuild old key -> severity
            for f in json.loads(STATE_FILE.read_text()).get("findings", []):
                old_map[build_finding_key(f)] = f.get("severity", "info")
        except Exception:
            pass
    for f in new_findings:
        key = build_finding_key(f)
        if key in old_map and is_worse(old_map[key], f.get("severity", "info")):
            escalated.append(key)

    return {
        "same_count": len(new_keys & old_keys),
        "added": sorted(added),
        "removed": sorted(removed),
        "escalated": sorted(escalated),
        "total": len(new_keys),
    }


def save_state(stdout: str, findings: list):
    """Save current findings to state file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "updated_at": datetime.now(TZ).isoformat(),
        "findings": [
            {
                "task_id": f.get("task_id", f.get("id", "?")),
                "issue_type": f.get("issue_type", f.get("type", "?")),
                "severity": f.get("severity", "?"),
                "title": f.get("title", ""),
                "board": f.get("board", ""),
            }
            for f in findings
        ],
    }
    STATE_FILE.write_text(json.dumps(state, indent=2))


def main():
    stdout, parsed = run_wfa()

    findings = parsed.get("findings", []) if parsed else []
    old_keys: set = set()
    if STATE_FILE.exists():
        try:
            old_keys = {build_finding_key(f) for f in
                        json.loads(STATE_FILE.read_text()).get("findings", [])}
        except Exception:
            pass

    delta = compare_findings(old_keys, findings)

    # Decision rules for output:
    # - First run (no state file): always output
    # - New findings added: output
    # - Severity escalated: output
    # - Nothing changed: SILENT
    # - Findings removed: output (regression may help)

    first_run = old_keys == set()

    if first_run:
        print(stdout)
        save_state(stdout, findings)
        return

    if delta["added"]:
        print(stdout)
        save_state(stdout, findings)
        return

    if delta["escalated"]:
        print(stdout)
        save_state(stdout, findings)
        return

    # Findings removed — brief delta-only output
    if delta["removed"]:
        print(f"WFA Delta · {datetime.now(TZ).strftime('%d/%m/%y %H:%M:%S')} UTC")
        print(f"Findings: {delta['total']} total · {len(delta['removed'])} removed")
        print("Removed findings (task_id | issue_type):")
        for r in delta["removed"]:
            print(f"  - {r}")
        save_state(stdout, findings)
        return

    # No change at all — silent
    # Do NOT update state file so next run with a change triggers output
    pass  # silent


if __name__ == "__main__":
    main()
