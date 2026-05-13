#!/bin/bash
# Daily token health check wrapper — formats token_health.py output for human delivery
# Route: Topic 20 (System Health + Alerts)

cd /home/kensei

output=$(/home/kensei/.hermes/hermes-agent/venv/bin/python3 /home/kensei/.hermes/scripts/token_health.py)
exit_code=$?

if [ $exit_code -eq 0 ]; then
    overall=$(echo "$output" | python3 -c "import sys, json; print(json.load(sys.stdin)['overall'])")
    count=$(echo "$output" | python3 -c "import sys, json; d=json.load(sys.stdin); print(f\"expired={d['expired_count']} warnings={d['warnings_count']}\")" 2>/dev/null)
    if [ "$overall" = "healthy" ]; then
        echo "✅ <b>Token health</b> · all OK ($count)"
        echo ""
        echo "All tokens valid. No re-auth needed."
    else
        echo "⚠️ <b>Token health</b> · $overall ($count)"
        echo ""
        echo "<b>Findings</b>"
        echo "$output" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for a in d['accounts']:
    if a.get('status') in ('expired', 'warning'):
        print(f\"• <code>{a['provider']}</code> {a['email']} — {a.get('detail', a['status'])}\")
"
        echo ""
        echo "Re-auth needed for flagged accounts. See memory for the rotation pattern."
    fi
else
    echo "❌ <b>Token health</b> · check failed"
    echo ""
    echo "<b>Error</b>"
    echo "$output" | head -5
fi

exit 0
