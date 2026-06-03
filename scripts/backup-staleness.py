#!/usr/bin/env python3
"""Backup Staleness Monitor — alerts when backups are old, missing, or shrinking.

Silent when healthy (exit 0, empty stdout).
Outputs alert text when backup age > 48h, size shrinking, or no backups found.
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BACKUP_DIR = Path("/home/kensei/backups")
STATE_FILE = Path("/home/kensei/.hermes/scripts/.backup-staleness-state.json")
MAX_AGE_HOURS = 48
TZ = ZoneInfo("Europe/London")

def get_latest_backup():
    """Find the most recent file in the backup directory."""
    if not BACKUP_DIR.exists():
        return None, 0, []
    
    files = sorted(BACKUP_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return None, 0, []
    
    latest = files[0]
    age_hours = (datetime.now().timestamp() - latest.stat().st_mtime) / 3600
    total_size = sum(f.stat().st_size for f in files if f.is_file())
    
    return latest, age_hours, files

def load_state():
    """Load previous state for size comparison."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_size": 0, "last_check": None}

def save_state(state):
    """Save current state."""
    STATE_FILE.write_text(json.dumps(state))

def main():
    alerts = []
    latest, age_hours, files = get_latest_backup()
    state = load_state()
    
    now = datetime.now(TZ)
    
    if latest is None:
        alerts.append("**No backups found** in /home/kensei/backups/")
    else:
        # Check age
        if age_hours > MAX_AGE_HOURS:
            age_days = age_hours / 24
            alerts.append(f"**Latest backup is {age_days:.1f} days old** — {latest.name} (max: {MAX_AGE_HOURS/24:.0f} days)")
        
        # Check size trend (shrinking = possible corruption)
        current_size = sum(f.stat().st_size for f in files if f.is_file())
        if state["last_size"] > 0 and current_size > 0:
            if current_size < state["last_size"] * 0.5:  # Shrank by >50%
                alerts.append(f"**Backup size shrinking** — was {state['last_size']/(1024*1024):.1f}MB, now {current_size/(1024*1024):.1f}MB")
        
        # Check backup count
        if len(files) < 3:
            alerts.append(f"**Only {len(files)} backup files** — expected multiple rotation copies")
    
    # Save state for next run
    save_state({
        "last_size": sum(f.stat().st_size for f in files if f.is_file()) if files else 0,
        "last_check": now.isoformat()
    })
    
    if not alerts:
        sys.exit(0)  # Silent when healthy
    
    print(f"**🟡 Backup Staleness Alert — {now.strftime('%d/%m/%y %H:%M')}**\n")
    for alert in alerts:
        print(f"• {alert}")
    print(f"\n**Action:** Check backup cron, verify `/home/kensei/backups/` contents.")
    sys.exit(0)

if __name__ == "__main__":
    main()
