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

# Find all gateway --replace processes. We prefer the live systemd MainPID as the
# primary, because an older orphan can outlive the real gateway. If systemd is not
# available, fall back to the newest PID seen in ps output.
mapfile -t GATEWAY_PIDS < <(ps -eo pid,ppid,lstart,args --no-headers \
    | grep -E 'python.*hermes_cli\.main gateway run --replace' \
    | grep -v grep \
    | awk '{print $1}')

if [[ ${#GATEWAY_PIDS[@]} -eq 0 ]]; then
    exit 0
fi

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

if [[ -z "$PRIMARY" ]]; then
    PRIMARY=$(printf '%s\n' "${GATEWAY_PIDS[@]}" | sort -n | tail -1)
fi

PRIMARY_PPID=$(ps -o ppid= -p "$PRIMARY" 2>/dev/null | tr -d ' ' || echo "?")

# Stay silent when healthy: 0 or 1 gateway process means nothing to do.
if [[ ${#GATEWAY_PIDS[@]} -le 1 ]]; then
    exit 0
fi

echo "=== Gateway Orphan Killer ==="
echo "Primary: PID $PRIMARY (PPID=$PRIMARY_PPID)"
echo "Total gateway processes: ${#GATEWAY_PIDS[@]}"
echo ""

KILLED=0
KEPT=1  # the primary

for pid in "${GATEWAY_PIDS[@]}"; do
    if [[ "$pid" == "$PRIMARY" ]]; then
        continue
    fi
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
