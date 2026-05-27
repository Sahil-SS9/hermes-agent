#!/usr/bin/env python3
"""Deterministic Discord-safe Kanban daily digest with HTML attachment."""
from __future__ import annotations

import datetime as dt
import html
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

DB = Path('/home/kensei/.hermes/kanban.db')
BASE = Path('/home/kensei/.hermes/runbooks/kanban-digest')
TZ = ZoneInfo('Europe/London')
now = dt.datetime.now(TZ)
yesterday = (now - dt.timedelta(days=1)).date()
start = int(dt.datetime.combine(yesterday, dt.time.min, TZ).timestamp())
end = int(dt.datetime.combine(yesterday + dt.timedelta(days=1), dt.time.min, TZ).timestamp())
out_dir = BASE / yesterday.strftime('%d-%m-%y')
out_dir.mkdir(parents=True, exist_ok=True)
html_path = out_dir / 'kanban-digest.html'

def short(s: str | None, n: int = 86) -> str:
    s = ' '.join((s or '').split())
    return s if len(s) <= n else s[: n - 1].rstrip() + '…'

def fmt_ts(ts):
    if not ts:
        return ''
    try:
        return dt.datetime.fromtimestamp(int(ts), TZ).strftime('%d/%m/%Y %H:%M:%S')
    except Exception:
        return ''

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
rows = [dict(r) for r in conn.execute('''
SELECT id,title,status,assignee,priority,created_at,started_at,completed_at,updated_at,status_reason,last_failure_error,result
FROM tasks
WHERE
  (completed_at IS NOT NULL AND completed_at >= ? AND completed_at < ?)
  OR (updated_at IS NOT NULL AND updated_at >= ? AND updated_at < ? AND status IN ('running','blocked','review','triage'))
  OR (created_at >= ? AND created_at < ? AND status IN ('running','blocked','review','triage'))
ORDER BY COALESCE(completed_at, updated_at, created_at) DESC
''', (start, end, start, end, start, end))]
conn.close()

if not rows:
    raise SystemExit(0)

groups = {
    'Completed yesterday': [r for r in rows if r['status'] == 'done' and r.get('completed_at')],
    'Still running': [r for r in rows if r['status'] == 'running'],
    'Blocked / needs call': [r for r in rows if r['status'] in ('blocked','review','triage')],
}
needs = groups['Blocked / needs call']
emoji = '⚠️' if needs else '✅'
signal = f'{len(needs)} need action' if needs else 'no blockers surfaced'
lines = [
    f"{emoji} Kanban digest · {now.strftime('%d/%m/%Y %H:%M:%S')}",
    f"checked · {len(rows)} tasks · {signal}",
    '',
]
for heading, items in groups.items():
    if not items:
        continue
    lines.append(heading)
    for r in items[:3]:
        reason = short(r.get('status_reason') or r.get('last_failure_error') or '', 60)
        suffix = f' — {reason}' if heading.startswith('Blocked') and reason else ''
        lines.append(f"• `{r['id']}` — {short(r['title'], 72)}{suffix}")
    lines.append('')

cards = []
for heading, items in groups.items():
    cards.append(f"<section><h2>{html.escape(heading)} <span>{len(items)}</span></h2>")
    if not items:
        cards.append("<p class='muted'>None.</p>")
    else:
        cards.append('<table><thead><tr><th>ID</th><th>Title</th><th>Status</th><th>Owner</th><th>Updated</th><th>Signal</th></tr></thead><tbody>')
        for r in items:
            signal_txt = r.get('status_reason') or r.get('last_failure_error') or r.get('result') or ''
            when = r.get('completed_at') or r.get('updated_at') or r.get('created_at')
            cards.append('<tr>'
                f"<td><code>{html.escape(r['id'])}</code></td>"
                f"<td>{html.escape(short(r['title'], 160))}</td>"
                f"<td>{html.escape(r['status'])}</td>"
                f"<td>{html.escape(r.get('assignee') or '')}</td>"
                f"<td>{html.escape(fmt_ts(when))}</td>"
                f"<td>{html.escape(short(signal_txt, 220))}</td>"
                '</tr>')
        cards.append('</tbody></table>')
    cards.append('</section>')

html_doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kanban digest · {yesterday.strftime('%d/%m/%Y')}</title>
<style>
:root {{ color-scheme: dark; --bg:#11100f; --card:#1c1917; --line:#34302c; --text:#f5f5f4; --muted:#a8a29e; --accent:#fbbf24; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif; }}
main {{ width:min(1180px, calc(100% - 32px)); margin:0 auto; padding:28px 0 48px; }}
h1 {{ margin:0 0 4px; font-size:28px; }} .muted {{ color:var(--muted); }}
.summary {{ display:flex; gap:12px; flex-wrap:wrap; margin:18px 0; }}
.pill {{ background:var(--card); border:1px solid var(--line); border-radius:999px; padding:8px 12px; }}
section {{ background:var(--card); border:1px solid var(--line); border-radius:14px; margin:18px 0; overflow:hidden; }}
h2 {{ margin:0; padding:14px 16px; border-bottom:1px solid var(--line); color:var(--accent); }} h2 span {{ color:var(--muted); font-size:14px; }}
table {{ width:100%; border-collapse:collapse; }} th,td {{ padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; text-align:left; }} th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
code {{ color:#fde68a; }}
</style></head><body><main>
<h1>Kanban digest · {yesterday.strftime('%d/%m/%Y')}</h1>
<p class="muted">Generated {now.strftime('%d/%m/%Y %H:%M:%S')} · {len(rows)} relevant task updates</p>
<div class="summary">
<div class="pill">Completed: {len(groups['Completed yesterday'])}</div>
<div class="pill">Running: {len(groups['Still running'])}</div>
<div class="pill">Blocked / needs call: {len(groups['Blocked / needs call'])}</div>
</div>
{''.join(cards)}
</main></body></html>"""
html_path.write_text(html_doc)
if not html_path.exists():
    raise SystemExit('HTML attachment was not written')

lines.append(f"MEDIA:{html_path}")
print('\n'.join(lines).strip())
