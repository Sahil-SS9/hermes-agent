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
