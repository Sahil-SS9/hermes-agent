"""Tests for blog.blog_pipeline — orchestrator + CLI.

run_stream(stream): router.choose -> generator -> gate -> illustrator ->
  assembler -> publisher.stage_draft -> router.record (on success).
run_all(streams): run_stream for each stream.
"""
import os
from pathlib import Path

import blog.blog_pipeline as bpl
import pytest


@pytest.fixture(autouse=True)
def no_real_approval_tracker(monkeypatch):
    monkeypatch.setattr(bpl, "_maybe_request_approval", lambda *args, **kwargs: None)


_DRAFT = {
    "title": "Token-Maxing at the Edge",
    "description": "A counterintuitive claim.",
    "body_md": "# Token-Maxing at the Edge\n\nLede\n\n## The mechanism\n\nText.\n\n## Worked example\n\nCode.\n\n## What I'd try next\n\nTakeaway.",
    "slug": "token-maxing-at-the-edge",
    "tier": "pm",
    "tags": ["ai"],
    "format": "essay",
    "source": "research-paper",
    "stream": "ai",
    "signals": [{"signal_id": "t1", "summary": "token-maxing"}],
    "context": "",
    "kb_snippets": [],
}


def _setup_tmp_repo(tmp_path):
    """Create a tmp SahilBlog repo skeleton with git init."""
    import subprocess
    (tmp_path / "src/content/blog").mkdir(parents=True)
    (tmp_path / "public/blog").mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True)
    (tmp_path / "README.md").write_text("# repo\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
    return tmp_path


def test_run_stream_happy_path(monkeypatch, tmp_path):
    """Full happy path: one staged draft per stream, topic recorded on success."""
    repo = _setup_tmp_repo(tmp_path)
    calls = []

    # Mock router.choose.
    plan = {"topic_id": "t1", "title_hint": "token-maxing", "tags": ["ai-adoption"],
            "source": "research-paper",
            "signals": [{"signal_id": "t1", "summary": "token-maxing"}]}
    monkeypatch.setattr(bpl, "choose", lambda stream: plan)

    # Mock generator.
    monkeypatch.setattr(bpl, "write_with_gate", lambda p, stream: _DRAFT)

    # Mock illustrator.
    monkeypatch.setattr(bpl, "illustrate", lambda d, out_dir=None, max_sections=None: {"hero_path": "/tmp/fake_hero.png", "section_paths": {}})

    # Mock assembler.
    def fake_assemble(d, imgs, repo=None, pub_date=None):
        p = Path(repo) / "src/content/blog" / f"{d['slug']}.mdx"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\ntitle: \"t\"\n---\nbody")
        calls.append(("assemble", d["slug"]))
        return p
    monkeypatch.setattr(bpl, "assemble", fake_assemble)

    # Mock publisher.
    monkeypatch.setattr(bpl, "stage_draft", lambda mdx, repo=None: calls.append(("stage", mdx)) or "ai")

    # Mock router.record.
    monkeypatch.setattr(bpl, "record", lambda stream, tid, title: calls.append(("record", stream, tid)))

    result = bpl.run_stream("ai", repo=str(repo))
    assert result["status"] == "ok"
    # Now record is called pre-emptively (before assemble) and also on success.
    op_names = [c[0] for c in calls]
    assert "record" in op_names  # called pre-emptively after choose()
    assert "assemble" in op_names
    assert "stage" in op_names
    assert op_names.index("assemble") < op_names.index("stage")


def test_run_stream_skips_when_router_returns_none(monkeypatch, tmp_path):
    """When the router returns None, run_stream skips."""
    repo = _setup_tmp_repo(tmp_path)
    monkeypatch.setattr(bpl, "choose", lambda stream: None)
    result = bpl.run_stream("ai", repo=str(repo))
    assert result["status"] == "skipped_router"


def test_run_stream_skips_when_generator_returns_none(monkeypatch, tmp_path):
    """When the generator returns None (LLM dead), run_stream skips."""
    repo = _setup_tmp_repo(tmp_path)
    plan = {"topic_id": "t1", "title_hint": "t", "tags": [], "source": "manual",
            "signals": [{"signal_id": "t1", "summary": "s"}]}
    monkeypatch.setattr(bpl, "choose", lambda stream: plan)
    monkeypatch.setattr(bpl, "write_with_gate", lambda p, stream: None)
    result = bpl.run_stream("ai", repo=str(repo))
    assert result["status"] == "skipped_generator"


def test_run_stream_does_not_record_on_generator_failure(monkeypatch, tmp_path):
    """router.record is NOT called when the generator fails."""
    repo = _setup_tmp_repo(tmp_path)
    plan = {"topic_id": "t1", "title_hint": "t", "tags": [], "source": "manual",
            "signals": [{"signal_id": "t1", "summary": "s"}]}
    monkeypatch.setattr(bpl, "choose", lambda stream: plan)
    monkeypatch.setattr(bpl, "write_with_gate", lambda p, stream: None)
    record_called = []
    monkeypatch.setattr(bpl, "record", lambda s, tid, t: record_called.append(tid))
    reserve_called = []
    release_called = []
    monkeypatch.setattr(bpl, "reserve", lambda s, tid, title: reserve_called.append(tid) or "tok")
    monkeypatch.setattr(bpl, "release", lambda token: release_called.append(token))

    bpl.run_stream("ai", repo=str(repo))
    # Failed generations release the temporary reservation and do not burn the
    # topic into permanent usage.
    assert reserve_called == ["t1"]
    assert release_called == ["tok"]
    assert record_called == []


def test_run_all_runs_all_streams(monkeypatch, tmp_path):
    """run_all() runs each configured stream and returns per-stream results."""
    repo = _setup_tmp_repo(tmp_path)
    plan = {"topic_id": "t1", "title_hint": "t", "tags": [], "source": "manual",
            "signals": [{"signal_id": "t1", "summary": "s"}]}
    monkeypatch.setattr(bpl, "choose", lambda stream: plan)
    monkeypatch.setattr(bpl, "write_with_gate", lambda p, stream: _DRAFT)
    monkeypatch.setattr(bpl, "illustrate", lambda d, out_dir=None, max_sections=None: {"hero_path": "/tmp/fake_hero.png", "section_paths": {}})
    def fake_assemble(d, imgs, repo=None, pub_date=None):
        p = Path(repo) / "src/content/blog" / f"{d['slug']}.mdx"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\ntitle: \"t\"\n---\nbody")
        return p
    monkeypatch.setattr(bpl, "assemble", fake_assemble)
    monkeypatch.setattr(bpl, "stage_draft", lambda mdx, repo=None: "slug")
    monkeypatch.setattr(bpl, "record", lambda s, tid, t: None)
    result = bpl.run_all(streams=("ai", "pm", "builder"), repo=str(repo))
    assert result["status"] == "ok"
    assert "ai" in result["results"]
    assert "pm" in result["results"]
    assert "builder" in result["results"]


def test_run_stream_skipped_when_disabled(monkeypatch, tmp_path):
    """When BLOG_ENABLED is False, run_stream skips."""
    repo = _setup_tmp_repo(tmp_path)
    monkeypatch.setattr(bpl, "BLOG_ENABLED", False)
    result = bpl.run_stream("ai", repo=str(repo))
    assert result["status"] == "skipped_disabled"


def test_run_stream_graceful_when_reviewer_degraded(monkeypatch, tmp_path):
    """Daily pipeline (strict_review=False default) still produces a draft
    when the editorial reviewer degrades. The reviewer LLM returning None
    must not block the daily path."""
    repo = _setup_tmp_repo(tmp_path)
    plan = {"topic_id": "t1", "title_hint": "t", "tags": [], "source": "manual",
            "signals": [{"signal_id": "t1", "summary": "s"}]}
    monkeypatch.setattr(bpl, "choose", lambda stream: plan)

    # write_with_gate in non-strict mode returns a draft even when the
    # reviewer degrades. Mock it to simulate that path.
    monkeypatch.setattr(bpl, "write_with_gate", lambda p, stream: _DRAFT)
    monkeypatch.setattr(bpl, "illustrate",
                        lambda d, out_dir=None, max_sections=None:
                        {"hero_path": "/tmp/fake_hero.png", "section_paths": {}})
    def fake_assemble(d, imgs, repo=None, pub_date=None):
        p = Path(repo) / "src/content/blog" / f"{d['slug']}.mdx"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\ntitle: \"t\"\n---\nbody")
        return p
    monkeypatch.setattr(bpl, "assemble", fake_assemble)
    monkeypatch.setattr(bpl, "stage_draft", lambda mdx, repo=None: "slug")
    monkeypatch.setattr(bpl, "record", lambda s, tid, t: None)

    result = bpl.run_stream("ai", repo=str(repo))
    assert result["status"] == "ok", \
        "daily pipeline must stage draft even when reviewer degrades"

# -- Failed-image handling tests -----------------------------------------------

def test_run_stream_failed_images_status(monkeypatch, tmp_path):
    """When all images fail (hero AND sections None), status is failed_images."""
    repo = _setup_tmp_repo(tmp_path)
    plan = {"topic_id": "t1", "title_hint": "t", "tags": [], "source": "manual",
            "signals": [{"signal_id": "t1", "summary": "s"}]}
    monkeypatch.setattr(bpl, "choose", lambda stream: plan)
    monkeypatch.setattr(bpl, "write_with_gate", lambda p, stream: _DRAFT)
    # All images fail.
    monkeypatch.setattr(bpl, "illustrate",
                        lambda d, out_dir=None, max_sections=None:
                        {"hero_path": None, "section_paths": {}})
    # Redirect tracking file to tmp.
    monkeypatch.setattr(bpl, "FAILED_IMAGES_PATH", tmp_path / "failed_images.jsonl")

    result = bpl.run_stream("ai", repo=str(repo))
    assert result["status"] == "failed_images"
    assert result["slug"] == _DRAFT["slug"]


def test_run_stream_partial_images_proceeds(monkeypatch, tmp_path):
    """When hero succeeds but sections fail, pipeline proceeds (partial imagery)."""
    repo = _setup_tmp_repo(tmp_path)
    plan = {"topic_id": "t1", "title_hint": "t", "tags": [], "source": "manual",
            "signals": [{"signal_id": "t1", "summary": "s"}]}
    monkeypatch.setattr(bpl, "choose", lambda stream: plan)
    monkeypatch.setattr(bpl, "write_with_gate", lambda p, stream: _DRAFT)
    # Hero succeeds, sections all fail.
    monkeypatch.setattr(bpl, "illustrate",
                        lambda d, out_dir=None, max_sections=None:
                        {"hero_path": "/tmp/fake_hero.png", "section_paths": {}})
    def fake_assemble(d, imgs, repo=None, pub_date=None):
        p = Path(repo) / "src/content/blog" / f"{d['slug']}.mdx"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\ntitle: \"t\"\n---\nbody")
        return p
    monkeypatch.setattr(bpl, "assemble", fake_assemble)
    monkeypatch.setattr(bpl, "stage_draft", lambda mdx, repo=None: "slug")
    monkeypatch.setattr(bpl, "record", lambda s, tid, t: None)
    monkeypatch.setattr(bpl, "FAILED_IMAGES_PATH", tmp_path / "failed_images.jsonl")

    result = bpl.run_stream("ai", repo=str(repo))
    assert result["status"] == "ok"


def test_failed_image_tracking_creates_jsonl(monkeypatch, tmp_path):
    """_track_failed_image creates the JSONL file and writes a valid entry."""
    monkeypatch.setattr(bpl, "FAILED_IMAGES_PATH", tmp_path / "failed_images.jsonl")
    bpl._track_failed_image("test-slug", "ai", "timeout")
    assert (tmp_path / "failed_images.jsonl").exists()
    import json
    entries = [json.loads(l) for l in (tmp_path / "failed_images.jsonl").read_text().splitlines() if l.strip()]
    assert len(entries) == 1
    assert entries[0]["slug"] == "test-slug"
    assert entries[0]["stream"] == "ai"
    assert entries[0]["last_error"] == "timeout"
    assert entries[0]["attempts"] == 1


def test_failed_image_tracking_increments_attempts(monkeypatch, tmp_path):
    """_track_failed_image increments attempts for existing slugs."""
    monkeypatch.setattr(bpl, "FAILED_IMAGES_PATH", tmp_path / "failed_images.jsonl")
    bpl._track_failed_image("test-slug", "ai", "error1")
    bpl._track_failed_image("test-slug", "ai", "error2")
    import json
    entries = [json.loads(l) for l in (tmp_path / "failed_images.jsonl").read_text().splitlines() if l.strip()]
    assert len(entries) == 1
    assert entries[0]["attempts"] == 2
    assert entries[0]["last_error"] == "error2"


def test_remove_from_failed(monkeypatch, tmp_path):
    """_remove_from_failed removes a slug from the tracking file."""
    monkeypatch.setattr(bpl, "FAILED_IMAGES_PATH", tmp_path / "failed_images.jsonl")
    bpl._track_failed_image("slug-a", "ai", "err")
    bpl._track_failed_image("slug-b", "pm", "err")
    bpl._remove_from_failed("slug-a")
    import json
    entries = [json.loads(l) for l in (tmp_path / "failed_images.jsonl").read_text().splitlines() if l.strip()]
    assert len(entries) == 1
    assert entries[0]["slug"] == "slug-b"


def test_stale_failed_images_flags_old_entries(monkeypatch, tmp_path):
    """Entries older than the stale threshold are flagged."""
    monkeypatch.setattr(bpl, "FAILED_IMAGES_PATH", tmp_path / "failed_images.jsonl")
    import json
    from datetime import date, timedelta
    # Write an old entry (10 days ago).
    old_date = (date.today() - timedelta(days=10)).isoformat()
    entry = {"slug": "old-slug", "stream": "ai", "date": old_date,
             "attempts": 3, "last_error": "err", "first_failure": old_date}
    (tmp_path / "failed_images.jsonl").write_text(json.dumps(entry) + "\n")
    # Write a recent entry (1 day ago).
    recent_date = (date.today() - timedelta(days=1)).isoformat()
    entry2 = {"slug": "recent-slug", "stream": "pm", "date": recent_date,
              "attempts": 1, "last_error": "err", "first_failure": recent_date}
    with open(tmp_path / "failed_images.jsonl", "a") as f:
        f.write(json.dumps(entry2) + "\n")

    stale = bpl.get_stale_failed_images()
    assert len(stale) == 1
    assert stale[0]["slug"] == "old-slug"

