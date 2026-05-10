#!/bin/bash
# KENSEI Content Engine — Daily Pipeline Runner
# Stage 1: text drafts + static visuals (free) → Telegram digest for approval
# Stage 2: AI images + videos for approved drafts (costs money) → runs after approval

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load env vars from Hermes
if [ -f /home/kensei/.hermes/.env ]; then
    export TELEGRAM_BOT_TOKEN=$(grep "^TELEGRAM_BOT_TOKEN=" /home/kensei/.hermes/.env | cut -d'=' -f2 | xargs)
    export FAL_KEY=$(grep "^FAL_KEY=" /home/kensei/.hermes/.env | cut -d'=' -f2 | xargs)
fi

# HyperFrames CPU-only mode (VPS has no GPU)
export PRODUCER_FORCE_SCREENSHOT="true"
export ORT_ALLOW_CPU_FALLBACK="1"
export ORT_USE_CUDA="0"

export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

echo "$(date -Iseconds) — Stage 1: generating text drafts + static visuals..."
python3 content_engine.py stage1 --brand matchdaymaestro plenishd sahil_twitter

echo "$(date -Iseconds) — Done. Check Telegram Topic 22 for approval digest."
