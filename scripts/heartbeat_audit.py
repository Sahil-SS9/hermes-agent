#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERMES = Path('/home/kensei/.hermes')
JOBS = HERMES / 'cron' / 'jobs.json'
SKILLS = HERMES / 'skills'
TAVILY_PROBE = HERMES / 'scripts' / 'tavily_health_probe.py'


def run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode, p.stdout.strip()
    except Exception as e:
        return 99, str(e)


def skill_exists(name: str) -> bool:
    if (SKILLS / name / 'SKILL.md').exists():
        return True
    return any((p / name / 'SKILL.md').exists() for p in SKILLS.iterdir() if p.is_dir())


def create_task(title: str, body: str, assignee: str, priority: str, key: str) -> str | None:
    cmd = [
        'hermes', 'kanban', 'create', title,
        '--body', body,
        '--assignee', assignee,
        '--priority', priority,
        '--triage',
        '--idempotency-key', key,
        '--created-by', 'kensei-heartbeat-audit',
        '--json',
    ]
    code, out = run(cmd, timeout=30)
    if code != 0:
        return None
    try:
        data = json.loads(out)
        task_id = data.get('task_id') or data.get('id')
    except Exception:
        task_id = out.split()[0] if out else None
    return task_id


def tavily_health_finding(now: datetime) -> dict | None:
    """Run the Tavily health probe and return a finding only after threshold breach."""
    if not TAVILY_PROBE.exists():
        return {
            'title': 'Tavily health probe script missing',
            'body': f"Heartbeat expected Tavily probe at `{TAVILY_PROBE}` but the file is missing. Tavily API health is not being monitored.",
            'assignee': 'wesker',
            'priority': 'P2',
            'key': f"audit-tavily-probe-missing-{now.date()}",
        }

    code, out = run(['python3', str(TAVILY_PROBE), '--threshold', '3', '--json'], timeout=20)
    if code != 0:
        return {
            'title': 'Tavily health probe failed to run',
            'body': f"`{TAVILY_PROBE}` exited with code `{code}`. Output: `{html.escape(out[:500])}`. Tavily API health may be unmonitored.",
            'assignee': 'wesker',
            'priority': 'P2',
            'key': f"audit-tavily-probe-runtime-{now.date()}",
        }

    try:
        probe = json.loads(out)
    except Exception:
        return {
            'title': 'Tavily health probe returned invalid JSON',
            'body': f"`{TAVILY_PROBE}` returned non-JSON output: `{html.escape(out[:500])}`. Tavily API health may be unmonitored.",
            'assignee': 'wesker',
            'priority': 'P2',
            'key': f"audit-tavily-probe-json-{now.date()}",
        }

    if not probe.get('alert'):
        return None

    failures = probe.get('consecutive_failures')
    threshold = probe.get('threshold')
    kind = probe.get('last_failure_kind') or 'failure'
    summary = probe.get('last_summary') or 'Tavily probe failed repeatedly'
    status_code = probe.get('last_status_code')
    return {
        'title': f"Tavily API health alert: {kind}",
        'body': (
            f"Tavily API probe has failed `{failures}` consecutive times (threshold `{threshold}`). "
            f"Latest failure: `{html.escape(str(kind))}`; status code `{html.escape(str(status_code))}`; summary: {html.escape(str(summary))}. "
            f"Probe logs: `/home/kensei/.hermes/logs/tavily_health.jsonl`; state: `/home/kensei/.hermes/state/tavily_health.json`."
        ),
        'assignee': 'wesker',
        'priority': 'P1' if kind in ('auth_failed', 'quota_exhausted') else 'P2',
        'key': f"audit-tavily-api-{kind}-{now.date()}",
    }


MEM_THRESHOLD_MB = 500
SERVICES_WATCH_NAMES = ['hermes-gateway', 'docker', 'postgresql']
MAX_CRON_GAP_HOURS = 3


def memory_health_finding(now: datetime) -> dict | None:
    """Check available memory. Alert below threshold."""
    code, out = run(['free', '-m'], timeout=10)
    if code != 0:
        return {
            'title': 'Memory check failed to run',
            'body': f'`free -m` exited with code `{code}`. Cannot monitor memory health.',
            'assignee': 'wesker', 'priority': 'P2',
            'key': f'audit-memory-cmd-fail-{now.date()}',
        }
    for line in out.splitlines():
        if line.startswith('Mem:'):
            parts = line.split()
            if len(parts) >= 7:
                free_mb = int(parts[6])  # available
                total_mb = int(parts[1])
                pct = int((total_mb - free_mb) / total_mb * 100)
                if free_mb < MEM_THRESHOLD_MB:
                    return {
                        'title': f'Low memory: {free_mb}MB available ({pct}% used)',
                        'body': f'Available memory is `{free_mb}MB` (threshold `{MEM_THRESHOLD_MB}MB`). Total: `{total_mb}MB`, usage: `{pct}%`. Check running processes.',
                        'assignee': 'wesker', 'priority': 'P2',
                        'key': f'audit-low-memory-{now.date()}',
                    }
    return None


def cron_gap_finding(now: datetime) -> dict | None:
    """Check last_run_at freshness for critical daily crons."""
    try:
        data = json.loads(JOBS.read_text(errors='replace'), strict=False)
    except Exception:
        return None
    jobs = data.get('jobs', [])
    gaps = []
    for j in jobs:
        if not j.get('enabled'):
            continue
        name = j.get('name', '?')
        last_run = j.get('last_run_at')
        schedule = j.get('schedule', {})
        if isinstance(schedule, dict):
            expr = schedule.get('expr', '')
        else:
            expr = str(schedule)
        # Only check daily crons (those with a HH:MM pattern, not intervals)
        if not expr or '*/' in expr or 'interval' in str(schedule):
            continue
        if not last_run:
            gaps.append(f'`{name}` — never run')
            continue
        try:
            from datetime import timezone
            last_dt = datetime.fromisoformat(last_run)
            age_hours = (now - last_dt).total_seconds() / 3600
            if age_hours > MAX_CRON_GAP_HOURS:
                gaps.append(f'`{name}` — last run {age_hours:.0f}h ago')
        except Exception:
            continue
    if gaps:
        return {
            'title': f'{len(gaps)} cron(s) missed schedule',
            'body': 'Daily cron jobs that have not run recently:\\n' + '\\n'.join(gaps[:6]),
            'assignee': 'wesker', 'priority': 'P2',
            'key': f'audit-cron-gap-{now.date()}',
        }
    return None


def duplicate_gateway_finding(now: datetime) -> dict | None:
    """Check for duplicate gateway processes (one main PID + its workers is normal)."""
    code, out = run(['pgrep', '-f', 'hermes_cli.main gateway'], timeout=10)
    if code != 0:
        return None
    pids = [p.strip() for p in out.splitlines() if p.strip()]
    # Normal: 12 gateway instances for 8 bots + workers. More than 16 is suspicious.
    if len(pids) > 16:
        return {
            'title': f'Potential duplicate gateway: {len(pids)} PIDs',
            'body': f'`pgrep -f hermes_cli.main gateway` returned {len(pids)} PIDs. Expected ~12 for 8-bot setup. Check `ps aux | grep gateway`.',
            'assignee': 'wesker', 'priority': 'P2',
            'key': f'audit-duplicate-gateway-{now.date()}',
        }
    return None


def main() -> int:
    now = datetime.now(ZoneInfo('Europe/London'))
    stamp = now.strftime('%a %d %b · %H:%M')
    data = json.loads(JOBS.read_text(errors='replace'), strict=False)
    jobs = data.get('jobs', [])

    findings = []

    tavily_finding = tavily_health_finding(now)
    if tavily_finding:
        findings.append(tavily_finding)

    # Enabled jobs must not reference missing skills.
    for j in jobs:
        if not j.get('enabled'):
            continue
        missing = [s for s in (j.get('skills') or []) if not skill_exists(s)]
        if missing:
            findings.append({
                'title': f"Cron {j.get('name')} references missing skill",
                'body': f"Cron `{j.get('name')}` references missing skill(s): {', '.join(missing)}. Remove the stale skill or install a vetted replacement.",
                'assignee': 'wesker',
                'priority': 'P2',
                'key': f"audit-cron-missing-skill-{j.get('id')}-{'-'.join(missing)}",
            })

    # Legacy file-backlog loops should stay paused after native Kanban orchestration landed.
    for name in ('kensei-backlog-processor', 'kensei-kanban-instigator'):
        j = next((x for x in jobs if x.get('name') == name), None)
        if j and j.get('enabled'):
            findings.append({
                'title': f"Legacy {name} cron still enabled",
                'body': f"`{name}` is a pre-native-Kanban loop. Native gateway dispatcher is active, so this cron should stay paused unless explicitly redesigned.",
                'assignee': 'wesker',
                'priority': 'P2',
                'key': f"audit-legacy-kanban-cron-enabled-{name}",
            })

    # Recently failed enabled cron jobs.
    for j in jobs:
        if not j.get('enabled'):
            continue
        if j.get('last_status') == 'error':
            findings.append({
                'title': f"Cron {j.get('name')} failed last run",
                'body': f"Cron `{j.get('name')}` last_status is `error`. Check `/home/kensei/.hermes/cron/output/{j.get('id')}` and logs.",
                'assignee': 'wesker',
                'priority': 'P2',
                'key': f"audit-cron-error-{j.get('id')}-{now.date()}",
            })

    # Gateway must be active.
    code, active = run(['systemctl', 'is-active', 'hermes-gateway'], timeout=10)
    if active.strip() != 'active':
        findings.append({
            'title': 'Hermes gateway is not active',
            'body': f"`systemctl is-active hermes-gateway` returned `{active}`. Cron and Discord delivery are at risk.",
            'assignee': 'wesker',
            'priority': 'P1',
            'key': f"audit-gateway-inactive-{now.date()}",
        })

    # --- Absorbed watchdog probes (replaces standalone services_health, memory_watchdog, cron-gap) ---
    mem_finding = memory_health_finding(now)
    if mem_finding:
        findings.append(mem_finding)

    gap_finding = cron_gap_finding(now)
    if gap_finding:
        findings.append(gap_finding)

    dup_gw_finding = duplicate_gateway_finding(now)
    if dup_gw_finding:
        findings.append(dup_gw_finding)

    filed = []
    for f in findings[:3]:
        task_id = create_task(f['title'], f['body'], f['assignee'], f['priority'], f['key'])
        if task_id:
            filed.append((task_id, f))

    if not filed:
        print('[SILENT]')
        return 0

    print(f"⚠️ **Audit heartbeat** · {stamp}")
    print(f"Filed {len(filed)} triage tasks · {max(0, len(findings)-len(filed))} overflow · target: cron/kanban")
    print()
    print('**Filed**')
    for task_id, f in filed:
        print(f"• `{str(task_id)}` {f['title']} · {f['priority']} · {f['assignee']}")
    print()
    print(f"Checked enabled crons, missing skills, native Kanban legacy loop drift, gateway service state, and Tavily API health. Jobs checked: `{len(jobs)}`. Tavily probe threshold: `3` consecutive failures.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
