#!/usr/bin/env python3
"""KENSEI Triage Processor - no_agent version, v3.0

Scans all kanban boards for triage tasks, classifies them, and updates status.
Writes NEEDS-HUMAN tasks to a pending-investigation file for the investigator cron.
SILENT — does NOT notify directly. All notification handled by kensei-triage-investigator.

Uses correct CLI: promote (triage→todo), block (triage→blocked).
"""
import subprocess
import json
import os
import sys
import time
import sqlite3
from datetime import datetime, timedelta

# Configuration
BOARDS = ['ops', 'research', 'apps', 'content-lead', 'default']
STATE_FILE = '/home/kensei/.hermes/data/triage-state.json'
PENDING_FILE = '/home/kensei/.hermes/data/pending-investigation.json'
DB_PATH_BASE = '/home/kensei/.hermes/kanban/boards/'
DEFAULT_DB = '/home/kensei/.hermes/kanban.db'

def run_hermes_list(board, status):
    """Run hermes kanban list --status <status> --json for a board."""
    cmd = ['hermes', 'kanban', '--board', board, 'list', '--status', status, '--json']
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return None

def promote_task(task_id, board):
    """Promote a task from triage to todo."""
    cmd = ['hermes', 'kanban', '--board', board, 'promote', task_id]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode == 0

def block_task(task_id, board, reason):
    """Block a task with a decision-needed reason."""
    cmd = ['hermes', 'kanban', '--board', board, 'block', task_id]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    blocked_ok = result.returncode == 0

    # Add comment with the reason
    comment_cmd = ['hermes', 'kanban', '--board', board, 'comment', task_id, '--body', reason]
    subprocess.run(comment_cmd, capture_output=True, text=True, timeout=30)

    return blocked_ok

def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def classify_task(title, body):
    title_lower = title.lower() if title else ''
    needs_human_prefixes = ['fork/product:', 'adopt:', 'extract:', 'plugin/skill:']
    for prefix in needs_human_prefixes:
        if title_lower.startswith(prefix):
            return 'NEEDS HUMAN'
    auto_promote_keywords = ['orphan process', 'disk alert', 'lock file', 'stale config',
                             'uncommitted changes', 'missing-but-trivial files',
                             'skills tracking', 'usage data']
    for keyword in auto_promote_keywords:
        if keyword in title_lower:
            return 'AUTO-PROMOTE'
    return 'NEEDS HUMAN'

def main():
    all_triage = []
    for board in BOARDS:
        tasks = run_hermes_list(board, 'triage')
        if tasks is None or not isinstance(tasks, list):
            continue
        for task in tasks:
            tid = task.get('id')
            title = task.get('title', '')
            body = task.get('body', '')
            assignee = task.get('assignee', '')
            if tid:
                all_triage.append((tid, board, title, body, assignee))

    if not all_triage:
        # No triage tasks — clear pending file if empty
        state = load_json(STATE_FILE, {'notified_ids': [], 'notified_at': 0, 'notified_count': 0})
        if set(state.get('notified_ids', [])) != set():
            state['notified_ids'] = []
            state['notified_at'] = int(time.time())
            state['notified_count'] = 0
            save_json(STATE_FILE, state)
        # Clear pending file
        save_json(PENDING_FILE, {'tasks': [], 'timestamp': int(time.time())})
        return  # SILENT

    auto_promoted = []
    pending_tasks = []
    errors = []

    for task_id, board, title, body, assignee in all_triage:
        classification = classify_task(title, body)
        if classification == 'AUTO-PROMOTE':
            if promote_task(task_id, board):
                auto_promoted.append({'id': task_id, 'board': board, 'title': title})
            else:
                errors.append({'id': task_id, 'board': board, 'title': title, 'error': 'promote failed'})
                print(f"[ERROR] promote failed for {task_id} ({board}): {title[:80]}", file=sys.stderr)
        else:
            reason = f"Needs Sahil's decision: {title[:120]}"
            if block_task(task_id, board, reason):
                pending_tasks.append({
                    'id': task_id,
                    'board': board,
                    'title': title,
                    'body': body,
                    'assignee': assignee,
                    'blocked_at': int(time.time()),
                    'investigated': False
                })
            else:
                errors.append({'id': task_id, 'board': board, 'title': title, 'error': 'block failed'})
                print(f"[ERROR] block failed for {task_id} ({board}): {title[:80]}", file=sys.stderr)

    # Pipeline bypass check
    bypass_found = []
    for board in BOARDS:
        for status in ['todo', 'ready']:
            tasks = run_hermes_list(board, status)
            if tasks is None or not isinstance(tasks, list):
                continue
            for task in tasks:
                tid = task.get('id')
                title = task.get('title', '').lower()
                if any(title.startswith(p) for p in ['fork/product:', 'adopt:', 'extract:', 'plugin/skill:']):
                    comment = "Pipeline bypass — created at todo/ready without human approval. See codebase-consolidation skill PITFALLS."
                    if block_task(tid, board, comment):
                        bypass_found.append({'id': tid, 'board': board, 'title': task.get('title', '')})

    # Write pending investigation file for the investigator cron
    pending_data = {
        'tasks': pending_tasks,
        'bypass_found': bypass_found,
        'auto_promoted_count': len(auto_promoted),
        'error_count': len(errors),
        'timestamp': int(time.time())
    }
    save_json(PENDING_FILE, pending_data)

    # Update triage state for debounce tracking
    current_ids = [t['id'] for t in pending_tasks]
    state = load_json(STATE_FILE, {'notified_ids': [], 'notified_at': 0, 'notified_count': 0})
    state['notified_ids'] = current_ids
    state['notified_at'] = int(time.time())
    state['notified_count'] = len(current_ids)
    save_json(STATE_FILE, state)

    # SILENT — notification handled by kensei-triage-investigator cron
    # Only print if there's a critical error (bypass found with no pending tasks)
    if bypass_found and not pending_tasks:
        lines = ['⚠️ Pipeline bypass blocked (no triage tasks):']
        for b in bypass_found:
            lines.append(f"• `{b['id']}` ({b['board']}): {b['title']}")
        print('\n'.join(lines))

if __name__ == '__main__':
    main()
