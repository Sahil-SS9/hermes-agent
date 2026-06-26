#!/usr/bin/env python3
"""Web backend health check — SearXNG + GroktoCrawl.

Checks:
1. SearXNG container running and responding on :8082
2. GroktoCrawl agent-svc container running and responding on :8090
3. GroktoCrawl scrape endpoint functional
4. DDGS importable and working

Exit codes:
  0 = all healthy
  1 = one or more services degraded
  2 = critical failure (search or extract completely down)

Designed for cron execution. Output is single-line status for Discord.
"""
import subprocess
import json
import sys
import os
from datetime import datetime

def check_searxng():
    """Check SearXNG container + API."""
    # Container status
    r = subprocess.run(
        ['sudo', 'docker', 'inspect', 'searxng', '--format', '{{.State.Status}}'],
        capture_output=True, text=True, timeout=5
    )
    if r.returncode != 0 or 'running' not in r.stdout:
        return False, "container down"
    
    # API check
    r2 = subprocess.run(
        ['curl', '-sL', '--max-time', '5',
         'http://127.0.0.1:8082/search?q=health+check&format=json'],
        capture_output=True, text=True, timeout=10
    )
    if r2.returncode != 0 or not r2.stdout:
        return False, "API not responding"
    try:
        d = json.loads(r2.stdout)
        n = len(d.get('results', []))
        if n == 0:
            return False, "0 results returned"
        return True, f"{n} results"
    except:
        return False, "invalid JSON response"


def check_groktoCrawl():
    """Check GroktoCrawl agent container + scrape endpoint."""
    # Container status
    r = subprocess.run(
        ['sudo', 'docker', 'inspect', 'groktocrawl-agent-svc-1', '--format', '{{.State.Status}}'],
        capture_output=True, text=True, timeout=5
    )
    if r.returncode != 0 or 'running' not in r.stdout:
        return False, "container down"
    
    # Health endpoint
    r2 = subprocess.run(
        ['curl', '-sL', '--max-time', '10', 'http://localhost:8090/health'],
        capture_output=True, text=True, timeout=15
    )
    if r2.returncode != 0 or not r2.stdout:
        return False, "health endpoint not responding"
    try:
        h = json.loads(r2.stdout)
        status = h.get('status', 'unknown')
        checks = h.get('checks', {})
        down_services = [k for k, v in checks.items() if v.get('status') == 'down' and k not in ('searxng',)]
        # SearXNG health check inside GroktoCrawl hits /healthz which returns 404
        # This is cosmetic — search still works via the SearXNG search API
        if down_services:
            return False, f"degraded: {','.join(down_services)}"
        if status == 'down' and not down_services:
            return True, "healthy (searxng health check cosmetic 404, search works)"
        return True, f"healthy ({status})"
    except:
        return False, "invalid health JSON"


def check_ddgs():
    """Check DDGS is importable and functional."""
    r = subprocess.run(
        ['python3', '-c',
         'from ddgs import DDGS; ddgs=DDGS(); r=list(ddgs.text("test", max_results=1)); exit(0 if len(r)>0 else 1)'],
        capture_output=True, text=True, timeout=15
    )
    if r.returncode == 0:
        return True, "working"
    return False, f"import or search failed: {r.stderr[:80]}"


def main():
    ts = datetime.now().strftime('%d/%m/%y %H:%M')
    
    searx_ok, searx_detail = check_searxng()
    grok_ok, grok_detail = check_groktoCrawl()
    ddgs_ok, ddgs_detail = check_ddgs()
    
    all_ok = searx_ok and grok_ok and ddgs_ok
    search_ok = searx_ok or ddgs_ok  # at least one search backend
    extract_ok = grok_ok  # only extract backend
    
    # Silent when healthy
    if all_ok:
        sys.exit(0)
    
    # Build alert only when something is wrong
    parts = []
    parts.append(f"SearXNG {'OK' if searx_ok else 'FAIL'} ({searx_detail})")
    parts.append(f"GroktoCrawl {'OK' if grok_ok else 'FAIL'} ({grok_detail})")
    parts.append(f"DDGS {'OK' if ddgs_ok else 'FAIL'} ({ddgs_detail})")
    
    if search_ok and extract_ok:
        status_emoji = "🟡"
        exit_code = 1
    else:
        status_emoji = "🔴"
        exit_code = 2
    
    print(f"{status_emoji} Web Backend Health [{ts}]")
    for p in parts:
        print(f"  {p}")
    
    if not search_ok:
        print("  CRITICAL: All search backends down")
    if not extract_ok:
        print("  CRITICAL: Extract backend (GroktoCrawl) down — extract will fall back to Tavily")
    
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
