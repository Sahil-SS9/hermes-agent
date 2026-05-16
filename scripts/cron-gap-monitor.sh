#!/bin/bash
# cron-gap-monitor.sh — watchdog for cron scheduler gap regression
# Part of Phase 1 fix monitoring. Reports pass/fail with clear recommendations.
# Called by kensei-cron-gap-monitor cron job (every 4 hours)

set -euo pipefail

REPORT=""

# 1. Check heartbeat audit last 6 runs
HB_OUTPUT_DIR=$(ls -td /home/kensei/.hermes/cron/output/*/ 2>/dev/null | head -5 | while read dir; do
  if [ -f "$dir/output.txt" ]; then
    jq -r '.model // empty' "$dir/job.json" 2>/dev/null && echo "$dir"
  fi
done 2>/dev/null)

# Check recent heartbeat audit output files
HB_DIR=$(ls -td /home/kensei/.hermes/cron/output/*/ 2>/dev/null | while read d; do
  if grep -q "kensei-heartbeat-audit" "$d/job.json" 2>/dev/null; then
    echo "$d"
  fi
done | head -6)

HB_CLEAN=0
HB_FAIL=0
if [ -n "$HB_DIR" ]; then
  while IFS= read -r dir; do
    STATUS=$(jq -r '.last_status // "unknown"' "$dir/job.json" 2>/dev/null || echo "unknown")
    if [ "$STATUS" = "ok" ]; then
      HB_CLEAN=$((HB_CLEAN + 1))
    elif [ "$STATUS" = "timeout" ] || [ "$STATUS" = "error" ]; then
      HB_FAIL=$((HB_FAIL + 1))
    fi
  done <<< "$HB_DIR"
fi

# 2. Check cron.db or jobs.json for gap evidence
GAP_COUNT=0
GAP_DETAILS=""
# Check the memory watchdog output for gaps
WATCHDOG_DIR=$(ls -td /home/kensei/.hermes/cron/output/*/ 2>/dev/null | while read d; do
  if grep -q "Memory Watchdog" "$d/job.json" 2>/dev/null; then
    echo "$d"
  fi
done | head -10)

RECENT_GAPS=0
if [ -n "$WATCHDOG_DIR" ]; then
  PREV_TS=""
  while IFS= read -r dir; do
    TS=$(jq -r '.last_run_at // empty' "$dir/job.json" 2>/dev/null || echo "")
    if [ -n "$TS" ] && [ -n "$PREV_TS" ]; then
      PREV_EPOCH=$(date -d "$PREV_TS" +%s 2>/dev/null || echo 0)
      CURR_EPOCH=$(date -d "$TS" +%s 2>/dev/null || echo 0)
      if [ "$PREV_EPOCH" -gt 0 ] && [ "$CURR_EPOCH" -gt 0 ]; then
        GAP=$((CURR_EPOCH - PREV_EPOCH))
        if [ "$GAP" -gt 1800 ]; then  # >30m
          RECENT_GAPS=$((RECENT_GAPS + 1))
          GAP_DETAILS="${GAP_DETAILS}Gap ${GAP}s at ${TS}\n"
        fi
      fi
    fi
    PREV_TS="$TS"
  done <<< "$WATCHDOG_DIR"
fi

# 3. Determine status
if [ "$RECENT_GAPS" -gt 0 ]; then
  echo "🔴 GAPS DETECTED - Phase 1 fix may not be sufficient"
  echo ""
  echo "Found $RECENT_GAPS gap(s) >30m in recent watchdog runs."
  [ -n "$GAP_DETAILS" ] && echo -e "$GAP_DETAILS"
  echo ""
  echo "--- RECOMMENDED ACTIONS ---"
  echo "1. Check which cron job is causing the delay:"
  echo "   Look at cron scheduler lock holder during gap window"
  echo "2. If a specific job is slow:"
  echo "   Move it off ollama-cloud (same fix as heartbeat audit)"
  echo "3. If multiple jobs cause intermittent gaps:"
  echo "   Implement Phase 2 fixes in the gateway tick lock:"
  echo "   a) Tick-level timeout so lock doesn't deadlock"
  echo "   b) Per-job timeout enforced outside the lock"
  echo "4. File a kanban task for Phase 2 if needed"
elif [ "$HB_FAIL" -gt 0 ] && [ "$HB_CLEAN" -eq 0 ]; then
  echo "🟡 HEARTBEAT AUDIT FAILING - Provider switch may need attention"
  echo ""
  echo "Last $((HB_CLEAN + HB_FAIL)) heartbeat runs: $HB_FAIL failed, 0 clean"
  echo ""
  echo "--- RECOMMENDED ACTIONS ---"
  echo "1. Check the nous provider is accessible:"
  echo "   hermes chat -m deepseek/deepseek-v4-flash --provider nous 'test'"
  echo "2. If nous is down, try openrouter as alternative:"
  echo "   Update cron job provider to 'auto' and let fallback chain handle it"
  echo "3. If all providers fail, file a kanban ops task for infrastructure investigation"
else
  echo "✅ PHASE 1 FIX WORKING - No gaps detected, heartbeat running cleanly"
  echo ""
  echo "Last $((HB_CLEAN + HB_FAIL)) heartbeat runs: $HB_CLEAN clean, $HB_FAIL failed"
  echo ""
  echo "--- STATUS ---"
  echo "The model swap from ollama-cloud to nous is effective."
  echo "No >30m gaps detected in recent watchdog cycles."
  echo ""
  echo "No action needed. Phase 1 fix is sufficient."
  echo "Phase 2 (structural tick lock changes) is not required at this time."
fi
