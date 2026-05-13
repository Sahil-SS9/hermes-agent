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
CHAT_ID = '-1003922682700'
THREAD_ID = '1'


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
    if task_id:
        run(['hermes', 'kanban', 'notify-subscribe', str(task_id), '--platform', 'telegram', '--chat-id', CHAT_ID, '--thread-id', THREAD_ID], timeout=15)
    return task_id


def main() -> int:
    now = datetime.now(ZoneInfo('Europe/London'))
    stamp = now.strftime('%a %d %b · %H:%M')
    data = json.loads(JOBS.read_text())
    jobs = data.get('jobs', [])

    findings = []

    # Enabled jobs must not reference missing skills.
    for j in jobs:
        if not j.get('enabled'):
            continue
        missing = [s for s in (j.get('skills') or []) if not skill_exists(s)]
        if missing:
            findings.append({
                'title': f"Cron {j.get('name')} references missing skill",
                'body': f"Cron `{j.get('name')}` references missing skill(s): {', '.join(missing)}. Remove the stale skill or install a vetted replacement.",
                'assignee': 'ops-lead',
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
                'assignee': 'ops-lead',
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
                'assignee': 'ops-lead',
                'priority': 'P2',
                'key': f"audit-cron-error-{j.get('id')}-{now.date()}",
            })

    # Gateway must be active.
    code, active = run(['systemctl', 'is-active', 'hermes-gateway'], timeout=10)
    if active.strip() != 'active':
        findings.append({
            'title': 'Hermes gateway is not active',
            'body': f"`systemctl is-active hermes-gateway` returned `{active}`. Cron and Telegram delivery are at risk.",
            'assignee': 'ops-lead',
            'priority': 'P1',
            'key': f"audit-gateway-inactive-{now.date()}",
        })

    filed = []
    for f in findings[:3]:
        task_id = create_task(f['title'], f['body'], f['assignee'], f['priority'], f['key'])
        if task_id:
            filed.append((task_id, f))

    if not filed:
        print('[SILENT]')
        return 0

    print(f"⚠️ <b>Audit heartbeat</b> · {stamp}")
    print(f"Filed {len(filed)} triage tasks · {max(0, len(findings)-len(filed))} overflow · target: cron/kanban")
    print()
    print('<b>Filed</b>')
    for task_id, f in filed:
        print(f"• <code>{html.escape(str(task_id))}</code> {html.escape(f['title'])} · {html.escape(f['priority'])} · {html.escape(f['assignee'])}")
    print()
    print(f"<blockquote expandable>Checked enabled crons, missing skills, native Kanban legacy loop drift, and gateway service state. Jobs checked: <code>{len(jobs)}</code></blockquote>")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
