import json
import sqlite3

import pytest


def test_append_event_creates_sqlite_row_and_jsonl_mirror(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profiles" / "octacon"))

    from hermes_cli.profile_activity_ledger import append_event, ledger_db_path, ledger_jsonl_dir

    event_id = append_event(
        source="test",
        actor_profile="octacon",
        target_profile="default",
        event_type="skill.loaded",
        object_type="skill",
        object_id="kanban-worker",
        payload={"via": "unit-test"},
    )

    db_path = ledger_db_path()
    assert db_path == tmp_path / "governance" / "profile-activity-ledger.sqlite"
    assert db_path.exists()

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT event_id, source, actor_profile, target_profile, event_type, object_type, object_id, payload_json FROM activity_events"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][:7] == (
        event_id,
        "test",
        "octacon",
        "default",
        "skill.loaded",
        "skill",
        "kanban-worker",
    )
    assert json.loads(rows[0][7]) == {"via": "unit-test"}

    mirror_files = sorted(ledger_jsonl_dir().glob("*.jsonl"))
    assert len(mirror_files) == 1
    mirror = [json.loads(line) for line in mirror_files[0].read_text().splitlines()]
    assert mirror[0]["event_id"] == event_id
    assert mirror[0]["event_type"] == "skill.loaded"


def test_append_event_is_idempotent_by_event_id_and_mirrors_once(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from hermes_cli.profile_activity_ledger import append_event, ledger_db_path, ledger_jsonl_dir

    first = append_event(
        event_id="evt-fixed",
        source="test",
        event_type="kanban.task.created",
        object_type="kanban_task",
        object_id="t_123",
        payload={"n": 1},
    )
    second = append_event(
        event_id="evt-fixed",
        source="test",
        event_type="kanban.task.created",
        object_type="kanban_task",
        object_id="t_123",
        payload={"n": 2},
    )

    assert first == second == "evt-fixed"
    with sqlite3.connect(ledger_db_path()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM activity_events").fetchone()[0] == 1
        payload = conn.execute("SELECT payload_json FROM activity_events").fetchone()[0]
    assert json.loads(payload) == {"n": 1}

    mirror_lines = []
    for mirror_file in ledger_jsonl_dir().glob("*.jsonl"):
        mirror_lines.extend(mirror_file.read_text().splitlines())
    assert len(mirror_lines) == 1


def test_activity_events_are_append_only(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from hermes_cli.profile_activity_ledger import append_event, ledger_db_path

    append_event(
        event_id="evt-append-only",
        source="test",
        event_type="gateway.message.received",
        object_type="gateway_message",
        object_id="m_1",
    )

    with sqlite3.connect(ledger_db_path()) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE activity_events SET source = 'mutated'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM activity_events")


def test_feature_flag_defaults_false_and_reads_nested_config(monkeypatch):
    from hermes_cli import profile_activity_ledger as pal

    monkeypatch.setattr(pal, "load_config", lambda: {})
    assert pal.is_enabled() is False

    monkeypatch.setattr(
        pal,
        "load_config",
        lambda: {"governance": {"profile_activity_ledger": {"enabled": True}}},
    )
    assert pal.is_enabled() is True


def test_record_event_if_enabled_is_noop_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from hermes_cli import profile_activity_ledger as pal

    monkeypatch.setattr(pal, "is_enabled", lambda cfg=None: False)
    assert pal.record_event_if_enabled(source="test", event_type="noop") is None
    assert not pal.ledger_db_path().exists()
