#!/usr/bin/env python3
"""Check for wesker blocked/ready tasks that need review children."""
import sqlite3, json, subprocess, sys

DB = '/home/kensei/.hermes/kanban.db'

def get_candidates():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    # Find tasks: blocked or ready, assignee=wesker, workspace exists
    # created within last 72 hours, no active review child
    cur.execute('''
        SELECT id, title, body, workspace_path, status, workflow_template_id, result
        FROM tasks
        WHERE assignee = 'wesker'
        AND status IN ('blocked', 'ready')
        AND workspace_path IS NOT NULL
        AND created_at >= strftime('%s','now') - 259200
        ORDER BY created_at DESC
        LIMIT 5
    ''')
    return cur.fetchall()

def has_active_child(parent_id, cur):
    cur.execute('''
        SELECT child.id, child.status, child.title
        FROM task_links l
        JOIN tasks child ON child.id = l.child_id
        WHERE l.parent_id = ? AND child.status NOT IN ('archived', 'done')
    ''', (parent_id,))
    return cur.fetchall()

def check_workspace(path):
    import os
    if not path or not os.path.isdir(path):
        return False, "no_dir"
    files = os.listdir(path)
    return len(files) > 0, files[:5] if files else "empty"

def main():
    candidates = get_candidates()
    if not candidates:
        print("NO_CANDIDATES")
        return

    for row in candidates:
        tid, title, body, wspath, status, wtid, result = row
        files_ok, detail = check_workspace(wspath)
        print(f"=== {tid} ===")
        print(f"Title: {title}")
        print(f"Status: {status}")
        print(f"Workspace: {wspath}")
        print(f"Files: {detail}")
        print(f"Workflow: {wtid}")
        print(f"Result: {result}")
        print()

if __name__ == '__main__':
    main()
