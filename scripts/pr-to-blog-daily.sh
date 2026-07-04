#!/bin/bash
# pr-to-blog-daily.sh — fire-and-forget PR-to-blog generation.
# Hermes no-agent crons have a 300s timeout; this script detaches the slow
# generation + image path and exits immediately.
set -euo pipefail

ROOT=/home/kensei/repos/KenseiAgent/content_engine
LOG_DIR="$ROOT/output/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/pr-to-blog-daily-$(date +%Y%m%d-%H%M%S).log"

if [[ "${BLOG_DAILY_NOOP:-}" == "1" ]]; then
  echo "noop: would launch PR-to-blog pipeline detached -> $LOG"
  exit 0
fi

(
  cd "$ROOT"
  set -a
  . ~/.hermes/.env 2>/dev/null || true
  set +a
  echo "[$(date -Is)] starting PR-to-blog daily"
  PYTHONPATH=. ../.venv/bin/python -m blog.pr_to_blog
  rc=$?
  echo "[$(date -Is)] finished PR-to-blog daily rc=$rc"
  exit "$rc"
) >>"$LOG" 2>&1 < /dev/null &

pid=$!
# Detached process started — silent on success (no Discord delivery)
exit 0
