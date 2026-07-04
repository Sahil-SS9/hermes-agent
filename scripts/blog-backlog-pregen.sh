#!/bin/bash
# blog-backlog-pregen.sh — fire-and-forget backlog pre-generation.
# Generates ONE ready-to-approve post per run (rotating ai/pm/builder), pulling
# from the backlog queues. Detaches so the slow LLM + Codex image work never
# trips the 300s no-agent cron timeout. One post = ~3 Codex images, well under
# the usage cap. Posts accrue as approved:false drafts + approval cards.
set -euo pipefail

ROOT=/home/kensei/repos/KenseiAgent/content_engine
LOG_DIR="$ROOT/output/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/blog-backlog-pregen-$(date +%Y%m%d-%H%M%S).log"

if [[ "${BLOG_DAILY_NOOP:-}" == "1" ]]; then
  echo "noop: would launch backlog pregen detached -> $LOG"
  exit 0
fi

(
  cd "$ROOT"
  set -a
  . ~/.hermes/.env 2>/dev/null || true
  set +a
  echo "[$(date -Is)] starting backlog pregen"
  PYTHONPATH=. ../.venv/bin/python -m blog.backlog_pregen
  rc=$?
  echo "[$(date -Is)] finished backlog pregen rc=$rc"
  exit "$rc"
) >>"$LOG" 2>&1 < /dev/null &

pid=$!
# Detached process started — silent on success (no Discord delivery)
exit 0
