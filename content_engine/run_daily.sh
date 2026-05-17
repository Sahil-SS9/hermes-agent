#!/usr/bin/env bash
# KENSEI Content Engine v2 — Daily Pipeline Runner
# Stage 1: LLM text drafts (free) → Telegram cards for approval
# Stage 2: AI images + videos for approved drafts only (costs money)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load env vars from Hermes. Use shell-native sourcing; do not pipe env files
# through xargs because secrets can contain shell metacharacters.
if [ -f /home/kensei/.hermes/.env ]; then
    set -a
    # shellcheck disable=SC1091
    source /home/kensei/.hermes/.env
    set +a
fi

export TELEGRAM_CONTENT_CHAT_ID=${TELEGRAM_CONTENT_CHAT_ID:-"-1003922682700"}
export TELEGRAM_CONTENT_TOPIC_ID=${TELEGRAM_CONTENT_TOPIC_ID:-"22"}
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

echo "$(date -Iseconds) — Content Engine v2: generating LLM drafts..."
python3 content_engine.py stage1 --brand matchdaymaestro plenishd sahil_twitter sahil_linkedin coachos --max-per-brand 2

echo "$(date -Iseconds) — Done. Check Telegram Topic 22 for approval digest."
