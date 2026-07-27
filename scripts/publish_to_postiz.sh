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

CE="/home/kensei/repos/KenseiAgent/content_engine"
cd "$CE"

# Source env for DB credentials
set -a
source /home/kensei/.hermes/.env 2>/dev/null || true
set +a

export PYTHONPATH="${CE}:${PYTHONPATH:-}"

# Use the venv python (has psycopg2-binary installed)
timeout 60 /home/kensei/repos/KenseiAgent/.venv/bin/python publish_to_postiz.py
