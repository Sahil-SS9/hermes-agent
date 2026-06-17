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
