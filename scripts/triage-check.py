import sqlite3, json, os
boards = {
    'ops': '/home/kensei/.hermes/kanban/boards/ops/kanban.db',
    'research': '/home/kensei/.hermes/kanban/boards/research/kanban.db',
    'apps': '/home/kensei/.hermes/kanban/boards/apps/kanban.db',
    'content-lead': '/home/kensei/.hermes/kanban/boards/content-lead/kanban.db',
    'default': '/home/kensei/.hermes/kanban.db',
}
for slug, db_path in sorted(boards.items()):
    print(f'=== {slug} ===')
    if not os.path.exists(db_path):
        print(f'  DB not found at {db_path}')
        continue
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, title, body, assignee FROM tasks WHERE status='triage'")
        rows = [dict(r) for r in cur.fetchall()]
        print(json.dumps(rows, ensure_ascii=False))
    except Exception as e:
        print(f'  Error: {e}')
    conn.close()
