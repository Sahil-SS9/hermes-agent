"""Strict TDD contract for the bounded foreground SahilBlog runner."""
import json
from pathlib import Path

import pytest


def test_run_once_writes_atomic_state_and_terminal_record(tmp_path):
    from blog.scheduler_runner import run_once

    seen = {}

    def child(*, deadline, max_new_drafts, max_images):
        seen.update(deadline=deadline, max_new_drafts=max_new_drafts, max_images=max_images)
        return {"drafts_created": 1, "images_created": 3}

    result = run_once(
        state_root=tmp_path,
        child_runner=child,
        max_new_drafts=1,
        max_images=3,
        timeout_seconds=10,
    )

    assert result["status"] == "completed"
    assert result["run_id"]
    assert seen["deadline"] > 0
    assert seen["max_new_drafts"] == 1
    assert seen["max_images"] == 3

    state = json.loads((tmp_path / "state.json").read_text())
    assert state["active_run_id"] is None
    assert state["last_run_id"] == result["run_id"]
    run_record = json.loads((tmp_path / "runs" / f"{result['run_id']}.json").read_text())
    assert run_record["status"] == "completed"
    assert run_record["result"] == {"drafts_created": 1, "images_created": 3}
    assert not list(tmp_path.rglob("*.tmp"))


@pytest.mark.parametrize(("max_new_drafts", "max_images"), [(2, 3), (1, 4), (-1, 1), (1, -1)])
def test_run_once_rejects_unbounded_work_before_child_runs(tmp_path, max_new_drafts, max_images):
    from blog.scheduler_runner import run_once

    with pytest.raises(ValueError):
        run_once(
            state_root=tmp_path,
            child_runner=lambda **_: pytest.fail("child must not run"),
            max_new_drafts=max_new_drafts,
            max_images=max_images,
        )


def test_run_once_returns_locked_without_starting_another_child(tmp_path):
    from blog.scheduler_runner import run_once

    def nested_child(**_):
        return run_once(
            state_root=tmp_path,
            child_runner=lambda **__: pytest.fail("second child must not run"),
        )

    result = run_once(state_root=tmp_path, child_runner=nested_child)

    assert result["status"] == "completed"
    assert result["result"] == {"status": "locked", "run_id": None}


def test_run_once_marks_timeout_and_clears_active_run_in_finally(tmp_path):
    from blog.scheduler_runner import run_once

    def timed_out_child(**_):
        raise TimeoutError("deadline exceeded")

    result = run_once(state_root=tmp_path, child_runner=timed_out_child)

    assert result["status"] == "timed_out"
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["active_run_id"] is None
    run_record = json.loads((tmp_path / "runs" / f"{result['run_id']}.json").read_text())
    assert run_record["status"] == "timed_out"


def test_terminal_json_is_stable_compact_and_json_parseable(tmp_path):
    from blog.scheduler_runner import terminal_json

    text = terminal_json({"run_id": "r", "status": "completed", "result": {"b": 2, "a": 1}})

    assert text == '{"result":{"a":1,"b":2},"run_id":"r","status":"completed"}'
    assert json.loads(text)["status"] == "completed"
