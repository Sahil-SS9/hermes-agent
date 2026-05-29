#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from croniter import croniter as _croniter

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
CRON_MISSED_GRACE_MINUTES = 10
CRON_OUTPUT = HERMES / 'cron' / 'output'


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
    """Check for cron jobs whose scheduled next run is overdue.

    A new cron with ``last_run_at=None`` is healthy while its first
    ``next_run_at`` is still in the future. Alert only when the scheduler has
    missed a due time, not merely because a job has never had a first run.
    """
    try:
        data = json.loads(JOBS.read_text(errors='replace'), strict=False)
    except Exception:
        return None
    jobs = data.get('jobs', [])
    gaps = []
    grace = timedelta(minutes=CRON_MISSED_GRACE_MINUTES)
    for j in jobs:
        if not j.get('enabled'):
            continue
        name = j.get('name', '?')
        schedule = j.get('schedule', {})
        if isinstance(schedule, dict):
            expr = schedule.get('expr', '')
        else:
            expr = str(schedule)
        # Only inspect explicit cron expressions here; interval jobs use their
        # own next-run cadence and are already visible in cron status.
        if not expr or '*/' in expr or 'interval' in str(schedule):
            continue

        next_run = j.get('next_run_at')
        if not next_run:
            if not j.get('last_run_at'):
                gaps.append(f'`{name}` — no last_run_at or next_run_at')
            continue
        try:
            next_dt = datetime.fromisoformat(next_run)
        except Exception:
            continue
        if now <= next_dt + grace:
            continue

        last_run = j.get('last_run_at')
        overdue_minutes = int((now - next_dt).total_seconds() / 60)
        if not last_run:
            gaps.append(f'`{name}` — first run overdue by {overdue_minutes}m (next_run_at {next_run})')
            continue
        try:
            last_dt = datetime.fromisoformat(last_run)
            age_hours = (now - last_dt).total_seconds() / 3600
            gaps.append(f'`{name}` — next run overdue by {overdue_minutes}m; last run {age_hours:.0f}h ago')
        except Exception:
            gaps.append(f'`{name}` — next run overdue by {overdue_minutes}m; last_run_at unreadable')
    if gaps:
        return {
            'title': f'{len(gaps)} cron(s) overdue',
            'body': 'Cron jobs whose next_run_at is overdue beyond the scheduler grace window:\\n' + '\\n'.join(gaps[:6]),
            'assignee': 'wesker', 'priority': 'P2',
            'key': f'audit-cron-gap-{now.date()}',
        }
    return None


def _newest_output_mtime(job_id: str) -> float | None:
    """Return the mtime (epoch) of the newest output file in a cron's output dir.

    Returns None if the output dir doesn't exist or has no files.
    Skips legacy subdirectories like 22-05-26/.
    """
    outdir = CRON_OUTPUT / job_id
    if not outdir.is_dir():
        return None
    newest = None
    for entry in outdir.iterdir():
        if not entry.is_file():
            continue
        mtime = entry.stat().st_mtime
        if newest is None or mtime > newest:
            newest = mtime
    return newest


def cron_stale_check(jobs: list[dict], now: datetime) -> list[dict]:
    """Run stale-detection on enabled cron jobs.

    Returns a list of stale findings, one per suspect job. Each finding has
    ``name``, ``reason``, and optionally ``details`` for the LLM to format.

    Three false-positive guards built in:

    1. **File mtime primary**: If the newest output file mtime falls within the
       cron schedule's previous expected window, the job is live even if
       ``last_run_at`` metadata is stale (in-flight LLM cron, metadata-updates-after
       pattern, etc.).

    2. **New-cron skip**: If a cron has ``last_run_at=None`` and its
       ``next_run_at`` is in the future, it's a brand-new cron waiting for its
       first slot. This is healthy, not stale. (Fixes ``denji-self-eval-reminder``
       SUSPEND false positive.)

    3. **Scheduled-window jobs**: Crons like ``0 9-20 * * *`` (active 9AM-8PM
       only) are not expected to produce output outside their window. The
       ``prev_due`` from croniter correctly reflects the last schedule firing,
       so no special handling needed — croniter handles ranges naturally.

    Jobs without a parseable cron expression (interval, one-shot) are skipped.
    """
    TZ = now.tzinfo or ZoneInfo('Europe/London')
    if TZ is None:
        TZ = ZoneInfo('Europe/London')

    stale: list[dict] = []

    for j in jobs:
        if not j.get('enabled'):
            continue
        name = j.get('name', '?')
        job_id = j.get('id', '')
        schedule = j.get('schedule', {})
        if isinstance(schedule, dict):
            expr = schedule.get('expr', '')
        else:
            expr = str(schedule)
        # Skip interval and one-shot jobs — only cron expressions here.
        if not expr or '*/' in expr or 'interval' in str(schedule) or 'oneshot' in str(schedule):
            continue

        # Guard 2: new cron with future first-run and no history.
        last_run_at = j.get('last_run_at')
        next_run_at = j.get('next_run_at')
        if not last_run_at and next_run_at:
            try:
                next_dt = datetime.fromisoformat(next_run_at).astimezone(TZ)
                if next_dt > now:
                    # Brand-new cron, first run hasn't happened yet — skip.
                    continue
            except Exception:
                pass  # fall through to normal check

        # Get the cron expression's previous due time.
        try:
            import datetime as _dt_mod
            prev_due = _croniter(expr, now).get_prev(_dt_mod.datetime).astimezone(TZ)
        except Exception:
            # Unparseable expression — skip.
            continue

        grace = timedelta(minutes=CRON_MISSED_GRACE_MINUTES)

        # Signal 1: last_run_at metadata.
        last_dt = None
        if last_run_at:
            try:
                last_dt = datetime.fromisoformat(last_run_at).astimezone(TZ)
            except Exception:
                pass
        metadata_ok = last_dt is not None and last_dt >= prev_due - grace

        # Signal 2: newest output file mtime (primary).
        newest_mtime = _newest_output_mtime(job_id)
        file_ok = newest_mtime is not None
        if file_ok and newest_mtime is not None:
            file_dt = datetime.fromtimestamp(newest_mtime, TZ)
            file_ok = file_dt >= prev_due - grace

        # Signal 3: next_run_at freshness (for in-flight crons).
        next_ok = False
        if next_run_at:
            try:
                next_dt = datetime.fromisoformat(next_run_at).astimezone(TZ)
                # If next_run is recent or imminent, job is alive.
                if next_dt > now - timedelta(hours=2):
                    next_ok = True
            except Exception:
                pass

        if not metadata_ok and not file_ok and not next_ok:
            lines = []
            lines.append(f'Stale check failed: prev_due {prev_due.isoformat()}')
            if last_run_at:
                lines.append(f'last_run_at {last_run_at} (ok={metadata_ok})')
            else:
                lines.append(f'last_run_at missing')
            if newest_mtime is not None:
                lines.append(f'newest output mtime {datetime.fromtimestamp(newest_mtime, TZ).isoformat()} (ok={file_ok})')
            else:
                lines.append(f'no output files')
            if next_run_at:
                lines.append(f'next_run_at {next_run_at} (ok={next_ok})')
            stale.append({
                'name': name,
                'reason': 'no recent run detected from metadata, output files, or next_run schedule',
                'details': ' | '.join(lines),
            })

    return stale


def _enumerate_gateway_units() -> dict[str, int | None]:
    """Return {unit_name: MainPID, ...} for every hermes-gateway*.service unit."""
    code, out = run(['systemctl', 'list-unit-files', '--type=service', '--all'], timeout=15)
    if code != 0:
        return {}
    units = {}
    for line in out.splitlines():
        parts = line.split()
        if not parts or not parts[0].startswith('hermes-gateway'):
            continue
        name = parts[0].removesuffix('.service')
        code2, pid_out = run(['systemctl', 'show', '-p', 'MainPID', '--value', f'{name}.service'], timeout=10)
        pid = int(pid_out.strip()) if code2 == 0 and pid_out.strip().isdigit() else None
        units[name] = pid if pid and pid > 0 else None
    return units


def duplicate_gateway_finding(now: datetime) -> dict | None:
    """Check for duplicate or orphan gateway processes using systemd unit enumeration.

    Every intentional gateway should be tracked by a hermes-gateway*.service
    systemd unit. Orphan gateways (running outside systemd) or multiple PIDs
    within a single unit are the real anomalies.
    """
    units = _enumerate_gateway_units()
    unit_pids = {pid for pid in units.values() if pid is not None}

    # Live gateway PIDs via pgrep — verify each candidate is actually a python
    # gateway process (not a subshell/hyphen-echo artifact from pgrep itself).
    code, out = run(['pgrep', '-f', 'hermes_cli.main gateway'], timeout=10)
    if code != 0:
        live_pids: set[str] = set()
    else:
        raw = [p.strip() for p in out.splitlines() if p.strip()]
        live_pids = set()
        for pid in raw:
            code2, args_out = run(['ps', '-p', pid, '-o', 'args=', '--no-headers'], timeout=10)
            args = args_out.strip()
            if 'python' in args and 'hermes_cli.main' in args and 'gateway' in args:
                live_pids.add(pid)

    # Normalise to str for cross-type set comparison.
    unit_pids_str: set[str] = {str(p) for p in unit_pids}

    # Orphans: running gateway PIDs not tracked by any systemd unit.
    orphans = live_pids - unit_pids_str

    # Multi-PID units: systemd units whose MainPID isn't in the live set.
    # Only flag the primary hermes-gateway unit — profile-specific units
    # (hermes-gateway-*) have MainPID=None when idle, which is intentional.
    unhealthy_units = []
    for name, main_pid in units.items():
        if main_pid is not None and str(main_pid) not in live_pids:
            unhealthy_units.append(f'{name}: MainPID {main_pid} not in live gateway set')
    if units.get('hermes-gateway') is None:
        unhealthy_units.append('hermes-gateway: no MainPID (service not running)')

    findings = []
    if orphans:
        findings.append(
            f'`{len(orphans)}` gateway PIDs not owned by any hermes-gateway*.service: '
        )
    if unhealthy_units:
        findings.extend(unhealthy_units)

    if not findings and not orphans:
        return None

    lines = []
    if orphans:
        pid_list = ', '.join(sorted(orphans))
        lines.append(f'Orphan gateway PIDs: `{pid_list}`. Not tracked by any systemd `hermes-gateway*.service` unit.')
    if unhealthy_units:
        lines.append('Unhealthy gateway units:')
        lines.extend(f'  - {u}' for u in unhealthy_units)
    if unit_pids:
        lines.append(f'Known systemd gateway units: `{len(unit_pids)}` active MainPIDs.')
    lines.append(f'`systemctl list-unit-files | grep hermes-gateway` shows `{len(units)}` total units.')

    return {
        'title': f'Gateway PID anomaly: {len(orphans)} orphan(s), {len(unhealthy_units)} unhealthy unit(s)',
        'body': '\\n'.join(lines),
        'assignee': 'wesker', 'priority': 'P2',
        'key': f'audit-gateway-anomaly-{now.date()}',
    }


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

    # Recently failed enabled cron jobs. A failed heartbeat means the audit
    # itself went dark, so flag that as P1 so the priority sort below keeps it
    # above housekeeping findings and the 3-task cap can never drop it. The body
    # points at the common provider/key-limit cause that breaks many LLM crons
    # at once.
    for j in jobs:
        if not j.get('enabled'):
            continue
        if j.get('last_status') == 'error':
            is_self = j.get('name') == 'kensei-heartbeat-audit'
            findings.append({
                'title': f"Cron {j.get('name')} failed last run",
                'body': (
                    f"Cron `{j.get('name')}` last_status is `error`. "
                    f"Check `/home/kensei/.hermes/cron/output/{j.get('id')}` and logs. "
                    "If it is a provider/key limit (e.g. OpenRouter 403 monthly limit), the "
                    "model route needs attention since many LLM crons share it."
                ),
                'assignee': 'wesker',
                'priority': 'P1' if is_self else 'P2',
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

    # Stale-detection: uses file mtime as primary signal to avoid false positives
    # on in-flight LLM crons, metadata-update-after patterns, and new crons with
    # future first-run schedules.
    stale_findings = cron_stale_check(jobs, now)
    for sf in stale_findings:
        findings.append({
            'title': f"Cron {sf['name']} appears stale",
            'body': f"Cron `{sf['name']}` {sf['reason']}. Details: {sf.get('details', '')}. Check status and consider pausing or removing.",
            'assignee': 'wesker',
            'priority': 'P2',
            'key': f"audit-stale-cron-{sf['name']}-{now.date()}",
        })

    dup_gw_finding = duplicate_gateway_finding(now)
    if dup_gw_finding:
        findings.append(dup_gw_finding)

    # Cap at 3 tasks per run to avoid notification spam, but file by severity so
    # outages (P1) always win over routine housekeeping (P2).
    priority_rank = {'P1': 0, 'P2': 1, 'P3': 2}
    findings.sort(key=lambda f: priority_rank.get(f.get('priority', 'P2'), 1))

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
