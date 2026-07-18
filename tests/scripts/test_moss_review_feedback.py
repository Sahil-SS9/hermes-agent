"""TDD contract for the Mossy read-only review-feedback loop.

All data is fixture JSON and all writes are redirected to temporary HERMES_HOME.
No test invokes GitHub or a real git mutation.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "scripts" / "moss_review_feedback.py"
WATCH_PATH = REPO / "scripts" / "moss-review-feedback-watch.py"
CONTEXT_PATH = REPO / "scripts" / "moss-review-feedback-context.py"
FIXTURE = REPO / "tests" / "fixtures" / "moss_review_feedback.json"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


@pytest.fixture
def feedback():
    return json.loads(FIXTURE.read_text())


def test_normalise_all_review_surfaces_rejects_self_and_bot_authors(feedback):
    mod = load_module(MODULE_PATH, "moss_review_feedback_normalise")

    records = mod.normalise_feedback(feedback)

    assert [(r["surface"], r["key"], r["author"]) for r in records] == [
        ("review", "review:NousResearch/hermes-agent#42:R-1", "alice"),
        ("inline", "inline:NousResearch/hermes-agent#42:I-1", "bob"),
        ("conversation", "conversation:NousResearch/hermes-agent#42:C-1", "carol"),
        ("conversation", "conversation:NousResearch/hermes-agent#42:C-2", "Teknium"),
    ]
    assert records[1]["path"] == "scripts/watcher.py"


@pytest.mark.parametrize(
    ("author", "body", "surface", "expected"),
    [
        ("alice", "Please add a regression test.", "inline", "routine_patch"),
        ("alice", "Thanks, this looks good.", "conversation", "reply_only"),
        ("alice", "Can you clarify why this is safe?", "conversation", "clarification"),
        ("alice", "This may cause data loss in production.", "review", "sahil_escalation"),
        # Teknium has priority, but still receives the same safety classification.
        ("Teknium", "nit: typo", "inline", "routine_patch"),
    ],
)
def test_classifier_matrix_reviews_teknium_without_a_blind_bypass(author, body, surface, expected):
    mod = load_module(MODULE_PATH, "moss_review_feedback_classifier")

    assert mod.classify_feedback({"author": author, "body": body, "surface": surface}) == expected


def test_atomic_paths_are_distinct_and_dedupe_is_namespaced(fake_home, feedback):
    mod = load_module(MODULE_PATH, "moss_review_feedback_paths")
    paths = mod.feedback_paths()
    assert len(set(paths.values())) == len(paths)

    records = mod.normalise_feedback(feedback)
    state = mod.load_json(paths["state"], {"seen": []})
    new_records = mod.dedupe_records(records, state)
    mod.atomic_write_json(paths["state"], {"seen": [r["key"] for r in new_records]})
    mod.atomic_write_json(paths["queue"], {"pending": new_records})
    mod.atomic_write_json(paths["ledger"], {"events": []})
    mod.atomic_write_json(paths["rules"], {"rules": []})

    assert mod.dedupe_records(records, mod.load_json(paths["state"], {})) == []
    assert {p.name for p in paths.values()} == {
        "moss-review-feedback-state.json", "moss-review-feedback-queue.json",
        "moss-review-feedback-ledger.json", "moss-review-feedback-rules.json",
    }
    assert not list(paths["state"].parent.glob("*.tmp"))


def test_promotion_rule_selection_and_pre_push_report(fake_home, feedback):
    mod = load_module(MODULE_PATH, "moss_review_feedback_promotion")
    records = mod.normalise_feedback(feedback)
    # Add a non-maintainer question so the report covers every matrix bucket.
    # Teknium's question is also a clarification: priority never bypasses review.
    classified = mod.classify_records(records + [{
        "author": "alice", "body": "Can you clarify why this is safe?", "surface": "conversation"
    }])
    promoted = mod.promote_records(classified)
    report = mod.build_pre_push_report(classified, promoted, {"routine_patch": "tests-first"})

    # The formal review and inline review are independently namespaced and
    # therefore both remain actionable routine patches.
    assert [r["classification"] for r in promoted] == ["routine_patch", "routine_patch"]
    assert report["blocked"] is False
    assert report["rule_selection"]["routine_patch"] == "tests-first"
    assert report["counts"] == {"routine_patch": 2, "reply_only": 1, "clarification": 2}


def test_dry_run_runner_denies_mutating_gh_and_git_commands():
    mod = load_module(MODULE_PATH, "moss_review_feedback_runner")
    invoked = []

    def runner(command, **kwargs):
        invoked.append(command)
        return "executed"

    assert mod.run_read_only(["gh", "pr", "comment", "42", "--body", "no"], runner=runner)["status"] == "denied"
    assert mod.run_read_only(["git", "push", "origin", "main"], runner=runner)["status"] == "denied"
    assert mod.run_read_only(["gh", "pr", "view", "42"], runner=runner)["status"] == "dry_run"
    assert invoked == []


def test_watch_and_context_scripts_use_fixture_only_paths(fake_home, feedback):
    watch = load_module(WATCH_PATH, "moss_review_feedback_watch")
    context = load_module(CONTEXT_PATH, "moss_review_feedback_context")

    result = watch.process_fixture(feedback)
    report = context.render_context(result["classified"], result["promoted"])

    assert result["new_count"] == 4
    assert "Mossy review feedback" in report
    assert "Teknium" in report
