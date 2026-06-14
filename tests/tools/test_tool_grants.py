"""Phase 4: tool grant engine + tool_request tool.

Covers grant_tool safety gates, task-completion revocation, and the
tool_request tool's registry-existence guard. Mirrors
tests/tools/test_skill_grants_engine.py. Isolated to a temp ledger.
"""
import time

import pytest

from hermes_cli import profile_activity_ledger as pal
import tools.tool_grants as tg
import tools.skills_tool as st


@pytest.fixture
def temp_ledger(tmp_path, monkeypatch):
    db = tmp_path / "ledger.sqlite"
    monkeypatch.setattr(pal, "ledger_db_path", lambda: db)
    monkeypatch.setattr(pal, "_governance_root", lambda: tmp_path)
    return db


def test_grant_safe_tool(temp_ledger):
    d = tg.grant_tool("octacon", "web_search", "t_1", "need to look something up")
    assert d["granted"] is True and d["decision"] == "grant_task_only"
    assert tg.has_active_grant("octacon", "web_search") is True


def test_grant_requires_task_id(temp_ledger):
    d = tg.grant_tool("octacon", "web_search", "", "no task")
    assert d["granted"] is False and "task_id" in d["reason"]
    assert tg.has_active_grant("octacon", "web_search") is False


def test_never_grant_curated_name_denied(temp_ledger):
    d = tg.grant_tool("octacon", "kanban_profile_edit", "t_1")
    assert d["granted"] is False
    assert "NEVER_GRANT" in d["reason"]
    assert tg.has_active_grant("octacon", "kanban_profile_edit") is False


def test_never_grant_terminal_toolset_denied(temp_ledger):
    d = tg.grant_tool("octacon", "terminal", "t_1")
    assert d["granted"] is False
    assert "NEVER_GRANT" in d["reason"]
    assert tg.has_active_grant("octacon", "terminal") is False


def test_never_grant_process_denied(temp_ledger):
    # process (the other terminal-toolset tool) must be denied via the
    # hardcoded floor even if toolset resolution is unavailable.
    d = tg.grant_tool("octacon", "process", "t_1")
    assert d["granted"] is False
    assert "NEVER_GRANT" in d["reason"]


def test_never_grant_floor_holds_without_toolset_resolution(temp_ledger, monkeypatch):
    # Simulate toolsets import/resolution failure: the floor must still deny
    # arbitrary command execution.
    monkeypatch.setattr(tg, "_effective_never_grant", lambda: set(tg.NEVER_GRANT_TOOLS))
    d = tg.grant_tool("octacon", "terminal", "t_1")
    assert d["granted"] is False
    assert "NEVER_GRANT" in d["reason"]


def test_unknown_tool_denied(temp_ledger):
    d = tg.grant_tool("octacon", "this_tool_does_not_exist", "t_1")
    assert d["granted"] is False
    assert "not a registered tool" in d["reason"]


def test_frequency_cap_denies(temp_ledger):
    for i in range(tg.FREQUENCY_LIMIT):
        tg.grant_tool("octacon", "web_search", f"t_{i}")
    d = tg.grant_tool("octacon", "web_search", "t_over")
    assert d["granted"] is False and "frequency" in d["reason"]


def test_revoke_grants_for_task(temp_ledger):
    tg.grant_tool("octacon", "web_search", "t_done")
    tg.grant_tool("octacon", "web_extract", "t_done")
    tg.grant_tool("octacon", "memory", "t_other")
    n = tg.revoke_grants_for_task("t_done", "completed")
    assert n == 2
    assert tg.has_active_grant("octacon", "web_search") is False
    assert tg.has_active_grant("octacon", "web_extract") is False
    # a grant on a different task is untouched
    assert tg.has_active_grant("octacon", "memory") is True


def test_ttl_sweep_revokes_old_grants(temp_ledger, monkeypatch):
    old = int(time.time() - 48 * 3600)
    pal.append_event(source="t", event_type="tool.borrowed", target_profile="remii",
                     object_type="tool", object_id="web_search", event_id="old1",
                     occurred_at=old, payload={"task_id": "t_x"})
    tg.grant_tool("remii", "memory", "t_y")  # fresh, must survive
    revoked = tg.sweep_expired_grants(ttl_hours=24)
    assert revoked == 1
    assert tg.has_active_grant("remii", "web_search") is False
    assert tg.has_active_grant("remii", "memory") is True


def test_revoke_by_event_id(temp_ledger):
    d = tg.grant_tool("octacon", "web_search", "t_1")
    res = tg.revoke_by_event_id(d["event_id"])
    assert res["status"] == "revoked"
    assert tg.revoke_by_event_id("nope").get("error")


def test_tool_request_rejects_unknown_tool(temp_ledger, monkeypatch):
    monkeypatch.setattr(st, "_current_profile", lambda: "octacon")
    import json

    out = json.loads(st.tool_request("this_tool_does_not_exist", "t_1", "because"))
    assert out["success"] is True  # the helper itself didn't error
    assert out["granted"] is False
    assert "not a registered tool" in out["reason"]


def test_tool_request_grants_existing_tool(temp_ledger, monkeypatch):
    monkeypatch.setattr(st, "_current_profile", lambda: "octacon")
    import json

    out = json.loads(st.tool_request("web_search", "t_1", "need it"))
    assert out["success"] is True and out["granted"] is True
    assert tg.has_active_grant("octacon", "web_search") is True
