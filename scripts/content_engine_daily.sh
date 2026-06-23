#!/usr/bin/env bash
# KENSEI Content Engine v4 - Daily Digest Runner
# Runs AFTER generation crons (08:50 personal, 09:00 app) to deliver
# the morning approval packet to Discord #content.
#
# Expects: content_engine.db has fresh draft rows from last 75 min.
# Outputs: short Discord summary + MEDIA tag for HTML digest file.

set -euo pipefail

cd /home/kensei/repos/KenseiAgent/content_engine

# Run digest (generates HTML + sends Telegram internally)
python3 content_engine.py digest --since-minutes 75 > /dev/null 2>&1 || true

# Find the latest HTML digest file
HTML_DIR="/home/kensei/.hermes/runbooks/content-digest"
LATEST_HTML=$(ls -t "$HTML_DIR"/*.html 2>/dev/null | head -1)

# Build brand counts from recent drafts
BRAND_COUNTS=$(python3 - <<'PY'
import sqlite3, json
conn = sqlite3.connect('db/content_engine.db')
rows = conn.execute("""
    SELECT brand, COUNT(*) FROM drafts
    WHERE status='draft'
      AND created_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-75 minutes')
    GROUP BY brand ORDER BY brand
""").fetchall()
conn.close()
print(json.dumps({b:c for b,c in rows}))
PY
)

TOTAL=$(echo "$BRAND_COUNTS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(sum(d.values()))")
BRANDS=$(echo "$BRAND_COUNTS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(', '.join(f'{b}:{c}' for b,c in d.items()))")

FINISHED_AT="$(TZ=Europe/London date '+%d/%m/%y %H:%M:%S')"

# Discord-safe summary
echo "📝 Content drafts · ${FINISHED_AT}"
echo "${TOTAL} drafts · ${BRANDS}"
echo ""
if [ -n "$LATEST_HTML" ]; then
    echo "MEDIA:${LATEST_HTML}"
else
    echo "HTML digest not found - check content_engine.py digest output."
fi
