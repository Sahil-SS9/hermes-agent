#!/bin/bash
# Reject a content_engine draft. Marks status='rejected'. No Stage 2 trigger.
# Usage:
#   reject_draft.sh <draft_id>

set -euo pipefail

if [ -z "${1:-}" ]; then
    echo "Usage: reject_draft.sh <draft_id>" >&2
    exit 2
fi

DRAFT_ID="$1"
REPO=/home/kensei/repos/KenseiAgent/content_engine
cd "$REPO"

export PYTHONPATH="$REPO:${PYTHONPATH:-}"

echo "$(date -Iseconds) - Rejecting draft $DRAFT_ID..."
python3 content_engine.py reject "$DRAFT_ID"
echo "$(date -Iseconds) - Done."
