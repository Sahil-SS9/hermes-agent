#!/usr/bin/env bash
set -euo pipefail
TODAY="$(date +%F)"
OUT_DIR="/home/kensei/.hermes/runbooks/system-report/${TODAY}"
cd /home/kensei/repos/KenseiAgent
python3 scripts/system_report.py \
  --out-dir "$OUT_DIR" \
  --print-telegram \
  --include-media-tag >/dev/null
python3 - <<'PY'
import json
from pathlib import Path
from datetime import datetime
out = Path('/home/kensei/.hermes/runbooks/system-report') / datetime.now().strftime('%Y-%m-%d')
data = json.loads((out / 'system-report.json').read_text())
ts = datetime.now().strftime('%a %d %b · %H:%M')
services = data.get('services', {})
cron_info = data.get('cron', {})
system = data.get('system', {})
doctor = data.get('doctor', {})
token = data.get('token_health', {})
issues = []
for name, state in services.items():
    if state != 'active':
        issues.append(f'Service <code>{name}</code> is <code>{state}</code>')
for item in doctor.get('failures', []):
    issues.append(item)
for item in doctor.get('warnings', []):
    if 'computer_use' not in item:
        issues.append(item)
if cron_info.get('error', 0):
    issues.append(f"<code>{cron_info.get('error')}</code> cron job(s) failing")
emoji = '✅' if not issues else '⚠️'
print(f"{emoji} <b>System report</b> · {ts}")
print(f"{cron_info.get('ok', 0)}/{cron_info.get('total', 0)} crons ok · disk {system.get('disk_pct', '?')} · mem {system.get('mem_used', '?')}")
print()
if issues:
    print('<b>Watchlist</b>')
    for item in issues[:5]:
        print(f'• {item}')
    print()
print('<b>Full report</b>')
print(f"<code>{out / 'system-report.html'}</code>")
print()
print(f"MEDIA:{out / 'system-report.html'}")
PY
