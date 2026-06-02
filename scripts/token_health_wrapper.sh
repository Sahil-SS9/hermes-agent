#!/bin/bash
# Daily token health check wrapper — formats token_health.py output for human delivery
# Discord-safe output (no HTML tags)

cd /home/kensei

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
    if [ "$overall" = "healthy" ]; then
        echo "✅ Token health · all OK ($count)"
        echo ""
        echo "All tokens valid. No re-auth needed."
    else
        echo "⚠️ Token health · $overall ($count)"
        echo ""
        echo "Findings"
        TOKEN_HEALTH_JSON="$output" /home/kensei/repos/KenseiAgent/.venv/bin/python - <<'PY'
import json, os
d = json.loads(os.environ["TOKEN_HEALTH_JSON"])
for account in d["accounts"]:
    if account.get("status") in ("expired", "warning"):
        provider = account["provider"]
        email = account["email"]
        detail = account.get("detail", account["status"])
        print(f"• `{provider}` {email} — {detail}")
PY
        echo ""
        echo "Re-auth needed for flagged accounts."
    fi
else
    echo "❌ Token health · check failed"
    echo ""
    echo "Error"
    printf '%s\n' "$output" | sed -n '1,5p'
fi

exit 0
