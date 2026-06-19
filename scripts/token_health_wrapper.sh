#!/bin/bash
set -euo pipefail

HOME_DIR="${HOME:-/home/kensei}"
cd "$HOME_DIR"

mkdir -p "$HOME/.hermes/runbooks/token-health/$(date +%Y-%m-%d)"
report_file="$HOME/.hermes/runbooks/token-health/$(date +%Y-%m-%d)/report.html"

output_file=$(mktemp)
/home/kensei/repos/KenseiAgent/.venv/bin/python /home/kensei/.hermes/scripts/token_health.py > "$output_file"
rc=$?
if [ "$rc" -ne 0 ]; then
    echo "❌ Token health · check failed"
    echo "MEDIA:$report_file"
    rm -f "$output_file"
    exit 0
fi

export TOKEN_HEALTH_JSON="$(cat "$output_file")"
/home/kensei/repos/KenseiAgent/.venv/bin/python /home/kensei/repos/KenseiAgent/scripts/token_health_render.py "$report_file"

# Extract overall status from JSON
overall_status=$(echo "$TOKEN_HEALTH_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['overall'])")

if [ "$overall_status" = "healthy" ]; then
    echo "✅ Token health · all OK"
else
    echo "⚠️ Token health · check output"
fi
echo "MEDIA:$report_file"
rm -f "$output_file"
exit 0