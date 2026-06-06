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

# WS-2 board routing: keyword → board + assignee mapping derived
# from governance/routing/goal-subgoal-routing-map.md
ROUTING_MAP = {
    # code/backend → apps board, octacon
    'apps': {
        'keywords': ['code', 'implement', 'build', 'refactor', 'migrate', 'debug',
                     'api', 'backend', 'frontend', 'component', 'database', 'schema',
                     'test', 'fix bug', 'pr ', 'pull request', 'deploy'],
        'default_assignee': 'octacon',
    },
    # content → content-lead board, ceecee
    'content-lead': {
        'keywords': ['content', 'post', 'draft', 'article', 'brand', 'voice',
                     'social', 'copy', 'tweet', 'linkedin', 'blog'],
        'default_assignee': 'ceecee',
    },
    # ops/infra → ops board, wesker
    'ops': {
        'keywords': ['ops', 'infra', 'docker', 'deploy', 'vps', 'nginx', 'backup',
                     'security', 'cron', 'gateway', 'restart', 'health', 'disk',
                     'memory', 'service', 'systemctl'],
        'default_assignee': 'wesker',
    },
    # research → research board, remii
    'research': {
        'keywords': ['research', 'analysis', 'report', 'market', 'scan',
                     'digest', 'signal', 'trend', 'survey', 'benchmark',
                     'evaluate', 'investigate'],
        'default_assignee': 'remii',
    },
}


def _route_task(title, body):
    """Route a task to the right board and assignee based on keyword matching.
    Returns (board, assignee) or (None, None) if no match."""
    combined = ((title or '') + ' ' + (body or '')).lower()
    for board, cfg in ROUTING_MAP.items():
        for kw in cfg['keywords']:
            if kw in combined:
                return board, cfg['default_assignee']
    return None, None

def _get_board_db(board):
    """Get the db_path for a board slug."""
    if board == 'default':
        return DEFAULT_DB
    return os.path.join(DB_PATH_BASE, board, 'kanban.db')


def _set_task_tier(board, task_id, tier):
    """Persist the tier classification on a task."""
    db_path = _get_board_db(board)
    if not os.path.exists(db_path):
        return
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE tasks SET tier = ? WHERE id = ?", (tier, task_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


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

def _set_task_assignee(board, task_id, assignee):
    """Set the assignee on a task via direct SQL."""
    db_path = _get_board_db(board)
    if not os.path.exists(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE tasks SET assignee = ? WHERE id = ? AND (assignee IS NULL OR assignee = '')",
                     (assignee, task_id))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def _promote_to_pipeline(task_id, board, stage):
    """Promote a task to a pipeline stage (research/prd/spec/council).

    Sets status=stage and pipeline_stage=stage via direct SQL.
    Returns True on success, False on failure.
    """
    db_path = _get_board_db(board)
    if not os.path.exists(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE tasks SET status = ?, pipeline_stage = ? WHERE id = ?",
            (stage, stage, task_id)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def classify_task(title, body):
    """Classify triage task: AUTO-PROMOTE vs NEEDS HUMAN, and tier (fast/full)."""
    title_lower = title.lower() if title else ''
    body_lower = (body or '').lower()

    # Tier classification: fast vs full
    # Full-tier keywords: product, feature, research, multi-step, build, implement
    full_keywords = [
        'product', 'feature', 'research', 'multi-step', 'build',
        'implement', 'refactor', 'migrate', 'redesign', 'architecture',
        'pipeline', 'workflow', 'end-to-end', 'deploy app',
    ]
    # Fast-tier keywords: ops, infra, config, cron, quick fix
    fast_keywords = [
        'config', 'cron', 'restart', 'health check', 'fix typo',
        'update doc', 'add column', 'bump version', 'cleanup',
        'orphan', 'stale', 'disk', 'lock', 'skill activation',
    ]

    tier = 'full'  # default: most triage tasks need full pipeline
    for kw in fast_keywords:
        if kw in title_lower or kw in body_lower:
            tier = 'fast'
            break

    needs_human_prefixes = ['fork/product:', 'adopt:', 'extract:', 'plugin/skill:']
    for prefix in needs_human_prefixes:
        if title_lower.startswith(prefix):
            return 'NEEDS HUMAN', tier

    auto_promote_keywords = ['orphan process', 'disk alert', 'lock file', 'stale config',
                             'uncommitted changes', 'missing-but-trivial files',
                             'skills tracking', 'usage data']
    for keyword in auto_promote_keywords:
        if keyword in title_lower:
            return 'AUTO-PROMOTE', tier

    return 'NEEDS HUMAN', tier

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
        classification, tier = classify_task(title, body)
        # WS-2 board routing: auto-assign unassigned tasks based on keywords
        routed_board, routed_assignee = None, None
        if not assignee or not assignee.strip():
            routed_board, routed_assignee = _route_task(title, body)

        if classification == 'AUTO-PROMOTE':
            if tier == 'full':
                # Feature pipeline: tier=full tasks enter at 'research'
                # stage. Intake gate must pass (body has problem + success
                # criteria) before promotion.
                from hermes_cli.feature_pipeline import validate_intake_brief
                gate_fail = validate_intake_brief(body)
                if gate_fail:
                    reason = f"Intake gate failed: {gate_fail}"
                    if block_task(task_id, board, reason):
                        _set_task_tier(board, task_id, tier)
                        pending_tasks.append({
                            'id': task_id, 'board': board, 'title': title,
                            'body': body, 'assignee': assignee,
                            'blocked_at': int(time.time()), 'investigated': False
                        })
                    else:
                        errors.append({'id': task_id, 'board': board, 'title': title, 'error': 'block failed'})
                    continue
                # Gate passed — promote to 'research' with pipeline_stage set
                if _promote_to_pipeline(task_id, board, 'research'):
                    _set_task_tier(board, task_id, tier)
                    if routed_assignee:
                        _set_task_assignee(board, task_id, routed_assignee)
                    auto_promoted.append({'id': task_id, 'board': board, 'title': title, 'tier': tier, 'stage': 'research'})
                else:
                    errors.append({'id': task_id, 'board': board, 'title': title, 'error': 'promote to research failed'})
            else:
                # Fast tier: promote to 'todo' (existing behavior)
                if promote_task(task_id, board):
                    _set_task_tier(board, task_id, tier)
                    if routed_assignee:
                        _set_task_assignee(board, task_id, routed_assignee)
                    auto_promoted.append({'id': task_id, 'board': board, 'title': title, 'tier': tier})
                else:
                    errors.append({'id': task_id, 'board': board, 'title': title, 'error': 'promote failed'})
        else:
            reason = f"Needs Sahil's decision: {title[:120]}"
            if block_task(task_id, board, reason):
                _set_task_tier(board, task_id, tier)
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
