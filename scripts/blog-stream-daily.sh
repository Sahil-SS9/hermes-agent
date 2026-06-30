#!/bin/bash
# blog-stream-daily.sh — fire-and-forget daily SahilBlog stream generation.
# Hermes no-agent crons have a 300s timeout; this script detaches the slow
# LLM + Codex image pipeline and exits immediately.
set -euo pipefail

ROOT=/home/kensei/repos/KenseiAgent/content_engine
LOG_DIR="$ROOT/output/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/blog-stream-daily-$(date +%Y%m%d-%H%M%S).log"

if [[ "${BLOG_DAILY_NOOP:-}" == "1" ]]; then
  echo "noop: would launch blog stream pipeline detached -> $LOG"
  exit 0
fi

(
  cd "$ROOT"
  set -a
  . ~/.hermes/.env 2>/dev/null || true
  set +a
  echo "[$(date -Is)] starting blog stream daily"
  PYTHONPATH=. ../.venv/bin/python -m blog.blog_pipeline --stream all
  rc=$?
  echo "[$(date -Is)] finished blog stream daily rc=$rc"
  exit "$rc"
) >>"$LOG" 2>&1 < /dev/null &

pid=$!
echo "blog-stream-daily detached pid=$pid log=$LOG"
exit 0
