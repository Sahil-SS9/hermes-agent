#!/bin/bash
# Daily token health check wrapper — formats token_health.py output for human delivery
# Route: Topic 20 (System Health + Alerts)

cd /home/kensei

output=$(/home/kensei/.hermes/hermes-agent/venv/bin/python3 /home/kensei/.hermes/scripts/token_health.py)
exit_code=$?

if [ $exit_code -eq 0 ]; then
    parsed=$(TOKEN_HEALTH_JSON="$output" /home/kensei/.hermes/hermes-agent/venv/bin/python3 - <<'PY'
import json
import os

d = json.loads(os.environ["TOKEN_HEALTH_JSON"])
print(d["overall"])
print(f"expired={d['expired_count']} warnings={d['warnings_count']}")
PY
)
    overall=$(printf '%s\n' "$parsed" | sed -n '1p')
    count=$(printf '%s\n' "$parsed" | sed -n '2p')
    if [ "$overall" = "healthy" ]; then
        echo "✅ <b>Token health</b> · all OK ($count)"
        echo ""
        echo "All tokens valid. No re-auth needed."
    else
        echo "⚠️ <b>Token health</b> · $overall ($count)"
        echo ""
        echo "<b>Findings</b>"
        TOKEN_HEALTH_JSON="$output" /home/kensei/.hermes/hermes-agent/venv/bin/python3 - <<'PY'
import json
import os

d = json.loads(os.environ["TOKEN_HEALTH_JSON"])
for account in d["accounts"]:
    if account.get("status") in ("expired", "warning"):
        provider = account["provider"]
        email = account["email"]
        detail = account.get("detail", account["status"])
        print(f"• <code>{provider}</code> {email} — {detail}")
PY
        echo ""
        echo "Re-auth needed for flagged accounts. See memory for the rotation pattern."
    fi
else
    echo "❌ <b>Token health</b> · check failed"
    echo ""
    echo "<b>Error</b>"
    printf '%s\n' "$output" | sed -n '1,5p'
fi

exit 0
