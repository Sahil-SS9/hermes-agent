"""Tests for blog backfill — stream config, budget cap, idempotency."""

import blog.blog_streams as bs


def test_streams_have_structural_rules():
    """Each stream must carry a 'structure' key with per-stream rules."""
    for s in ("ai", "pm", "builder"):
        assert bs.STREAMS[s].get("structure"), f"{s}: structure rule required"
    assert "reflective" in bs.STREAMS["pm"]["structure"].lower()
    assert "hype" in bs.STREAMS["builder"]["structure"].lower() or \
           "reality" in bs.STREAMS["builder"]["structure"].lower()
    assert "verify" in bs.STREAMS["ai"]["structure"].lower()


def test_blog_image_model_is_nano_banana_2():
    """Config should point to nano-banana-2 with a positive backfill cap."""
    import config as cfg
    assert cfg.BLOG_IMAGE_MODEL == "fal-ai/nano-banana-2/edit"
    assert cfg.BACKFILL_SPEND_CAP_GBP > 0


def test_backfill_topics_have_correct_counts():
    """Each stream has exactly 12 approved topics."""
    from blog.backfill_topics import TOPICS
    for stream in ("ai", "pm", "builder"):
        assert len(TOPICS[stream]) == 12, f"{stream}: expected 12 topics, got {len(TOPICS[stream])}"


def test_backfill_verification_topics_have_claims():
    """needs_verification=True topics must carry a claim string."""
    from blog.backfill_topics import TOPICS
    for stream, topics in TOPICS.items():
        for t in topics:
            if t.get("needs_verification"):
                assert t.get("claim"), f"{stream}/{t['title']}: needs_verification but no claim"


def test_backfill_skips_existing_and_respects_cap(monkeypatch, tmp_path):
    """Backfill skips topics whose MDX already exists and stops at cap."""
    import blog.backfill as bf
    import budget as bgt
    import config as cfg

    # Set up a minimal SahilBlog repo structure.
    repo = tmp_path / "SahilBlog"
    posts_dir = repo / "src/content/blog"
    posts_dir.mkdir(parents=True)

    # Pre-create one MDX so the first topic is skipped.
    (posts_dir / "why-context-is-the-bottleneck-not-model-size.mdx").write_text("existing")

    monkeypatch.setattr(cfg, "SAHILBLOG_REPO", str(repo))
    monkeypatch.setattr(cfg, "BACKFILL_SPEND_CAP_GBP", 0.2)  # low cap

    # Mock write_with_gate to return a fake draft.
    def fake_write(plan, stream="ai", **kw):
        return {
            "title": plan.get("title_hint", "Post").split(":")[0].strip(),
            "description": "A test draft",
            "body_md": "# Test\n\nLede.\n\n## Section one\n\nContent.\n\n## Section two\n\nMore.\n\n## Takeaway\n\nDone.",
            "slug": "test-post",
            "tier": "pm",
            "tags": ["test"],
            "format": "essay",
            "source": "manual",
            "stream": stream,
            "signals": [{"summary": "test signal"}],
            "context": "",
            "kb_snippets": [],
        }
    monkeypatch.setattr(bf, "write_with_gate", fake_write)

    # Mock illustrate to return fake paths.
    def fake_illustrate(draft, max_sections=0, **kw):
        out = {"hero_path": None, "section_paths": {}}
        if max_sections > 0:
            hero = tmp_path / "hero.png"
            hero.write_text("x")
            out["hero_path"] = str(hero)
        for i in range(max_sections):
            sec = tmp_path / f"sec{i}.png"
            sec.write_text("x")
            out["section_paths"][f"Section {i}"] = str(sec)
        return out
    monkeypatch.setattr(bf, "illustrate", fake_illustrate)

    # Reset budget for the test.
    from pathlib import Path
    ledger = Path(bgt._LEDGER)
    if ledger.exists():
        ledger.unlink()

    # Run with a limit of 3 (should generate ~3 but cap stops earlier).
    result = bf.run(stream="ai", limit=5)
    # First topic skipped (exists), subsequent generate until cap hit.
    assert result["skipped"] >= 1
    # Total images generated should be limited by the cap.
    assert result["total_spend_gbp"] <= cfg.BACKFILL_SPEND_CAP_GBP + 0.01, \
        f"spend {result['total_spend_gbp']} exceeded cap {cfg.BACKFILL_SPEND_CAP_GBP}"
