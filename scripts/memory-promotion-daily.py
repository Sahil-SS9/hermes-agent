#!/usr/bin/env python3
"""Query Mnemosyne memories table for high-importance promotion candidates."""

import sqlite3
import json

DB = '/home/kensei/.hermes/mnemosyne/data/mnemosyne.db'

conn = sqlite3.connect(DB, timeout=10)
cur = conn.cursor()

# Query memories table for high importance (>= 0.8)
cur.execute("""
    SELECT id, content, source, timestamp, importance, metadata_json, created_at
    FROM memories
    WHERE importance >= 0.8
    ORDER BY timestamp DESC
    LIMIT 30
""")

rows = cur.fetchall()
print(f"FOUND {len(rows)} memories with importance >= 0.8")
print("=" * 100)

for r in rows:
    mid, content, source, ts, importance, meta_json, created_at = r
    meta = {}
    if meta_json and meta_json.strip():
        try:
            meta = json.loads(meta_json)
        except:
            pass
    veracity = meta.get('veracity', 'unknown')
    print(f"\n--- Memory: {mid}")
    print(f"  Content: {content[:200]}")
    print(f"  Source: {source}")
    print(f"  Timestamp: {ts}")
    print(f"  Importance: {importance}")
    print(f"  Veracity: {veracity}")
    print(f"  Meta keys: {list(meta.keys())}")

print("\n\n=================== CONSOLIDATED FACTS ===================")
# Query consolidated_facts for high confidence with veracity=stated or imported
cur.execute("""
    SELECT id, subject, predicate, object, confidence, mention_count,
           first_seen, last_seen, veracity, sources_json
    FROM consolidated_facts
    WHERE confidence >= 0.8
      AND (veracity = 'stated' OR veracity = 'imported')
    ORDER BY mention_count DESC, confidence DESC
    LIMIT 30
""")

rows = cur.fetchall()
print(f"FOUND {len(rows)} consolidated_facts with confidence >= 0.8 and stated/imported veracity")
print("=" * 100)

for r in rows:
    fid, subj, pred, obj, conf, mentions, first, last, veracity, sources = r
    print(f"\n--- Fact: {fid}")
    print(f"  Triple: {subj} -> {pred} -> {obj}")
    print(f"  Confidence: {conf}")
    print(f"  Mention count: {mentions}")
    print(f"  Veracity: {veracity}")
    print(f"  First seen: {first}")

conn.close()
