"""Tests for the article_pipeline orchestrator — end-to-end flow.

The pipeline:
  1. router.choose()  -> plan or None
  2. generator.write()  -> draft (or None on LLM dead)
  3. gates.check()  -> GateResult; if fail, retry once with feedback
  4. illustrator.illustrate()  -> illustrated body
  5. assembler.bundle()  -> ArticleBundle on disk
  6. database.insert_draft(content_type='article')  -> DB row
  7. discord_digest.post_article()  -> preview message

All external deps are stubbed; the tests assert the orchestration order
and the no-tech-debt wiring.
"""
import discord_digest as dd
from pathlib import Path
import article_pipeline as ap


def _stub_bundle(d, tmp_path):
    """Return a dd.ArticleBundle-shaped value for tests that stub assemble."""
    return dd.ArticleBundle(
        dir=tmp_path / "bundle", article_md=d["body_md"],
        article_md_path=tmp_path / "bundle" / "article.md",
        image_paths=[], title=d.get("title", "t"), lede=d.get("body_md", "")[:200],
        mode=d.get("mode", "deep_dive"), pillar=d.get("pillar", "h"),
    )


def test_pipeline_runs_router_then_generator_then_gates(monkeypatch, tmp_path):
    """Order: router -> generator -> gates. Short-circuit on router None."""
    calls = []

    def fake_router(state):
        calls.append("router")
        return None
    monkeypatch.setattr(ap, "router_choose", fake_router)
    monkeypatch.setattr(ap, "deliver_preview", lambda *a, **kw: calls.append("deliver"))
    out = ap.run(out_root=tmp_path, deliver=False)
    assert out["status"] in ("skipped_router", "skipped_disabled", "ok")
    assert "router" in calls
    # No draft generated.
    assert "deliver" not in calls


def test_pipeline_skips_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(ap, "ARTICLE_ENABLED", False)
    calls = []
    monkeypatch.setattr(ap, "router_choose", lambda s: calls.append("r") or None)
    out = ap.run(out_root=tmp_path, deliver=False)
    assert out["status"] == "skipped_disabled"
    assert "r" not in calls


def test_pipeline_skips_when_router_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(ap, "router_choose", lambda s: None)
    out = ap.run(out_root=tmp_path, deliver=False)
    assert out["status"] == "skipped_router"


def test_pipeline_happy_path_inserts_draft_with_article_content_type(monkeypatch, tmp_path):
    """The orchestrator persists a drafts row with content_type='article' on success."""
    plan = {"mode": "deep_dive", "signals": [{"signal_id": "x", "signal_type": "harness_change",
            "priority": 8, "summary": "x", "repo": "KenseiAgent", "sha": "abc",
            "variables": {"summary": "x"}}], "pillar": "harness_tuning", "title_hint": "How I tuned routing"}
    draft = {"title": "t", "body_md": "long enough body", "mode": "deep_dive",
             "pillar": "h", "slug": "t", "signals": plan["signals"],
             "context": "ctx", "kb_snippets": []}
    monkeypatch.setattr(ap, "router_choose", lambda s: plan)
    monkeypatch.setattr(ap, "generate_draft", lambda plan, brand: draft)
    monkeypatch.setattr(ap, "gate_draft", lambda d: ("ok", []))
    monkeypatch.setattr(ap, "illustrate", lambda d, out_dir, **kw: d["body_md"])
    monkeypatch.setattr(ap, "assemble", lambda ill, d, out_root, dry_run: _stub_bundle(d, tmp_path))
    inserted = []
    monkeypatch.setattr(ap, "persist_article_draft",
                        lambda **kw: inserted.append(kw) or "draft-id-1")
    monkeypatch.setattr(ap, "deliver_preview", lambda b: None)
    monkeypatch.setattr(ap, "ARTICLE_ENABLED", True)
    out = ap.run(out_root=tmp_path, deliver=True)
    assert out["status"] == "ok"
    assert inserted, "expected persist_article_draft to be called"


def test_pipeline_secret_scan_blocks_persist_and_send(monkeypatch, tmp_path):
    """A planted sk- token is redacted before any DB write or Discord post."""
    plan = {"mode": "deep_dive", "signals": [{"signal_id": "x", "signal_type": "harness_change",
            "priority": 8, "summary": "x", "repo": "KenseiAgent", "sha": "abc",
            "variables": {"summary": "x"}}], "pillar": "harness_tuning", "title_hint": "x"}
    draft = {"title": "t", "body_md": "body", "mode": "deep_dive", "pillar": "h",
             "slug": "t", "signals": [], "context": "context with sk-abc...7890 secret",
             "kb_snippets": []}
    monkeypatch.setattr(ap, "router_choose", lambda s: plan)
    monkeypatch.setattr(ap, "generate_draft", lambda plan, brand: draft)
    sent = []
    monkeypatch.setattr(ap, "gate_draft", lambda d: ("ok", []))
    monkeypatch.setattr(ap, "illustrate", lambda d, out_dir, **kw: d["body_md"])
    monkeypatch.setattr(ap, "assemble",
                        lambda ill, d, out_root, dry_run: _stub_bundle(
                            {**d, "body_md": "body with sk-abc...7890 token"}, tmp_path))
    monkeypatch.setattr(ap, "persist_article_draft", lambda **kw: "draft-id")
    monkeypatch.setattr(ap, "deliver_preview", lambda b: sent.append(b))
    monkeypatch.setattr(ap, "ARTICLE_ENABLED", True)
    ap.run(out_root=tmp_path, deliver=True)
    # The body sent to Discord must have the redaction, not the raw token.
    assert sent, "expected the pipeline to send a bundle"
    sent_body = sent[0].article_md
    assert "sk-abc...7890" not in sent_body
    assert "***REDACTED***" in sent_body


def test_persist_article_draft_inserts_with_article_content_type(monkeypatch, tmp_path):
    """persist_article_draft must pass content_type='article' to db.insert_draft."""
    captured = []
    def fake_insert_draft(**kwargs):
        captured.append(kwargs)
    monkeypatch.setattr(ap.db, "insert_draft", fake_insert_draft)
    ap.persist_article_draft(brand="sahil_twitter", pillar="h", title="T",
                              body_md="body", slop_issues="")
    assert captured, "expected db.insert_draft to be called"
    assert captured[0]["content_type"] == "article"
