#!/bin/bash
# Approve a content_engine draft and trigger Stage 2 (AI image/video generation).
# Usage:
#   approve_draft.sh <draft_id>
# Examples:
#   approve_draft.sh d_abc123
#   bash ~/.hermes/scripts/approve_draft.sh d_abc123
#
# Side effects:
#   1. Sets draft status='approved' + queues post in Postiz (via content_engine.py approve)
#   2. Triggers Stage 2 which generates FAL.ai images + FFMPEG/HyperFrames videos for
#      ALL currently-approved drafts (the function is idempotent - already-enriched
#      drafts won't double-spend)
#
# Note: this is the Phase 2 interim helper. The full automated bridge
# (Telegram A:<id>/R:<id> reply handling) is filed as a Kanban triage task.

set -euo pipefail

if [ -z "${1:-}" ]; then
    echo "Usage: approve_draft.sh <draft_id>" >&2
    echo "  Run 'cd /home/kensei/repos/KenseiAgent/content_engine && python3 content_engine.py list' to see pending drafts." >&2
    exit 2
fi

DRAFT_ID="$1"
REPO=/home/kensei/repos/KenseiAgent/content_engine
cd "$REPO"

# Load Hermes env (TELEGRAM_BOT_TOKEN, FAL_KEY etc) via shell-native sourcing.
# Was previously grep|cut|xargs which mangled values containing shell metacharacters (C3).
if [ -f /home/kensei/.hermes/.env ]; then
    set -a
    # shellcheck disable=SC1091
    source /home/kensei/.hermes/.env
    set +a
fi

# HyperFrames CPU-only mode (VPS has no GPU)
export PRODUCER_FORCE_SCREENSHOT="true"
export ORT_ALLOW_CPU_FALLBACK="1"
export ORT_USE_CUDA="0"

export PYTHONPATH="$REPO:${PYTHONPATH:-}"

# Use the repo venv: it has ARM-native numpy/Pillow that the image post-process
# (postprocess.py) needs. Bare python3 resolves to an x86 numpy build that fails
# to import on this aarch64 box.
VENV_PY=/home/kensei/repos/KenseiAgent/.venv/bin/python

echo "$(date -Iseconds) - Approving draft $DRAFT_ID..."
"$VENV_PY" content_engine.py approve "$DRAFT_ID"

echo "$(date -Iseconds) - Running Stage 2 (AI enrichment for all approved drafts)..."
"$VENV_PY" content_engine.py stage2

echo "$(date -Iseconds) - Done. Draft queued to Postiz (if integration is wired for brand/platform)."
