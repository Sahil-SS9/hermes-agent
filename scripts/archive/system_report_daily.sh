#!/usr/bin/env bash
set -euo pipefail
TODAY="$(TZ=Europe/London date +%d-%m-%y)"
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
now = datetime.now()
out = Path('/home/kensei/.hermes/runbooks/system-report') / now.strftime('%d-%m-%y')
# Backwards compatibility if collector still wrote ISO dir internally.
if not (out / 'system-report.json').exists():
    iso = Path('/home/kensei/.hermes/runbooks/system-report') / now.strftime('%Y-%m-%d')
    if (iso / 'system-report.json').exists():
        out = iso

data = json.loads((out / 'system-report.json').read_text())
html_path = out / 'system-report.html'
services = data.get('services', {})
cron_info = data.get('cron', {})
system = data.get('system', {})
doctor = data.get('doctor', {})
issues = []
for name, state in services.items():
    if state != 'active':
        issues.append(f'Service `{name}` is `{state}`')
for item in doctor.get('failures', []):
    issues.append(str(item))
for item in doctor.get('warnings', []):
    if 'computer_use' not in str(item):
        issues.append(str(item))
if cron_info.get('error', 0):
    issues.append(f"{cron_info.get('error')} cron job(s) failing")
emoji = '✅' if not issues else '⚠️'
print(f"{emoji} System report · {now.strftime('%d/%m/%Y %H:%M:%S')}")
print(f"checked · {cron_info.get('total', 0)} crons · {len(issues)} issue(s)")
print()
print(f"• Crons ok: {cron_info.get('ok', 0)}/{cron_info.get('total', 0)}")
print(f"• Disk: {system.get('disk_pct', '?')}")
print(f"• Memory: {system.get('mem_used', '?')}")
for item in issues[:2]:
    print(f"• {item}")
if html_path.exists():
    print()
    print(f"MEDIA:{html_path}")
PY
