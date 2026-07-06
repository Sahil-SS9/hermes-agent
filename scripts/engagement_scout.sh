#!/usr/bin/env bash
# Engagement Scout — batched X scanning (5 batches of 5 accounts)
# Each run processes one batch, rotating through all 5 batches across the day.
# Keeps each run under the 300s cron scheduler timeout.
set -euo pipefail

PROJECT_DIR="/home/kensei/repos/KenseiAgent"
ENGAGEMENT_PY="$PROJECT_DIR/content_engine/engagement_suggester.py"
CE_DIR="$PROJECT_DIR/content_engine"
STATE_FILE="/home/kensei/.hermes/data/engagement-scout-batch.txt"

# Source env for DISCORD_BOT_TOKEN + OLLAMA_API_KEY
set -a
source /home/kensei/.hermes/.env 2>/dev/null || true
set +a

export PYTHONPATH="${CE_DIR}:${PYTHONPATH:-}"

# Define 5 batches of accounts
BATCH_0="marc_louvion,levelsio,tahseen_rahman,shadcn,rauchg"
BATCH_1="theo,swyx,ryan_c_harris,kentcdodds,pk_hal"
BATCH_2="AnthropicAI,claude_code,alexalbert__,amasad,TheAthleticFC"
BATCH_3="utdreport,ManUtd,GaryLineker,naval,paulg"
BATCH_4="sweatystartup,NousResearch,teknium,hermesagent,Sahil_Saghir"

# Determine current batch (rotate 0→1→2→3→4→0...)
mkdir -p "$(dirname "$STATE_FILE")"
CURRENT=0
if [ -f "$STATE_FILE" ]; then
    CURRENT=$(cat "$STATE_FILE")
fi

# Select the batch
case "$CURRENT" in
    0) BATCH="$BATCH_0" ;;
    1) BATCH="$BATCH_1" ;;
    2) BATCH="$BATCH_2" ;;
    3) BATCH="$BATCH_3" ;;
    4) BATCH="$BATCH_4" ;;
    *) BATCH="$BATCH_0"; CURRENT=0 ;;
esac

# Advance for next run
NEXT=$(( (CURRENT + 1) % 5 ))
echo "$NEXT" > "$STATE_FILE"

export ENGAGEMENT_BATCH_ACCOUNTS="$BATCH"

cd "$CE_DIR"
echo "[engagement-scout] Batch $CURRENT — accounts: $BATCH"
exec /home/kensei/repos/KenseiAgent/.venv/bin/python "$ENGAGEMENT_PY" scan 2>&1
