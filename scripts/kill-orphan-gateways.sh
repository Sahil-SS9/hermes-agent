#!/usr/bin/env bash
# kill-orphan-gateways.sh — Kill orphaned `gateway run --replace` processes
#
# Gateway crash/restart loops can spawn `gateway run --replace` processes
# that don't properly die — they get reparented to PID 1 (init) and accumulate
# as orphans, wasting ~30MB each.
#
# This script targets specifically: python -m hermes_cli.main gateway run --replace
# processes whose parent is PID 1, keeping the longest-running one as the
# "real" gateway.
#
# Usage:
#   ./kill-orphan-gateways.sh          # dry-run (print what would be killed)
#   ./kill-orphan-gateways.sh --apply  # actually kill

set -euo pipefail

DRY_RUN=true
if [[ "${1:-}" == "--apply" ]]; then
    DRY_RUN=false
elif [[ ! -t 1 ]]; then
    # Non-interactive (cron etc.) — default to apply
    DRY_RUN=false
fi

# Find all gateway --replace processes ordered by PID (oldest first)
# We keep the oldest one as the primary, kill the rest if they're PPID=1
mapfile -t GATEWAY_PIDS < <(ps -eo pid,ppid,lstart,args --no-headers \
    | grep -E 'python.*hermes_cli\.main gateway run --replace' \
    | grep -v grep \
    | sort -k3 \
    | awk '{print $1}')

if [[ ${#GATEWAY_PIDS[@]} -eq 0 ]]; then
    echo "[SILENT] No gateway processes found."
    exit 0
fi

# The first PID (oldest) is the primary — keep it
PRIMARY="${GATEWAY_PIDS[0]}"
PRIMARY_PPID=$(ps -o ppid= -p "$PRIMARY" 2>/dev/null | tr -d ' ' || echo "?")

echo "=== Gateway Orphan Killer ==="
echo "Primary: PID $PRIMARY (PPID=$PRIMARY_PPID)"
echo "Total gateway processes: ${#GATEWAY_PIDS[@]}"
echo ""

KILLED=0
KEPT=1  # the primary

for pid in "${GATEWAY_PIDS[@]:1}"; do
    ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ' || echo "?")
    comm=$(ps -o comm= -p "$pid" 2>/dev/null || echo "<gone>")
    elapsed=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ' || echo "?")
    args=$(ps -o args= -p "$pid" 2>/dev/null | head -c 80 || echo "<gone>")

    if [[ "$ppid" == "1" ]]; then
        if $DRY_RUN; then
            echo "ORPHAN  PID $pid (PPID=$ppid, age=$elapsed) — would kill"
        else
            # Kill the process and any children
            subtree=$(ps --ppid "$pid" -o pid= 2>/dev/null || true)
            for child in $subtree; do kill -TERM "$child" 2>/dev/null || true; done
            kill -TERM "$pid" 2>/dev/null && \
                echo "KILLED  PID $pid (PPID=$ppid, age=$elapsed)" || \
                echo "GONE    PID $pid (already dead)"
            KILLED=$((KILLED + 1))
        fi
    else
        echo "KEEP    PID $pid (PPID=$ppid, age=$elapsed) — parented by system process"
        KEPT=$((KEPT + 1))
    fi
done

echo ""
echo "=== Summary ==="
echo "Primary gateway: PID $PRIMARY"
echo "Kept (incl primary): $KEPT"
if $DRY_RUN; then
    echo "Would kill: $KILLED orphans"
    echo "DRY RUN — run with --apply to kill."
else
    echo "Killed: $KILLED orphans"
    if [[ $KILLED -gt 0 ]]; then
        reclaimed=$((KILLED * 30))
        echo "~${reclaimed}MB RAM reclaimed (est. 30MB each)"
    fi
fi
