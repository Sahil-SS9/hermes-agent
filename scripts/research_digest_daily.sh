#!/usr/bin/env bash
set -euo pipefail
TODAY="$(date +%F)"
OUT_DIR="/home/kensei/.hermes/runbooks/research-digest/${TODAY}"
cd /home/kensei/repos/KenseiAgent
python3 scripts/research_digest.py \
  --out-dir "$OUT_DIR" \
  --time-range day \
  --fallback-time-range week \
  --selected-limit 10 \
  --print-telegram \
  --include-media-tag >/dev/null
python3 - <<'PY'
import json, html
from pathlib import Path
from datetime import datetime
out = Path('/home/kensei/.hermes/runbooks/research-digest') / datetime.now().strftime('%Y-%m-%d')
data = json.loads((out / 'research-digest.json').read_text())
if data.get('silent'):
    print('[SILENT]')
    raise SystemExit
selected = data.get('selected', [])
lanes = {}
for item in selected:
    lane = (item.get('lane') or 'Other').replace('A: ', '').replace('B: ', '').replace('C: ', '')
    lanes[lane] = lanes.get(lane, 0) + 1
ts = datetime.now().strftime('%a %d %b · %H:%M')
print(f"🟡 <b>Research digest</b> · {ts}")
print(f"{len(selected)} signals · {data.get('candidates_considered', 0)} candidates · {data.get('time_range_used', 'day')}")
print()
print('<b>Top signals</b>')
for item in selected[:3]:
    title = html.escape(item.get('title','Untitled'))
    source = html.escape(item.get('source','source'))
    url = html.escape(item.get('url',''))
    if url:
        print(f'• <a href="{url}">{title}</a> · {source}')
    else:
        print(f'• {title} · {source}')
print()
print('<b>Lanes</b>')
for lane, count in sorted(lanes.items()):
    print(f'• {html.escape(lane)}: <code>{count}</code>')
print()
print(f"<blockquote expandable>Sources considered: <code>{data.get('sources_considered', 0)}</code> · RSS feeds: <code>{data.get('rss_source_count', 0)}</code> · Queries: <code>{data.get('query_count', 0)}</code>\nReport: <code>{out / 'research-digest.html'}</code></blockquote>")
print()
print(f"MEDIA:{out / 'research-digest.html'}")
PY
