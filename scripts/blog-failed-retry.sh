#!/bin/bash
# blog-failed-retry.sh — holistic recovery for held (failed-image) blog posts.
# Retries EVERY post in failed_images.jsonl. Codex-cap-aware: if Codex reports
# its usage cap the whole run defers (no attempts burned, drafts preserved) and
# tries again next window. Detaches like the other blog crons (the 300s cron
# timeout can't hold a slow image pipeline).
set -euo pipefail

ROOT=/home/kensei/repos/KenseiAgent/content_engine
LOG_DIR="$ROOT/output/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/blog-failed-retry-$(date +%Y%m%d-%H%M%S).log"

if [[ "${BLOG_RETRY_NOOP:-}" == "1" ]]; then
  echo "noop: would launch blog failed-image retry detached -> $LOG"
  exit 0
fi

(
  cd "$ROOT"
  set -a
  . ~/.hermes/.env 2>/dev/null || true
  set +a
  echo "[$(date -Is)] starting blog failed-image retry"
  PYTHONPATH=. ../.venv/bin/python -m blog.blog_pipeline --retry
  rc=$?
  echo "[$(date -Is)] finished blog failed-image retry rc=$rc"
  exit "$rc"
) >>"$LOG" 2>&1 < /dev/null &

pid=$!
# Detached process started — silent on success (no Discord delivery)
exit 0
