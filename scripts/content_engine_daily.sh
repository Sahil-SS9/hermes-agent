#!/usr/bin/env bash
# KENSEI Content Engine v2 — Daily Pipeline Runner
# Stage 1: Draft generation with brand voice → Telegram summary + HTML
# Stage 2: AI images + videos for approved drafts only (costs money)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load Hermes env (proper way — no xargs)
if [ -f /home/kensei/.hermes/.env ]; then
    while IFS= read -r line; do
        line="$(printf '%s' "$line" | tr -d '\r')"
        case "$line" in
            '#'*|'') continue ;;
            *) export "$line" ;;
        esac
    done < /home/kensei/.hermes/.env
fi

export TELEGRAM_CONTENT_CHAT_ID=${TELEGRAM_CONTENT_CHAT_ID:-"-1003922682700"}
export TELEGRAM_CONTENT_TOPIC_ID=${TELEGRAM_CONTENT_TOPIC_ID:-"22"}
PYTHONPATH="${PYTHONPATH}:$SCRIPT_DIR"
cd /home/kensei/repos/KenseiAgent/content_engine

echo "$(date -Iseconds) — Content Engine v2: generating drafts..."
python3 content_engine.py generate
echo "$(date -Iseconds) — Done. Check Telegram Topic 22 for draft review."
