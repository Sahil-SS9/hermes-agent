#!/bin/bash
# Daily token health check wrapper — formats token_health.py output for human delivery
# Discord-safe output (no HTML tags)
# cron-output-contract: Output summary + MEDIA tag for full report
set -euo pipefail
trap 'echo "[SILENT]"; exit 1' ERR

cd /home/kensei

report_dir="$HOME/.hermes/runbooks/token-health/$(date +%Y-%m-%d)"
mkdir -p "$report_dir"
report_file="$report_dir/report.html"

output=$(/home/kensei/repos/KenseiAgent/.venv/bin/python /home/kensei/.hermes/scripts/token_health.py)
exit_code=$?

if [ $exit_code -eq 0 ]; then
    parsed=$(TOKEN_HEALTH_JSON="$output" /home/kensei/repos/KenseiAgent/.venv/bin/python - <<'PY'
import json, os
d = json.loads(os.environ["TOKEN_HEALTH_JSON"])
print(d["overall"])
print(f"expired={d['expired_count']} warnings={d['warnings_count']}")
PY
)
    overall=$(printf '%s\n' "$parsed" | sed -n '1p')
    count=$(printf '%s\n' "$parsed" | sed -n '2p')
    
    # Generate HTML report
    TOKEN_HEALTH_JSON="$output" /home/kensei/repos/KenseiAgent/.venv/bin/python - <<PY > "$report_file"
import json, os
d = json.loads(os.environ["TOKEN_HEALTH_JSON"])
html = '''<!DOCTYPE html>
<html lang="en" data-color-scheme="dark">
<head><meta charset="utf-8"><title>Token Health Report</title>
<style>
body { background: #11100f; color: #f5f5f4; font-family: system-ui; padding: 2rem; }
h1 { color: #fbbf24; }
.healthy { color: #4ade80; }
.warning { color: #fbbf24; }
.expired { color: #f87171; }
table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
th, td { padding: 0.5rem 1rem; text-align: left; border-bottom: 1px solid #2c2a28; }
th { background: #1c1a18; color: #a8a29e; font-size: 0.8rem; text-transform: uppercase; }
.card { background: #1c1a18; border: 1px solid #34302c; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
.summary { display: flex; gap: 1rem; }
.stat { flex: 1; text-align: center; padding: 1rem; background: #2c2a28; border-radius: 6px; }
.stat-value { font-size: 2rem; font-weight: bold; }
.stat-label { color: #a8a29e; font-size: 0.8rem; }
</style></head>
<body>
<h1>Token Health Report</h1>
<div class="card">
  <div class="summary">
    <div class="stat"><div class="stat-value">''' + str(d['expired_count']) + '''</div><div class="stat-label">Expired</div></div>
    <div class="stat"><div class="stat-value">''' + str(d['warnings_count']) + '''</div><div class="stat-label">Warnings</div></div>
    <div class="stat"><div class="stat-value ''' + d['overall'] + '''">''' + d['overall'] + '''</div><div class="stat-label">Overall Status</div></div>
  </div>
</div>
<h2>Accounts</h2>
<table><tr><th>Provider</th><th>Email</th><th>Status</th><th>Detail</th></tr>
'''
for acc in d['accounts']:
    status_class = acc['status'] if acc['status'] in ('healthy', 'warning', 'expired') else ''
    html += f"<tr><td>{acc['provider']}</td><td>{acc['email']}</td><td class='{status_class}'>{acc['status']}</td><td>{acc.get('detail', '')}</td></tr>"
html += '''</table>
</body></html>'''
print(html)
PY
    
    if [ "$overall" = "healthy" ]; then
        echo "✅ Token health · all OK ($count)"
        echo "MEDIA:$report_file"
    else
        echo "⚠️ Token health · $overall ($count)"
        echo "MEDIA:$report_file"
    fi
else
    echo "❌ Token health · check failed"
    echo "MEDIA:$report_file"
fi

exit 0