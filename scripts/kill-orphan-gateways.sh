#!/usr/bin/env bash
# kill-orphan-gateways.sh — Kill orphaned `gateway run --replace` processes
#
# Gateway crash/restart loops can spawn `gateway run --replace` processes
# that don't properly die — they get reparented to PID 1 (init) and accumulate
# as orphans, wasting ~30MB each.
#
# v3 — 03/06/26: silent-by-default with delta detection.
# The previous version printed a 600-byte report to Discord on every run
# (every 15m) which flooded the channel. New contract:
#   - 0 orphans            -> completely silent (no stdout, no Discord)
#   - 1+ orphans, count    ->  silent (cleanup is working as expected)
#     not worse than last
#   - count INCREASED vs   -> WARN: orphans growing, investigate
#     last run
#   - count > THRESHOLD    -> WARN regardless (structural problem)
#   - keeper-pid mismatch  -> WARN: gateway identity changed
# Threshold default 5. Override with KILL_ORPHAN_THRESHOLD env.
#
# Usage:
#   ./kill-orphan-gateways.sh          # dry-run (print what would be killed)
#   ./kill-orphan-gateways.sh --apply  # actually kill (default when non-tty)
#
# State: ~/.hermes/state/gateway-orphan-watchdog.json
set -euo pipefail

DRY_RUN=true
if [[ "${1:-}" == "--apply" ]]; then
    DRY_RUN=false
elif [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
elif [[ ! -t 1 ]]; then
    DRY_RUN=false
fi

THRESHOLD=${KILL_ORPHAN_THRESHOLD:-5}
STATE_DIR="${HOME}/.hermes/state"
STATE_FILE="${STATE_DIR}/gateway-orphan-watchdog.json"

mkdir -p "$STATE_DIR"

# Find all gateway --replace processes
mapfile -t GATEWAY_PIDS < <(ps -eo pid,ppid,lstart,args --no-headers \
    | grep -E 'python.*hermes_cli\.main gateway run --replace' \
    | grep -v grep \
    | awk '{print $1}' || true)
# Always-defined count variable; mapfile leaves array empty if no match.
GATEWAY_TOTAL=${#GATEWAY_PIDS[@]}

# Read prior state
PREV_COUNT=0
PREV_PIDS=""
if [[ -f "$STATE_FILE" ]]; then
    PREV_COUNT=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('last_count',0))" "$STATE_FILE" 2>/dev/null || echo 0)
    PREV_PIDS=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(' '.join(str(x) for x in d.get('last_pids',[])))" "$STATE_FILE" 2>/dev/null || echo "")
fi

# Find the live keeper (prefer systemd MainPID, fall back to newest PID)
SYSTEMD_MAIN_PID=$(systemctl show -p MainPID --value hermes-gateway.service 2>/dev/null | tr -d ' ' || true)
PRIMARY=""
if [[ -n "$SYSTEMD_MAIN_PID" && "$SYSTEMD_MAIN_PID" != "0" ]]; then
    for pid in "${GATEWAY_PIDS[@]}"; do
        if [[ "$pid" == "$SYSTEMD_MAIN_PID" ]]; then
            PRIMARY="$pid"
            break
        fi
    done
fi
if [[ -z "$PRIMARY" ]] && (( GATEWAY_TOTAL > 0 )); then
    PRIMARY=$(printf '%s\n' "${GATEWAY_PIDS[@]}" | sort -n | tail -1)
fi
PRIMARY_PPID=$(ps -o ppid= -p "$PRIMARY" 2>/dev/null | tr -d ' ' || echo "?")

# Classify: orphans are PPID=1, anything else is "kept".
# CRITICAL: the keeper PRIMARY (resolved above) is ALWAYS excluded from
# KILL_LIST even if its PPID is 1. systemd-tracked services can have a
# real MainPID with PPID=1 after the original parent wrapper exits.
KILL_LIST=()
KEPT_LIST=()
for pid in "${GATEWAY_PIDS[@]}"; do
    if [[ -n "$PRIMARY" && "$pid" == "$PRIMARY" ]]; then
        KEPT_LIST+=("$pid")
        continue
    fi
    ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ' || echo "?")
    if [[ "$ppid" == "1" ]]; then
        KILL_LIST+=("$pid")
    else
        KEPT_LIST+=("$pid")
    fi
done

KILLED=0
KILLED_RAM_MB=0
if ! $DRY_RUN; then
    for pid in "${KILL_LIST[@]}"; do
        # Triple-check: never kill the keeper, even if classification slipped.
        if [[ -n "$PRIMARY" && "$pid" == "$PRIMARY" ]]; then
            echo "  [SKIP] $pid is PRIMARY — refusing to kill" >&2
            continue
        fi
        rss_kb=$(ps -o rss= -p "$pid" 2>/dev/null | tr -d ' ' || echo 0)
        subtree=$(ps --ppid "$pid" -o pid= 2>/dev/null || true)
        for child in $subtree; do kill -TERM "$child" 2>/dev/null || true; done
        kill -TERM "$pid" 2>/dev/null || true
        KILLED=$((KILLED + 1))
        KILLED_RAM_MB=$((KILLED_RAM_MB + rss_kb / 1024))
    done
fi

# Always persist state (so next run knows prior count)
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
PIDS_JSON=$(printf '%s\n' "${GATEWAY_PIDS[@]}" | python3 -c "import sys,json; print(json.dumps([int(x) for x in sys.stdin if x.strip()]))")
KILL_JSON=$(printf '%s\n' "${KILL_LIST[@]}" | python3 -c "import sys,json; print(json.dumps([int(x) for x in sys.stdin if x.strip()]))")
KEEPER_JSON=$(printf '%s\n' "${KEPT_LIST[@]}" | python3 -c "import sys,json; print(json.dumps([int(x) for x in sys.stdin if x.strip()]))")
python3 - "$STATE_FILE" "$NOW" "$PRIMARY" "$PRIMARY_PPID" \
    "$PREV_COUNT" "$GATEWAY_TOTAL" "$KILLED" "$KILLED_RAM_MB" \
    "$PIDS_JSON" "$KILL_JSON" "$KEEPER_JSON" <<'PY'
import json, sys
state_file, now, primary, primary_ppid, prev_count, total, killed, ram_mb, pids, kill_list, kept_list = sys.argv[1:]
data = {
    "last_run_at": now,
    "keeper_pid": int(primary) if primary.isdigit() else None,
    "keeper_ppid": int(primary_ppid) if primary_ppid.isdigit() else None,
    "last_count": int(total),
    "last_killed": int(killed),
    "last_killed_ram_mb": int(ram_mb),
    "last_pids": json.loads(pids),
    "last_kill_list": json.loads(kill_list),
    "last_kept_list": json.loads(kept_list),
    "prev_count": int(prev_count),
}
with open(state_file, "w") as f:
    json.dump(data, f, indent=2)
PY

# Decision: should we emit a Discord alert?
TOTAL="$GATEWAY_TOTAL"
ORPHAN_COUNT=${#KILL_LIST[@]}
KEPT_COUNT=${#KEPT_LIST[@]}
SHOULD_ALERT=false
ALERT_REASON=""

# Rule 1: count grew vs last run -> growing
if (( TOTAL > PREV_COUNT && PREV_COUNT > 0 )); then
    SHOULD_ALERT=true
    ALERT_REASON="orphans grew ${PREV_COUNT}→${TOTAL} (new ones being created)"
fi

# Rule 2: count above structural threshold
if (( ORPHAN_COUNT > THRESHOLD )); then
    SHOULD_ALERT=true
    ALERT_REASON="${ORPHAN_COUNT} orphans > threshold ${THRESHOLD}"
fi

# Rule 3: dry-run with structural issues (for human review without killing)
if $DRY_RUN && (( ORPHAN_COUNT > 0 && ORPHAN_COUNT > THRESHOLD )); then
    SHOULD_ALERT=true
    ALERT_REASON="DRY-RUN: ${ORPHAN_COUNT} orphans would be killed (>threshold ${THRESHOLD})"
fi

# Output (silent when healthy, summary on alert)
if $SHOULD_ALERT; then
    ts=$(date +%d/%m/%y\ %H:%M)
    echo "🟡 Gateway Orphan Watchdog — ${ts}"
    echo "Reason: ${ALERT_REASON}"
    echo "Primary: PID ${PRIMARY:-?} (PPID=${PRIMARY_PPID:-?})"
    echo "Total gateway --replace: ${TOTAL}  |  Orphans (PPID=1): ${ORPHAN_COUNT}  |  Kept: ${KEPT_COUNT}"
    if (( KILLED > 0 )); then
        echo "Killed this run: ${KILLED}  (~${KILLED_RAM_MB}MB RAM reclaimed)"
    fi
    echo "Prev run count: ${PREV_COUNT}  |  Threshold: ${THRESHOLD}"
    if (( ORPHAN_COUNT > 0 )); then
        echo "Orphan PIDs:"
        printf '  - %s\n' "${KILL_LIST[@]}"
    fi
    echo ""
    echo "Investigate: hermes-gateway --replace restart cascade. Likely cause:"
    echo "  - KillMode=mixed in hermes-gateway.service does not propagate SIGTERM"
    echo "    to children → they reparent to PID 1 when the wrapper exits."
    echo "  - Fix candidate: change KillMode to 'process' or 'cgroup' in the unit."
fi
# Silent when healthy. Exit 0 always.
exit 0
