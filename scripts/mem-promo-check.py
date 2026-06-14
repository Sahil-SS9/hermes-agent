#!/usr/bin/env python3
"""Memory Promotion cron: query Mnemosyne for high-confidence memories and promote to brain."""
import sqlite3, json, os

DB = '/home/kensei/.hermes/mnemosyne/data/mnemosyne.db'
BRAIN = '/home/kensei/brain'

conn = sqlite3.connect(DB)
cur = conn.cursor()

# Get tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("Tables:", tables)

for tbl in tables:
    cur.execute(f"PRAGMA table_info({tbl})")
    cols = [(c[1], c[2]) for c in cur.fetchall()]
    print(f"\n{tbl} columns:", cols)
    try:
        cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        print(f"{tbl} count:", cur.fetchone()[0])
    except Exception as e:
        print(f"{tbl} count error:", e)
    
    # Show first 5 rows
    try:
        col_names = [c[0] for c in cols]
        print(f"{tbl} columns names:", col_names)
        cur.execute(f"SELECT * FROM {tbl} LIMIT 5")
        rows = cur.fetchall()
        for r in rows:
            print(" ", r[:3])  # First 3 fields
    except Exception as e:
        print(f"{tbl} sample error:", e)

conn.close()