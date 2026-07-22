"""RED-first regression tests for the decomposer invalid-tool-call fix.

Covers F001: the decomposer must not permanently strand a triage task on a
single transient malformed-JSON response. It must retry (bounded) against the
SAME configured aux client and only return a structured failure after all
attempts are exhausted. No raw model output may leak into the reason string.

The aux client is mocked — no network calls.
"""
from __future__ import annotations

import json as jsonlib
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_decompose as decomp

# Reuse the `kanban_home` fixture from the sibling decomposer test module
# rather than duplicating it (AGENTS.md: extend, don't duplicate).
from tests.hermes_cli.test_kanban_decompose import kanban_home  # noqa: F401


def _fake_aux_response(content: str):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    return resp


def _fake_client_returns(sequence):
    """Return a client whose create() yields `sequence` items in order."""
    client = MagicMock()
    client.chat.completions.create = MagicMock(side_effect=sequence)
    return client, "test-model"


def _patch_aux_client_obj(client, model="test-model"):
    return patch(
        "agent.auxiliary_client.get_text_auxiliary_client",
        return_value=(client, model),
    )


def _patch_extra_body():
    return patch(
        "agent.auxiliary_client.get_auxiliary_extra_body",
        return_value={},
    )


def _patch_list_profiles(names):
    from types import SimpleNamespace
    fake_profiles = [
        SimpleNamespace(
            name=n, is_default=(i == 0), description=f"desc for {n}",
            description_auto=False, model="m", provider="p", skill_count=1,
        )
        for i, n in enumerate(names)
    ]
    return [
        patch("hermes_cli.profiles.list_profiles", return_value=fake_profiles),
        patch("hermes_cli.profiles.profile_exists", side_effect=lambda x: x in names),
        patch("hermes_cli.profiles.get_active_profile_name", return_value=names[0] if names else "default"),
    ]


# --- Core F001 fix: retry on malformed JSON, succeed on a later attempt ---

def test_retries_on_malformed_json_then_succeeds(kanban_home):
    """Transient prose on attempt 1, valid JSON on attempt 2 -> fanout works."""
    with kb.connect() as conn:
        tid = kb.create_task(conn, title="ship a feature", triage=True)

    good = jsonlib.dumps({
        "fanout": True,
        "rationale": "split",
        "tasks": [{"title": "research", "body": "look", "assignee": "researcher", "parents": []}],
    })
    client, _ = _fake_client_returns([
        _fake_aux_response("sorry, I forgot the JSON"),  # attempt 1 fails
        _fake_aux_response(good),                          # attempt 2 succeeds
    ])

    patches = _patch_list_profiles(["orchestrator", "researcher"])
    for p in patches:
        p.start()
    try:
        with _patch_aux_client_obj(client), _patch_extra_body():
            outcome = decomp.decompose_task(tid, author="me")
    finally:
        for p in patches:
            p.stop()

    assert outcome.ok, outcome.reason
    assert outcome.fanout is True
    assert outcome.child_ids is not None
    assert len(outcome.child_ids) == 1


def test_retries_on_empty_content_then_succeeds(kanban_home):
    with kb.connect() as conn:
        tid = kb.create_task(conn, title="x", triage=True)

    good = jsonlib.dumps({
        "fanout": False, "rationale": "one", "title": "T", "body": "B", "assignee": "researcher",
    })
    client, _ = _fake_client_returns([
        _fake_aux_response(""),        # attempt 1: empty
        _fake_aux_response(good),      # attempt 2: valid
    ])
    patches = _patch_list_profiles(["orchestrator", "researcher"])
    for p in patches:
        p.start()
    try:
        with _patch_aux_client_obj(client), _patch_extra_body(), patch(
            "hermes_cli.kanban_decompose._load_config",
            return_value={"kanban": {"default_assignee": "researcher"}},
        ):
            outcome = decomp.decompose_task(tid, author="me")
    finally:
        for p in patches:
            p.stop()
    assert outcome.ok, outcome.reason


def test_gives_up_structured_after_all_attempts(kanban_home):
    """All attempts malformed -> structured 'failed after N attempts' reason, task unchanged."""
    with kb.connect() as conn:
        tid = kb.create_task(conn, title="x", triage=True)

    client, _ = _fake_client_returns([
        _fake_aux_response("not json 1"),
        _fake_aux_response("not json 2"),
        _fake_aux_response("not json 3"),
    ])
    patches = _patch_list_profiles(["orchestrator"])
    for p in patches:
        p.start()
    try:
        with _patch_aux_client_obj(client), _patch_extra_body():
            outcome = decomp.decompose_task(tid, author="me")
    finally:
        for p in patches:
            p.stop()

    assert outcome.ok is False
    assert "attempts" in outcome.reason
    assert "malformed" in outcome.reason
    # No raw model output ("not json 3") must leak into the reason.
    assert "not json" not in outcome.reason
    # Task must still be in triage (not silently mutated / stranded differently).
    with kb.connect() as conn:
        task = kb.get_task(conn, tid)
    assert task is not None
    assert task.status == "triage"


def test_no_raw_output_leaks_on_api_error(kanban_home):
    """API exception path must not embed raw content; reason names only the exception class."""
    with kb.connect() as conn:
        tid = kb.create_task(conn, title="x", triage=True)

    client = MagicMock()
    client.chat.completions.create = MagicMock(
        side_effect=[RuntimeError("SECRET-RAW-TOKEN-12345") for _ in range(3)]
    )
    patches = _patch_list_profiles(["orchestrator"])
    for p in patches:
        p.start()
    try:
        with _patch_aux_client_obj(client), _patch_extra_body():
            outcome = decomp.decompose_task(tid, author="me")
    finally:
        for p in patches:
            p.stop()

    assert outcome.ok is False
    assert "SECRET-RAW-TOKEN" not in outcome.reason  # never leaks raw error text
    assert "RuntimeError" in outcome.reason
    assert "attempts" in outcome.reason


def test_single_success_first_try_is_not_wasteful(kanban_home):
    """Happy path: first attempt valid -> exactly one create() call."""
    with kb.connect() as conn:
        tid = kb.create_task(conn, title="x", triage=True)
    good = jsonlib.dumps({
        "fanout": False, "rationale": "one", "title": "T", "body": "B", "assignee": "researcher",
    })
    client, _ = _fake_client_returns([_fake_aux_response(good)])
    patches = _patch_list_profiles(["orchestrator", "researcher"])
    for p in patches:
        p.start()
    try:
        with _patch_aux_client_obj(client), _patch_extra_body(), patch(
            "hermes_cli.kanban_decompose._load_config",
            return_value={"kanban": {"default_assignee": "researcher"}},
        ):
            outcome = decomp.decompose_task(tid, author="me")
    finally:
        for p in patches:
            p.stop()
    assert outcome.ok, outcome.reason
    assert client.chat.completions.create.call_count == 1
