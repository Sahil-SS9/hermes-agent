#!/usr/bin/env python3
"""Discord Bot Health Monitor — checks all 9 gateway bots for Discord connectivity.

Silent when healthy (exit 0, empty stdout).
Outputs alert text when a bot is down or unreachable.
"""
import subprocess
import sys
import json
from pathlib import Path

HERMES = Path("/home/kensei/.hermes")

# All gateway services to check
SERVICES = [
    ("kensei", "hermes-gateway.service"),
    ("ceecee", "hermes-gateway-ceecee.service"),
    ("denji", "hermes-gateway-denji.service"),
    ("dezzy", "hermes-gateway-dezzy.service"),
    ("gojo", "hermes-gateway-gojo.service"),
    ("light", "hermes-gateway-light.service"),
    ("misa-misa", "hermes-gateway-misa-misa.service"),
    ("miyagi", "hermes-gateway-miyagi.service"),
    ("octacon", "hermes-gateway-octacon.service"),
    ("remii", "hermes-gateway-remii.service"),
    ("wesker", "hermes-gateway-wesker.service"),
]

def check_service(name, service):
    """Check if a systemd service is active."""
    result = subprocess.run(
        ["systemctl", "is-active", service],
        capture_output=True, text=True, timeout=10
    )
    return result.stdout.strip() == "active"

def check_pid(name, service):
    """Check if the service has a valid main PID."""
    result = subprocess.run(
        ["systemctl", "show", service, "-p", "MainPID", "--value"],
        capture_output=True, text=True, timeout=10
    )
    pid = result.stdout.strip()
    if not pid or pid == "0":
        return False, pid
    # Verify PID exists in /proc
    proc_path = Path(f"/proc/{pid}")
    return proc_path.exists(), pid

def check_gateway_log_errors(name):
    """Check the last 50 lines of gateway log for critical errors."""
    log_path = HERMES / "profiles" / name / "logs" / "gateway.log"
    if name == "kensei":
        log_path = HERMES / "logs" / "gateway.log"
    if not log_path.exists():
        return []
    
    try:
        result = subprocess.run(
            ["tail", "-50", str(log_path)],
            capture_output=True, text=True, timeout=10
        )
        errors = []
        for line in result.stdout.splitlines():
            lower = line.lower()
            if any(kw in lower for kw in ["critical", "fatal", "traceback", "unhandled exception"]):
                errors.append(line.strip()[:200])
        return errors[-3:]  # Last 3 errors max
    except Exception:
        return []

def main():
    alerts = []
    
    for name, service in SERVICES:
        is_active = check_service(name, service)
        if not is_active:
            alerts.append(f"**{name}** — service NOT active ({service})")
            continue
        
        has_pid, pid = check_pid(name, service)
        if not has_pid:
            alerts.append(f"**{name}** — service active but PID {pid} not found in /proc")
            continue
        
        # Check for recent critical errors in logs
        errors = check_gateway_log_errors(name)
        if errors:
            error_summary = "; ".join(errors[:2])
            alerts.append(f"**{name}** — recent errors: {error_summary}")
    
    if not alerts:
        sys.exit(0)  # Silent when healthy
    
    # Output alert
    print("**🔴 Discord Bot Health Alert — DD/MM/YY HH:MM**\n")
    for alert in alerts:
        print(f"• {alert}")
    print(f"\n**Action:** Check `systemctl status <service>` for affected bots.")
    sys.exit(0)  # Still exit 0 — we delivered the alert via stdout

if __name__ == "__main__":
    main()
