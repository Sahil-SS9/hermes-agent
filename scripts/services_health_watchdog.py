#!/usr/bin/env python3
"""Alert-only watchdog for Hermes gateway/MCP process duplication.

Silent when healthy. Prints a Telegram-ready alert only when it sees a real
runtime risk: duplicate gateway processes, orphan MCP roots, port 8000 owned by
non-gateway process, or new Telegram polling conflicts.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

STATE_PATH = Path('/home/kensei/.hermes/state/services-health-watchdog.json')
LOG_PATHS = [
    Path('/home/kensei/.hermes/logs/errors.log'),
    Path('/home/kensei/.hermes/logs/gateway.log'),
]


def run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as exc:
        return exc.output or ''


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))


def process_rows() -> list[dict]:
    out = run(['ps', '-eo', 'pid=,ppid=,stat=,cmd='])
    rows = []
    for line in out.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        pid, ppid, stat, cmd = parts
        try:
            rows.append({'pid': int(pid), 'ppid': int(ppid), 'stat': stat, 'cmd': cmd})
        except ValueError:
            continue
    return rows


def descendants(pid: int, by_parent: dict[int, list[int]]) -> set[int]:
    seen: set[int] = set()
    stack = list(by_parent.get(pid, []))
    while stack:
        child = stack.pop()
        if child in seen:
            continue
        seen.add(child)
        stack.extend(by_parent.get(child, []))
    return seen


def port_8000_owner_pids() -> set[int]:
    out = run(['ss', '-ltnp'])
    pids: set[int] = set()
    for line in out.splitlines():
        if ':8000' not in line:
            continue
        for match in re.finditer(r'pid=(\d+)', line):
            pids.add(int(match.group(1)))
    return pids


def recent_telegram_conflicts(state: dict) -> tuple[int, str | None]:
    now = datetime.now()
    cutoff = now - timedelta(minutes=15)
    last_alerted = state.get('last_telegram_conflict_ts', '')
    newest = None
    count = 0
    ts_re = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
    for path in LOG_PATHS:
        if not path.exists():
            continue
        try:
            lines = path.read_text(errors='ignore').splitlines()[-1000:]
        except Exception:
            continue
        for line in lines:
            if 'Telegram polling conflict' not in line:
                continue
            m = ts_re.match(line)
            if not m:
                continue
            ts_s = m.group(1)
            try:
                ts = datetime.strptime(ts_s, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                continue
            if ts < cutoff:
                continue
            if ts_s <= last_alerted:
                continue
            count += 1
            if newest is None or ts_s > newest:
                newest = ts_s
    return count, newest


def main() -> int:
    state = load_state()
    rows = process_rows()
    by_pid = {r['pid']: r for r in rows}
    by_parent: dict[int, list[int]] = {}
    for r in rows:
        by_parent.setdefault(r['ppid'], []).append(r['pid'])

    gateway_pids = [
        r['pid'] for r in rows
        if 'hermes_cli.main gateway run' in r['cmd']
    ]

    interactive_hermes_pids = [
        r['pid'] for r in rows
        if '/home/kensei/.local/bin/hermes' in r['cmd']
        and 'gateway run' not in r['cmd']
        and 'dashboard' not in r['cmd']
    ]

    claude_pids = [
        r['pid'] for r in rows
        if r['cmd'].strip() == 'claude'
        or r['cmd'].endswith('/claude')
    ]

    mcp_roots = [
        r for r in rows
        if (
            'uv tool uvx workspace-mcp' in r['cmd']
            or 'ms-365-mcp-server --preset mail' in r['cmd']
            or 'npm exec @ycse/nanobanana-mcp' in r['cmd']
        )
    ]

    alerts: list[str] = []

    if len(gateway_pids) > 1:
        alerts.append(f'Duplicate Hermes gateway processes: {gateway_pids}')
    elif len(gateway_pids) == 0:
        alerts.append('Hermes gateway process not found')

    allowed_mcp_parents = set(gateway_pids) | set(interactive_hermes_pids) | set(claude_pids)
    allowed_descendants = set()
    for parent in allowed_mcp_parents:
        allowed_descendants |= descendants(parent, by_parent)
    suspect_mcp = []
    for r in mcp_roots:
        parent = by_pid.get(r['ppid'])
        if r['ppid'] not in allowed_mcp_parents and r['ppid'] not in allowed_descendants:
            parent_desc = parent['cmd'][:80] if parent else 'missing'
            suspect_mcp.append(f"pid={r['pid']} ppid={r['ppid']} parent={parent_desc} cmd={r['cmd'][:80]}")
    if suspect_mcp:
        alerts.append('Suspicious MCP root processes:\n' + '\n'.join(f'- {x}' for x in suspect_mcp[:8]))

    owner_pids = port_8000_owner_pids()
    if owner_pids:
        bad_owners = sorted(pid for pid in owner_pids if pid not in allowed_mcp_parents and pid not in allowed_descendants)
        if bad_owners:
            details = []
            for pid in bad_owners:
                details.append(f"pid={pid} cmd={by_pid.get(pid, {}).get('cmd', 'unknown')[:100]}")
            alerts.append('Port 8000 owned outside the system gateway tree:\n' + '\n'.join(f'- {x}' for x in details))

    conflict_count, newest_conflict_ts = recent_telegram_conflicts(state)
    if conflict_count:
        alerts.append(f'New Telegram polling conflicts in the last 15m: {conflict_count}')
        if newest_conflict_ts:
            state['last_telegram_conflict_ts'] = newest_conflict_ts

    state['last_run_at'] = datetime.now().isoformat(timespec='seconds')
    state['gateway_pids'] = gateway_pids
    state['interactive_hermes_pids'] = interactive_hermes_pids
    state['claude_pids'] = claude_pids
    save_state(state)

    if not alerts:
        return 0

    ts = datetime.now().strftime('%a %d %b · %H:%M')
    print(f"🔴 <b>Services alert</b> · {ts}")
    print(f"{len(alerts)} issues · action needed")
    print()
    print("<b>Findings</b>")
    for a in alerts[:5]:
        clean = a.split('\n')[0].replace('- ', '').strip()
        print(f"• {clean}")
    print()
    print(f"<code>sudo /home/kensei/.local/bin/hermes gateway restart --system</code>")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
