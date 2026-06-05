#!/usr/bin/env python3
"""
denji-logboard-monitor.py

Monitors agent.log and errors.log for patterns and issues requiring investigation.
Includes noise filtering, pattern-vs-incident analysis, and cross-run deduplication.

Outputs JSON array of verified findings. Silent (empty stdout) when nothing to report.
"""

import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOGS_DIR = Path(os.path.expanduser("~/.hermes/logs"))
AGENT_LOG = LOGS_DIR / "agent.log"
ERRORS_LOG = LOGS_DIR / "errors.log"
DETECTIONS_PATH = Path(os.path.expanduser("~/.hermes/governance/logboard/monitor-detections.jsonl"))

# How far back to look (minutes)
LOOKBACK_MINUTES = 240

# Thresholds
HIGH_LATENCY_SECONDS = 30
API_CALL_SPIKE_THRESHOLD = 200
MIN_REPEAT_FOR_PATTERN = 3  # minimum occurrences to classify as "pattern"

# Known noise patterns — skip these entirely
NOISE_PATTERNS = [
    # Test-related (pytest tmp dirs)
    r'/tmp/pytest-',
    r'test_gateway_dispatcher',
    # Expected plugin warnings (image gen providers not configured)
    r"Failed to load plugin '(fal|krea|openai|openai-codex|xai)'",
    r"register_provider\(\) expects an ImageGenProvider",
    # Copilot auth (expected when not using Copilot)
    r"copilot_auth.*Token from GITHUB_TOKEN is not supported",
    r"openai-codex requested but no Codex OAuth token",
    # Auxiliary provider fallback (expected — just means one provider unavailable)
    r"Auxiliary.*unavailable: no .* authentication found",
    r"marking \w+ unhealthy for 60s",
]

# Minimum severity to notify on (below this = log only, don't notify)
NOTIFY_MIN_SEVERITY = "warning"


def parse_timestamp(line):
    """Extract datetime from log line."""
    m = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})', line)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def tail_lines(filepath, max_lines=8000):
    """Read last N lines of a file."""
    if not filepath.exists():
        return []
    try:
        with open(filepath, 'r', errors='replace') as f:
            lines = f.readlines()
        return lines[-max_lines:]
    except OSError:
        return []


def filter_recent(lines, minutes):
    """Keep only lines from the last N minutes."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    recent = []
    for line in lines:
        ts = parse_timestamp(line)
        if ts and ts >= cutoff:
            recent.append((ts, line))
    return recent


def is_noise(line):
    """Check if a log line matches known noise patterns."""
    for pattern in NOISE_PATTERNS:
        if re.search(pattern, line):
            return True
    return False


def load_previous_detections(hours=48):
    """Load recent detections from the log to avoid re-notifying about the same issue."""
    if not DETECTIONS_PATH.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent = []
    try:
        with open(DETECTIONS_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts_str = entry.get("timestamp", "")
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        if ts >= cutoff:
                            recent.append(entry)
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        pass
    return recent


def classify_incident_type(count, window_minutes):
    """
    Classify whether something is a pattern or isolated incident.
    Returns: 'pattern', 'isolated', or 'emerging'
    """
    if count >= MIN_REPEAT_FOR_PATTERN * 2:
        return "pattern"
    elif count >= MIN_REPEAT_FOR_PATTERN:
        # Check if concentrated (all in short timespan) or spread out
        return "pattern"
    elif count == 1:
        return "isolated"
    else:
        return "emerging"


def analyze_agent_log(lines):
    """Analyze agent.log for patterns requiring investigation."""
    findings = []
    if not lines:
        return findings

    # Filter out noise
    clean_lines = [(ts, line) for ts, line in lines if not is_noise(line)]

    # --- 1. High latency API calls ---
    high_latency_by_model = defaultdict(list)
    for ts, line in clean_lines:
        if "API call" in line and "latency=" in line:
            m = re.search(r'latency=(\d+\.?\d*)s', line)
            model_m = re.search(r'model=(\S+)', line)
            session_m = re.search(r'\[(\w+)\]', line)
            if m:
                latency = float(m.group(1))
                if latency >= HIGH_LATENCY_SECONDS:
                    model = model_m.group(1) if model_m else "unknown"
                    high_latency_by_model[model].append({
                        "timestamp": ts.isoformat(),
                        "latency": latency,
                        "session": session_m.group(1) if session_m else "unknown"
                    })

    for model, calls in high_latency_by_model.items():
        count = len(calls)
        incident_type = classify_incident_type(count, LOOKBACK_MINUTES)
        max_lat = max(c["latency"] for c in calls)
        unique_sessions = len(set(c["session"] for c in calls))

        # Skip if all calls are from same session and count is low — likely just a slow request
        if unique_sessions == 1 and count <= 2:
            severity = "info"
        elif incident_type == "pattern":
            severity = "warning"
        else:
            severity = "info"

        findings.append({
            "rule": "high_latency",
            "severity": severity,
            "domain": "ops",
            "classification": incident_type,
            "detail": f"Model '{model}': {count} high-latency calls (max {max_lat:.0f}s) across {unique_sessions} session(s)",
            "source": "agent.log",
            "model": model,
            "count": count,
            "max_latency": max_lat,
            "unique_sessions": unique_sessions,
            "recommendation": f"Review {model} provider performance. {'Consider switching model if pattern persists.' if incident_type == 'pattern' else 'Isolated — monitor for recurrence.'}"
        })

    # --- 2. API call volume per session (loop detection) ---
    session_api_calls = Counter()
    for ts, line in clean_lines:
        if "API call #" in line:
            session_m = re.search(r'\[(\w+)\]', line)
            call_m = re.search(r'API call #(\d+)', line)
            if session_m and call_m:
                session_api_calls[session_m.group(1)] = max(
                    session_api_calls[session_m.group(1)],
                    int(call_m.group(1))
                )

    for session, count in session_api_calls.items():
        if count >= API_CALL_SPIKE_THRESHOLD:
            findings.append({
                "rule": "api_call_spike",
                "severity": "error",
                "domain": "ops",
                "classification": "isolated",
                "detail": f"Session {session}: {count} API calls — possible infinite loop or long-running task",
                "source": "agent.log",
                "session": session,
                "count": count,
                "recommendation": "Investigate session for stuck loops. Check if max_iterations was hit."
            })

    # --- 3. Tool execution failures ---
    tool_failures = defaultdict(list)
    for ts, line in clean_lines:
        if "WARNING" in line and "tool_executor" in line:
            m = re.search(r'tool (\w+) (failed|error|timeout|exception)', line, re.IGNORECASE)
            if m:
                tool_failures[m.group(1)].append(ts.isoformat())

    for tool, timestamps in tool_failures.items():
        count = len(timestamps)
        if count >= MIN_REPEAT_FOR_PATTERN:
            incident_type = classify_incident_type(count, LOOKBACK_MINUTES)
            findings.append({
                "rule": "tool_failure_pattern",
                "severity": "warning",
                "domain": "ops",
                "classification": incident_type,
                "detail": f"Tool '{tool}' failed {count} times in window",
                "source": "agent.log",
                "tool": tool,
                "count": count,
                "first_seen": timestamps[0] if timestamps else None,
                "last_seen": timestamps[-1] if timestamps else None,
                "recommendation": f"Check {tool} implementation. {'Recurring — needs investigation.' if incident_type == 'pattern' else 'Monitor for escalation.'}"
            })

    # --- 4. Environment churn ---
    cleanup_count = sum(1 for _, line in clean_lines if "Cleaned up inactive environment" in line)
    if cleanup_count > 10:
        findings.append({
            "rule": "environment_churn",
            "severity": "info",
            "domain": "ops",
            "classification": "pattern" if cleanup_count > 20 else "emerging",
            "detail": f"{cleanup_count} environment cleanups in window — high session churn",
            "source": "agent.log",
            "count": cleanup_count,
            "recommendation": "Informational. High churn may indicate excessive session creation."
        })

    return findings


def analyze_errors_log(lines):
    """Analyze errors.log for patterns requiring investigation."""
    findings = []
    if not lines:
        return findings

    # Filter out noise
    clean_lines = [(ts, line) for ts, line in lines if not is_noise(line)]

    # --- 1. Error pattern clustering ---
    error_patterns = defaultdict(list)
    for ts, line in clean_lines:
        if "ERROR" in line:
            # Normalize for clustering
            normalized = re.sub(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+', '', line)
            normalized = re.sub(r'\[\w+\]', '', normalized)
            normalized = re.sub(r'/[^\s]+\.db', '/<db>', normalized)
            parts = normalized.strip().split(': ', 2)
            if len(parts) >= 2:
                key = f"{parts[0].strip()}: {parts[1].strip()[:80]}"
            else:
                key = normalized.strip()[:100]
            error_patterns[key].append(ts.isoformat())

    for pattern, timestamps in error_patterns.items():
        count = len(timestamps)
        if count >= MIN_REPEAT_FOR_PATTERN:
            incident_type = classify_incident_type(count, LOOKBACK_MINUTES)
            # Check if all errors are in a tight cluster (burst) or spread out
            if count >= 3:
                try:
                    first = datetime.fromisoformat(timestamps[0])
                    last = datetime.fromisoformat(timestamps[-1])
                    if first.tzinfo is None:
                        first = first.replace(tzinfo=timezone.utc)
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    span_minutes = (last - first).total_seconds() / 60
                    burst = span_minutes < 5  # all within 5 minutes = burst
                except (ValueError, TypeError):
                    burst = False
            else:
                burst = False

            findings.append({
                "rule": "error_cluster",
                "severity": "error" if count >= 5 else "warning",
                "domain": "ops",
                "classification": "pattern" if incident_type == "pattern" else "burst" if burst else "emerging",
                "detail": f"Error pattern ({count}x): {pattern[:120]}",
                "source": "errors.log",
                "count": count,
                "burst": burst,
                "first_seen": timestamps[0],
                "last_seen": timestamps[-1],
                "recommendation": f"{'Burst detected — likely transient. Monitor next window.' if burst else 'Recurring — investigate root cause in: ' + pattern.split(':')[0].strip()}"
            })

    # --- 2. Asyncio errors ---
    asyncio_timestamps = []
    for ts, line in clean_lines:
        if "asyncio" in line and ("ERROR" in line or "Task was destroyed" in line):
            asyncio_timestamps.append(ts.isoformat())

    if len(asyncio_timestamps) >= MIN_REPEAT_FOR_PATTERN:
        incident_type = classify_incident_type(len(asyncio_timestamps), LOOKBACK_MINUTES)
        findings.append({
            "rule": "asyncio_errors",
            "severity": "warning",
            "domain": "ops",
            "classification": incident_type,
            "detail": f"{len(asyncio_timestamps)} asyncio errors in window — possible event loop issues",
            "source": "errors.log",
            "count": len(asyncio_timestamps),
            "recommendation": "Check gateway for unclosed resources or cancelled tasks." if incident_type == "pattern" else "Monitor for escalation."
        })

    # --- 3. Kanban DB errors ---
    kanban_timestamps = []
    for ts, line in clean_lines:
        if "kanban" in line.lower() and ("ERROR" in line or "not a valid SQLite" in line):
            kanban_timestamps.append(ts.isoformat())

    if len(kanban_timestamps) >= 2:
        incident_type = classify_incident_type(len(kanban_timestamps), LOOKBACK_MINUTES)
        findings.append({
            "rule": "kanban_db_errors",
            "severity": "error",
            "domain": "ops",
            "classification": incident_type,
            "detail": f"{len(kanban_timestamps)} kanban database errors — possible corruption or concurrent access",
            "source": "errors.log",
            "count": len(kanban_timestamps),
            "recommendation": "Run `hermes kanban check` to verify DB integrity." if incident_type == "pattern" else "Likely transient. Monitor next window."
        })

    # --- 4. Gateway platform errors ---
    platform_timestamps = defaultdict(list)
    for ts, line in clean_lines:
        if "gateway.platforms" in line and "ERROR" in line:
            m = re.search(r'gateway\.platforms\.(\w+)', line)
            if m:
                platform_timestamps[m.group(1)].append(ts.isoformat())

    for platform, timestamps in platform_timestamps.items():
        count = len(timestamps)
        if count >= MIN_REPEAT_FOR_PATTERN:
            incident_type = classify_incident_type(count, LOOKBACK_MINUTES)
            findings.append({
                "rule": "platform_errors",
                "severity": "error",
                "domain": "ops",
                "classification": incident_type,
                "detail": f"Platform '{platform}' produced {count} errors in window",
                "source": "errors.log",
                "platform": platform,
                "count": count,
                "recommendation": f"Check {platform} adapter config and connectivity." if incident_type == "pattern" else "Single incident — monitor."
            })

    return findings


def deduplicate_with_history(findings, previous_detections):
    """
    Remove findings that were already notified in recent runs.
    Only keep: new findings, or existing findings that have escalated in severity/count.
    """
    # Build a lookup of previous detections by rule + detail prefix
    prev_lookup = {}
    for det in previous_detections:
        key = (det.get("rule", ""), det.get("detail", "")[:60])
        prev_lookup[key] = det

    filtered = []
    for f in findings:
        key = (f["rule"], f["detail"][:60])

        if key not in prev_lookup:
            # New finding — keep it
            filtered.append(f)
            continue

        # Existing finding — check if escalated
        prev = prev_lookup[key]
        prev_count = prev.get("count", 0)
        curr_count = f.get("count", 0)

        if curr_count > prev_count * 1.5:
            # Count increased by 50%+ — escalate
            f["severity"] = "error" if f["severity"] == "warning" else f["severity"]
            f["escalated"] = True
            f["previous_count"] = prev_count
            filtered.append(f)
        # else: same issue, already notified — skip

    return filtered


def main():
    # Read recent lines
    agent_lines = tail_lines(AGENT_LOG, 10000)
    errors_lines = tail_lines(ERRORS_LOG, 6000)

    agent_recent = filter_recent(agent_lines, LOOKBACK_MINUTES)
    errors_recent = filter_recent(errors_lines, LOOKBACK_MINUTES)

    # Fallback: if nothing recent in errors, use last 500 lines for pattern detection
    if not errors_recent and errors_lines:
        errors_recent = [(parse_timestamp(l), l) for l in errors_lines[-500:] if parse_timestamp(l)]

    # Analyze
    findings = []
    findings.extend(analyze_agent_log(agent_recent))
    findings.extend(analyze_errors_log(errors_recent))

    # Deduplicate within this run
    seen = {}
    for f in findings:
        key = (f["rule"], f["detail"][:60])
        if key not in seen or _severity_rank(f["severity"]) > _severity_rank(seen[key]["severity"]):
            seen[key] = f
    deduped = list(seen.values())

    # Cross-run deduplication
    previous = load_previous_detections(hours=LOOKBACK_MINUTES // 60 + 24)
    final = deduplicate_with_history(deduped, previous)

    # Filter by minimum severity for notification
    notifiable = [f for f in final if _severity_rank(f["severity"]) >= _severity_rank(NOTIFY_MIN_SEVERITY)]

    # Build output
    output = {
        "findings": notifiable,
        "total_detected": len(deduped),
        "suppressed": len(deduped) - len(notifiable),
        "new_or_escalated": len(notifiable),
        "window_minutes": LOOKBACK_MINUTES,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    if not notifiable:
        return

    print(json.dumps(output, indent=2))


def _severity_rank(sev):
    return {"info": 0, "warning": 1, "error": 2, "critical": 3}.get(sev, 0)


if __name__ == "__main__":
    main()
