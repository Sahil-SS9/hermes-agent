"""Phase 1: skill broker is backed by the unified profile activity ledger.

Verifies borrow/deny/revoke/count flow through the central append-only ledger
and that query_events reads them back correctly. Isolated to a temp ledger via
monkeypatching ledger_db_path.
"""
import importlib.util
from pathlib import Path

import pytest

from hermes_cli import profile_activity_ledger as pal


@pytest.fixture
def temp_ledger(tmp_path, monkeypatch):
    db = tmp_path / "ledger.sqlite"
    monkeypatch.setattr(pal, "ledger_db_path", lambda: db)
    # JSONL mirror also lives under the temp governance dir
    monkeypatch.setattr(pal, "_governance_root", lambda: tmp_path)
    return db


@pytest.fixture
def broker(temp_ledger):
    spec = importlib.util.spec_from_file_location(
        "skill_broker_ledger",
        str(Path(__file__).resolve().parents[2] / "scripts" / "skill-broker-ledger.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_query_events_filters(temp_ledger):
    pal.append_event(source="t", event_type="skill.borrowed", target_profile="octacon",
                     object_type="skill", object_id="arxiv", event_id="b1")
    pal.append_event(source="t", event_type="skill.borrowed", target_profile="remii",
                     object_type="skill", object_id="arxiv", event_id="b2")
    octacon = pal.query_events(event_types=["skill.borrowed"], target_profile="octacon")
    assert [e["event_id"] for e in octacon] == ["b1"]
    by_skill = pal.query_events(object_id="arxiv")
    assert len(by_skill) == 2


def test_borrow_then_count(broker, temp_ledger):
    broker.cmd_borrow("octacon", "arxiv", "t_1", "ops")
    broker.cmd_borrow("octacon", "arxiv", "t_2", "ops")
    rows = pal.query_events(event_types=["skill.borrowed"], target_profile="octacon", object_id="arxiv")
    assert len(rows) == 2


def test_revoke_appends_event_and_reduces_active(broker, temp_ledger):
    eid = broker.cmd_borrow("remii", "maps", "t_9", "ops")
    assert eid not in broker._revoked_borrow_ids()
    rc = broker.cmd_revoke(eid, "completed")
    assert rc == 0
    assert eid in broker._revoked_borrow_ids()
    # append-only: a revoke event exists, the borrow row is untouched
    revokes = pal.query_events(event_types=["skill.revoked"])
    assert any((e["payload"] or {}).get("borrow_event_id") == eid for e in revokes)


def test_never_grant_is_denied(broker, temp_ledger, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["x", "borrow", "octacon", "governance", "t_x", "ops"])
    broker.main()
    denies = pal.query_events(event_types=["skill.denied"], object_id="governance")
    assert len(denies) == 1
    assert "NEVER_GRANT" in (denies[0]["payload"]["recommendation"])


def test_frequency_limit_denies_after_threshold(broker, temp_ledger, monkeypatch):
    # 6 successful borrows already this month -> the next is denied.
    for i in range(6):
        broker.cmd_borrow("octacon", "arxiv", f"t_{i}", "ops")
    monkeypatch.setattr("sys.argv", ["x", "borrow", "octacon", "arxiv", "t_over", "ops"])
    broker.main()
    denies = pal.query_events(event_types=["skill.denied"], object_id="arxiv")
    assert len(denies) == 1
    assert "frequency limit" in denies[0]["payload"]["recommendation"]


def test_revoke_unknown_id_is_rejected(broker, temp_ledger):
    assert broker.cmd_revoke("does-not-exist", "completed") == 1


def test_unique_event_ids_no_grant_loss(broker, temp_ledger):
    ids = {broker.cmd_borrow("octacon", "arxiv", f"t_{i}", "ops") for i in range(20)}
    assert len(ids) == 20  # no collisions -> no silently-dropped grants
    assert len(pal.query_events(event_types=["skill.borrowed"])) == 20


def test_import_legacy_skips_malformed_line(broker, temp_ledger, tmp_path, monkeypatch):
    legacy = tmp_path / "legacy.jsonl"
    legacy.write_text(
        '{"event_id":"l1","skill_borrowed":"arxiv","worker_profile":"octacon","board":"ops","ts":1,"success":true}\n'
        "this-is-not-json\n"
        '{"event_id":"l2","skill_borrowed":"maps","worker_profile":"remii","board":"ops","ts":2,"success":false,"recommendation":"denied: x"}\n'
    )
    monkeypatch.setattr(broker, "LEGACY_JSONL", legacy)
    broker.cmd_import_legacy()
    assert len(pal.query_events(event_types=["skill.borrowed"], object_id="arxiv")) == 1
    assert len(pal.query_events(event_types=["skill.denied"], object_id="maps")) == 1


def test_ledger_is_append_only(temp_ledger):
    import sqlite3
    pal.append_event(source="t", event_type="skill.borrowed", target_profile="octacon",
                     object_type="skill", object_id="arxiv", event_id="b1")
    with pal._connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE activity_events SET summary='x' WHERE event_id='b1'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM activity_events WHERE event_id='b1'")
