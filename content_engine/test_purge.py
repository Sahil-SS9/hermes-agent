"""Tests for purge_stale_drafts — 48h retention filter."""
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import database
import config

TEST_DB = Path(tempfile.mktemp(suffix=".db"))
database.DB_PATH = TEST_DB
config.DB_PATH = TEST_DB


def _exec(sql: str, *params):
    """Run SQL with params, commit, close. One-shot only."""
    conn = sqlite3.connect(str(TEST_DB))
    cur = conn.execute(sql, params)
    conn.commit()
    conn.close()
    return cur


def _query(sql: str, *params):
    conn = sqlite3.connect(str(TEST_DB))
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def setup_module():
    if TEST_DB.exists():
        TEST_DB.unlink()
    database.init_db()


def _count_all():
    return _query("SELECT COUNT(*) FROM drafts")[0][0]


def _insert_with_age(draft_id: str, brand: str, hours_ago: int):
    ts = (datetime.utcnow() - timedelta(hours=hours_ago)).isoformat()
    _exec(
        "INSERT INTO drafts (id, brand, platform, pillar, topic, body_text, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        draft_id, brand, "twitter", "test", "test_topic", "Test body", ts,
    )


# --- Tests ---

def test_fresh_draft_survives_purge():
    _exec("DELETE FROM drafts")
    _insert_with_age("fresh-1", "plenishd", hours_ago=1)
    _insert_with_age("fresh-2", "plenishd", hours_ago=12)
    _insert_with_age("fresh-3", "matchdaymaestro", hours_ago=0)

    deleted = database.purge_stale_drafts(retention_hours=48)
    assert deleted == 0, f"Expected 0 deleted, got {deleted}"
    assert _count_all() == 3


def test_stale_drafts_are_purged():
    _exec("DELETE FROM drafts")
    _insert_with_age("stale-1", "plenishd", hours_ago=49)
    _insert_with_age("stale-2", "matchdaymaestro", hours_ago=72)
    _insert_with_age("stale-3", "coachos", hours_ago=100)

    assert _count_all() == 3
    deleted = database.purge_stale_drafts(retention_hours=48)
    assert deleted == 3, f"Expected 3 deleted, got {deleted}"
    assert _count_all() == 0


def test_brand_filter_respected():
    _exec("DELETE FROM drafts")
    _insert_with_age("s-plen", "plenishd", hours_ago=72)
    _insert_with_age("s-match", "matchdaymaestro", hours_ago=72)
    _insert_with_age("f-plen", "plenishd", hours_ago=1)

    deleted = database.purge_stale_drafts(retention_hours=48, brand="plenishd")
    assert deleted == 1
    assert _count_all() == 2


def test_dry_run_counting():
    _exec("DELETE FROM drafts")
    _insert_with_age("a", "plenishd", hours_ago=50)
    _insert_with_age("b", "plenishd", hours_ago=50)
    _insert_with_age("c", "matchdaymaestro", hours_ago=50)
    _insert_with_age("d", "matchdaymaestro", hours_ago=2)

    assert database.count_drafts_older_than(retention_hours=48) == 3
    assert database.count_drafts_older_than(retention_hours=48, brand="plenishd") == 2
    assert database.count_drafts_older_than(retention_hours=48, brand="coachos") == 0


if __name__ == "__main__":
    setup_module()
    tests = [
        ("fresh_draft_survives_purge", test_fresh_draft_survives_purge),
        ("stale_drafts_are_purged", test_stale_drafts_are_purged),
        ("brand_filter_respected", test_brand_filter_respected),
        ("dry_run_counting", test_dry_run_counting),
    ]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS: {name}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {name} — {e}")
    print(f"\n{passed}/{len(tests)} passed")
    if TEST_DB.exists():
        TEST_DB.unlink()
    sys.exit(0 if passed == len(tests) else 1)
