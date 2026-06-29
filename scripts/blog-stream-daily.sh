#!/bin/bash
# blog-stream-daily.sh — Daily blog stream generation for AI Decoding, PM Insights, Builder's Log.
# Runs blog_pipeline.run_all() through the CLI. Sources Hermes .env for API credentials.
# Designed for Hermes cron (no-agent script mode).
set -euo pipefail

cd /home/kensei/repos/KenseiAgent/content_engine
set -a
. ~/.hermes/.env 2>/dev/null || true
set +a

PYTHONPATH=. ../.venv/bin/python -m blog.blog_pipeline --stream all 2>&1
echo "Exit code: $?"
