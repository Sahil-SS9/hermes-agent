"""Tests for blog.blog_illustrator — hero + per-section images via transplant.

Reuses imagery_transplant.generate (the validated nano-banana-pro/edit
dual-anchor transplant). One hero + up to BLOG_MAX_SECTION_IMAGES per-section
images. Budget-gated via budget.can_spend.
"""
import os
from pathlib import Path

import blog.blog_illustrator as bi
from blog.blog_streams import STREAMS
import config


_DRAFT = {
    "title": "Token-Maxing at the Edge",
    "body_md": """# Token-Maxing at the Edge

A counterintuitive claim.

## The mechanism

The numbers tell a story.

## Worked example

Here is the code.

## What I'd try next

The takeaway.
""",
    "stream": "ai",
    "title_hint": "token-maxing",
}


def _make_fake_png(path):
    """Write a minimal valid 1x1 PNG so copy operations work in tests."""
    import struct, zlib
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Minimal 1x1 white PNG.
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IHHBBBB", 1, 1, 8, 0, 0, 0, 0)
    ihdr_chunk = b"IHDR" + ihdr
    ihdr_crc = struct.pack(">I", zlib.crc32(ihdr_chunk) & 0xFFFFFFFF)
    ihdr_full = struct.pack(">I", len(ihdr)) + ihdr_chunk + ihdr_crc
    raw = b"\x00\xff\xff\xff"  # filter + white pixel
    comp = zlib.compress(raw)
    idat_chunk = b"IDAT" + comp
    idat_crc = struct.pack(">I", zlib.crc32(idat_chunk) & 0xFFFFFFFF)
    idat_full = struct.pack(">I", len(comp)) + idat_chunk + idat_crc
    iend = b"IEND"
    iend_crc = struct.pack(">I", zlib.crc32(iend) & 0xFFFFFFFF)
    iend_full = struct.pack(">I", 0) + iend + iend_crc
    path.write_bytes(sig + ihdr_full + idat_full + iend_full)
    return str(path)


def test_illustrate_returns_hero_and_section_paths(monkeypatch, tmp_path):
    """illustrate() returns {hero_path, section_paths: {h2_heading: path}}."""
    def fake_generate(draft, brand, out_dir=None, ctype=None, **kw):
        return _make_fake_png(Path(out_dir) / f"fake_{ctype or 'hero'}.png")
    monkeypatch.setattr(bi, "generate", fake_generate)
    monkeypatch.setattr(bi.budget, "can_spend", lambda cost: True)

    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=2)
    assert "hero_path" in images
    assert images["hero_path"] is not None
    assert os.path.exists(images["hero_path"])
    assert isinstance(images["section_paths"], dict)
    # At most max_sections section images.
    assert len(images["section_paths"]) <= 2


def test_illustrate_caps_at_max_sections(monkeypatch, tmp_path):
    """Section images are capped at max_sections even with many H2s."""
    body = "# T\n\nLede\n\n" + "\n\n".join(f"## Section {i}\n\nText." for i in range(10))
    draft = {**_DRAFT, "body_md": body}
    calls = []
    def fake_generate(draft, brand, out_dir=None, ctype=None, **kw):
        calls.append(ctype)
        return _make_fake_png(Path(out_dir) / f"fake_{len(calls)}.png")
    monkeypatch.setattr(bi, "generate", fake_generate)
    monkeypatch.setattr(bi.budget, "can_spend", lambda cost: True)

    images = bi.illustrate(draft, out_dir=tmp_path, max_sections=1)
    assert len(images["section_paths"]) <= 1


def test_illustrate_skips_when_budget_blocked(monkeypatch, tmp_path):
    """When budget.can_spend returns False, no images are generated."""
    monkeypatch.setattr(bi, "generate", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not call")))
    monkeypatch.setattr(bi.budget, "can_spend", lambda cost: False)
    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=2)
    assert images["hero_path"] is None
    assert images["section_paths"] == {}


def test_illustrate_uses_sahil_twitter_brand(monkeypatch, tmp_path):
    """All streams pass brand='sahil_twitter' to imagery_transplant (palette reuse)."""
    received_brands = []
    def fake_generate(draft, brand, out_dir=None, ctype=None, **kw):
        received_brands.append(brand)
        return _make_fake_png(Path(out_dir) / f"fake_{len(received_brands)}.png")
    monkeypatch.setattr(bi, "generate", fake_generate)
    monkeypatch.setattr(bi.budget, "can_spend", lambda cost: True)
    bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=1)
    assert all(b == "sahil_twitter" for b in received_brands)


def test_illustrate_section_paths_keyed_by_h2_heading(monkeypatch, tmp_path):
    """Section image paths are keyed by the H2 heading text."""
    def fake_generate(draft, brand, out_dir=None, ctype=None, **kw):
        return _make_fake_png(Path(out_dir) / f"fake_{ctype or 'hero'}.png")
    monkeypatch.setattr(bi, "generate", fake_generate)
    monkeypatch.setattr(bi.budget, "can_spend", lambda cost: True)
    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=3)
    # The draft has H2s: "The mechanism", "Worked example", "What I'd try next"
    for key in images["section_paths"]:
        assert "## " not in key  # it's the heading text, not the markdown
        assert key.strip()  # non-empty


def test_illustrate_hero_only_when_max_sections_zero(monkeypatch, tmp_path):
    """max_sections=0 produces hero only (no section images)."""
    calls = []
    def fake_generate(draft, brand, out_dir=None, ctype=None, **kw):
        calls.append(ctype)
        return _make_fake_png(Path(out_dir) / f"fake_{len(calls)}.png")
    monkeypatch.setattr(bi, "generate", fake_generate)
    monkeypatch.setattr(bi.budget, "can_spend", lambda cost: True)
    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=0)
    assert images["hero_path"] is not None
    assert images["section_paths"] == {}


def test_default_max_sections_from_config(monkeypatch, tmp_path):
    """illustrate() defaults max_sections to config.BLOG_MAX_SECTION_IMAGES."""
    def fake_generate(draft, brand, out_dir=None, ctype=None, **kw):
        return _make_fake_png(Path(out_dir) / f"fake_{ctype or 'hero'}.png")
    monkeypatch.setattr(bi, "generate", fake_generate)
    monkeypatch.setattr(bi.budget, "can_spend", lambda cost: True)
    monkeypatch.setattr(config, "BLOG_MAX_SECTION_IMAGES", 2)
    images = bi.illustrate(_DRAFT, out_dir=tmp_path)
    assert len(images["section_paths"]) <= 2