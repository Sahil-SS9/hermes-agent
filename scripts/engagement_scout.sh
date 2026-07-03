#!/usr/bin/env bash
# Engagement Scout — scans X for quote tweet / reply opportunities,
# generates brand-voice responses via LLM, delivers to Discord for approval.
set -euo pipefail

PROJECT_DIR="/home/kensei/repos/KenseiAgent"
ENGAGEMENT_PY="$PROJECT_DIR/content_engine/engagement_suggester.py"
CE_DIR="$PROJECT_DIR/content_engine"

# Source env for DISCORD_BOT_TOKEN + OLLAMA_API_KEY
set -a
source /home/kensei/.hermes/.env 2>/dev/null || true
set +a

export PYTHONPATH="${CE_DIR}:${PYTHONPATH:-}"

cd "$CE_DIR"
timeout 300 /home/kensei/repos/KenseiAgent/.venv/bin/python "$ENGAGEMENT_PY" scan 2>&1
