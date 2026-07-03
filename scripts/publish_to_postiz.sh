#!/usr/bin/env bash
# Publish approved personal drafts to Postiz for scheduling and posting.
# Runs as no_agent cron. Silent when nothing to publish.
set -euo pipefail

CE="/home/kensei/repos/KenseiAgent/content_engine"
cd "$CE"

# Source env for DB credentials
set -a
source /home/kensei/.hermes/.env 2>/dev/null || true
set +a

export PYTHONPATH="${CE}:${PYTHONPATH:-}"

# Use the venv python (has psycopg2-binary installed)
timeout 60 /home/kensei/repos/KenseiAgent/.venv/bin/python publish_to_postiz.py
