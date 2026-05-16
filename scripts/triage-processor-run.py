import sqlite3, time

now = int(time.time())

# --- OPS BOARD ---
DB = '/home/kensei/.hermes/kanban/boards/ops/kanban.db'
conn = sqlite3.connect(DB)
cur = conn.cursor()

auto_promote_ops = [
    ('t_cc16faad', 'ops-lead'),   # stale remote - mechanical git fix
    ('t_be05c38b', 'ops-lead'),   # pipeline latency - infra monitoring
    ('t_2e3ce1b3', 'ops-lead'),   # cron scheduler delays - infra/cron
    ('t_70c0b9e6', 'ops-lead'),   # github-radar-merged 52min - infra/cron
]

for tid, assignee in auto_promote_ops:
    cur.execute("UPDATE tasks SET status='todo', assignee=? WHERE id=? AND status='triage'", (assignee, tid))
    print(f"ops: {tid} -> todo, {assignee}")

conn.commit()
conn.close()

# --- RESEARCH BOARD ---
DB2 = '/home/kensei/.hermes/kanban/boards/research/kanban.db'
conn2 = sqlite3.connect(DB2)
cur2 = conn2.cursor()

adopt_ids = [
    't_7d21d461', 't_89b77d6c', 't_2691d45c', 't_c8643cf4', 't_3990e773',
    't_b8525b10', 't_2628d5c2', 't_507fdf4e', 't_ab25ac81', 't_ed56ff18',
    't_59538f15', 't_e9ae51af', 't_bb988f43', 't_e5c3a15f', 't_f6547589',
    't_9ed3d338', 't_d0fac5cc', 't_51a8420c', 't_bf6b9ad8', 't_787eee66',
    't_11087bc9', 't_00047046', 't_e5dde461', 't_8576d9a0', 't_658a2e8d',
    't_ea6edade', 't_d5128e3e', 't_3b346097', 't_84985315', 't_ed8f3dc8',
    't_c638dfbe', 't_0d0f32a5', 't_feaa2a63', 't_83a8d68c', 't_cec0ed17',
    't_c201d80e', 't_5c59ec91', 't_76e68051', 't_75bbd60e', 't_b7fdaad2',
    't_414fda35', 't_6c0e006a', 't_a7f17640', 't_b78008c3', 't_583837dc',
    't_37058bb4', 't_411b29be', 't_c0d0b92f', 't_1d06c53a'
]

extract_ids = [
    't_93c1e984', 't_e2cae4de', 't_5bf260fb', 't_7988f296', 't_e3205506',
    't_6ef0796b', 't_e0331123', 't_19285755', 't_fa16588c', 't_bb44fe22',
    't_f0d95b1c', 't_6dbb639f', 't_f3b04cbe', 't_c18e075b', 't_11dbe00f',
    't_6ff38167', 't_6ea75295', 't_9de03a15', 't_2dbed03b', 't_3100886e',
    't_d9a9879c', 't_fb74f113', 't_db65d9a7'
]

plugin_ids = ['t_b7f60e9c', 't_989059e2']

for tid in adopt_ids:
    cur2.execute("UPDATE tasks SET status='todo', assignee='research-lead' WHERE id=? AND status='triage'", (tid,))
    print(f"research: {tid} -> todo, research-lead [ADOPT]")

for tid in extract_ids:
    cur2.execute("UPDATE tasks SET status='todo', assignee='research-lead' WHERE id=? AND status='triage'", (tid,))
    print(f"research: {tid} -> todo, research-lead [EXTRACT]")

for tid in plugin_ids:
    cur2.execute("UPDATE tasks SET status='todo', assignee='research-lead' WHERE id=? AND status='triage'", (tid,))
    print(f"research: {tid} -> todo, research-lead [PLUGIN]")

conn2.commit()
conn2.close()

print(f"All done at {now}")
