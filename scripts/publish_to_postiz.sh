#!/usr/bin/env bash
# Publish approved personal drafts to Postiz for scheduling and posting.
# Runs as no_agent cron. Silent when nothing to publish.
#
# Env overrides (P13 isolation / local disposable runs):
#   POSTIZ_DRY_RUN=1 — print the would-publish line, do not invoke the
#                     Python publisher
set -euo pipefail

if [[ "${POSTIZ_DRY_RUN:-0}" == "1" ]]; then
    echo "dry-run: would publish to Postiz"
    exit 0
fi

RUNTIME_ROOT="${HERMES_AGENT_ROOT:-$PWD}"
CE="$RUNTIME_ROOT/content_engine"
[[ -d "$CE" ]] || { echo "ERROR: content engine not found under runtime root: $RUNTIME_ROOT" >&2; exit 1; }
cd "$CE"

# Source env for DB credentials
set -a
source /home/kensei/.hermes/.env 2>/dev/null || true
set +a

export PYTHONPATH="${CE}:${PYTHONPATH:-}"

# Use the venv python (has psycopg2-binary installed)
timeout 60 "$RUNTIME_ROOT/.venv/bin/python" publish_to_postiz.py
