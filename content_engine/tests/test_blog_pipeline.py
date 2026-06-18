"""Tests for blog.blog_pipeline — orchestrator + CLI.

run_stream(stream): router.choose -> generator -> gate -> illustrator ->
  assembler -> publisher.stage_draft -> router.record (on success).
run_all(streams): run_stream for each stream.
"""
import os
from pathlib import Path

import blog.blog_pipeline as bpl


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
    monkeypatch.setattr(bpl, "illustrate", lambda d, out_dir=None, max_sections=None: {"hero_path": None, "section_paths": {}})

    # Mock assembler.
    def fake_assemble(d, imgs, repo=None):
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
    # Verify order: assemble -> stage -> record.
    op_names = [c[0] for c in calls]
    assert "assemble" in op_names
    assert "stage" in op_names
    assert "record" in op_names
    assert op_names.index("assemble") < op_names.index("stage")
    assert op_names.index("stage") < op_names.index("record")


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
    bpl.run_stream("ai", repo=str(repo))
    assert record_called == []  # not recorded on failure


def test_run_all_runs_all_streams(monkeypatch, tmp_path):
    """run_all() runs each configured stream and returns per-stream results."""
    repo = _setup_tmp_repo(tmp_path)
    plan = {"topic_id": "t1", "title_hint": "t", "tags": [], "source": "manual",
            "signals": [{"signal_id": "t1", "summary": "s"}]}
    monkeypatch.setattr(bpl, "choose", lambda stream: plan)
    monkeypatch.setattr(bpl, "write_with_gate", lambda p, stream: _DRAFT)
    monkeypatch.setattr(bpl, "illustrate", lambda d, out_dir=None, max_sections=None: {"hero_path": None, "section_paths": {}})
    def fake_assemble(d, imgs, repo=None):
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
                        {"hero_path": None, "section_paths": {}})
    def fake_assemble(d, imgs, repo=None):
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