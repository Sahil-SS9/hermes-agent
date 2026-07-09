#!/bin/bash
# blog-failed-retry.sh — holistic recovery for held (failed-image) blog posts.
# Retries EVERY post in failed_images.jsonl. Codex-cap-aware: if Codex reports
# its usage cap the whole run defers (no attempts burned, drafts preserved) and
# tries again next window.
#
# Writes a status JSON (blog-failed-retry-status.json) on completion so the
# pipeline-audit cron can report the outcome to #blog-management. Previously
# this cron ran silent — retries happened with zero visibility.
set -euo pipefail

ROOT=/home/kensei/repos/KenseiAgent/content_engine
LOG_DIR="$ROOT/output/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/blog-failed-retry-$(date +%Y%m%d-%H%M%S).log"
STATUS="$LOG_DIR/blog-failed-retry-status.json"

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
  OUT=$(PYTHONPATH=. ../.venv/bin/python -m blog.blog_pipeline --retry 2>&1)
  rc=$?
  echo "$OUT"
  echo "[$(date -Is)] finished blog failed-image retry rc=$rc"
  # Persist machine-readable status for the audit cron to surface.
  python3 - "$rc" <<'PY'
import sys, json, re, datetime
rc = sys.argv[1]
out = sys.stdin.read()
status = {"rc": int(rc), "finished_at": datetime.datetime.now().isoformat(timespec="seconds"), "raw": out[-2000:]}
m = re.search(r"retry_all_pending_images:\s*\{?(.*?)\}?", out, re.S)
if m:
    blob = m.group(1)
    for key in ("recovered", "still_failed", "no_draft", "deferred", "idle"):
        km = re.search(rf"'?{key}'?\s*:\s*(\[[^\]]*\]|\w+)", blob)
        if km:
            val = km.group(1)
            status[key] = json.loads(val) if val.startswith("[") else val
with open("$STATUS", "w") as f:
    json.dump(status, f, indent=2)
PY
  exit "$rc"
) >>"$LOG" 2>&1 < /dev/null &

pid=$!
# Detached process started — status written on completion for the audit cron.
exit 0
