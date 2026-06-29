"""Tests for blog.blog_illustrator — hero + per-section images via Codex CLI.

The illustrator now uses codex_image_gen (Codex CLI with ChatGPT auth) instead
of FAL/imagery_transplant. No budget gating — Codex is zero marginal cost.
Tests mock generate_hero/generate_section to avoid real CLI calls.
"""
import os
from pathlib import Path
from unittest.mock import patch

import blog.blog_illustrator as bi
from blog.blog_streams import STREAMS
import config


_DRAFT = {
    "title": "Token-Maxing at the Edge",
    "description": "A counterintuitive claim about edges.",
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
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IHHBBBB", 1, 1, 8, 0, 0, 0, 0)
    ihdr_chunk = b"IHDR" + ihdr
    ihdr_crc = struct.pack(">I", zlib.crc32(ihdr_chunk) & 0xFFFFFFFF)
    ihdr_full = struct.pack(">I", len(ihdr)) + ihdr_chunk + ihdr_crc
    raw = b"\x00\xff\xff\xff"
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
    def fake_hero(title, description, out_path, **kw):
        return _make_fake_png(out_path)
    def fake_section(title, heading, out_path, **kw):
        return _make_fake_png(out_path)
    monkeypatch.setattr(bi, "generate_hero", fake_hero)
    monkeypatch.setattr(bi, "generate_section", fake_section)

    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=2)
    assert "hero_path" in images
    assert images["hero_path"] is not None
    assert os.path.exists(images["hero_path"])
    assert isinstance(images["section_paths"], dict)
    assert len(images["section_paths"]) <= 2


def test_illustrate_caps_at_max_sections(monkeypatch, tmp_path):
    """Section images are capped at max_sections even with many H2s."""
    body = "# T\n\nLede\n\n" + "\n\n".join(f"## Section {i}\n\nText." for i in range(10))
    draft = {**_DRAFT, "body_md": body}
    calls = []
    def fake_hero(title, description, out_path, **kw):
        return _make_fake_png(out_path)
    def fake_section(title, heading, out_path, **kw):
        calls.append(heading)
        return _make_fake_png(out_path)
    monkeypatch.setattr(bi, "generate_hero", fake_hero)
    monkeypatch.setattr(bi, "generate_section", fake_section)

    images = bi.illustrate(draft, out_dir=tmp_path, max_sections=1)
    assert len(images["section_paths"]) <= 1


def test_illustrate_hero_only_when_max_sections_zero(monkeypatch, tmp_path):
    """max_sections=0 produces hero only (no section images)."""
    calls = []
    def fake_hero(title, description, out_path, **kw):
        return _make_fake_png(out_path)
    def fake_section(title, heading, out_path, **kw):
        calls.append(heading)
        return _make_fake_png(out_path)
    monkeypatch.setattr(bi, "generate_hero", fake_hero)
    monkeypatch.setattr(bi, "generate_section", fake_section)

    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=0)
    assert images["hero_path"] is not None
    assert images["section_paths"] == {}
    assert len(calls) == 0


def test_illustrate_section_paths_keyed_by_h2_heading(monkeypatch, tmp_path):
    """Section image paths are keyed by the H2 heading text."""
    def fake_hero(title, description, out_path, **kw):
        return _make_fake_png(out_path)
    def fake_section(title, heading, out_path, **kw):
        return _make_fake_png(out_path)
    monkeypatch.setattr(bi, "generate_hero", fake_hero)
    monkeypatch.setattr(bi, "generate_section", fake_section)

    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=3)
    for key in images["section_paths"]:
        assert "## " not in key
        assert key.strip()


def test_illustrate_handles_failed_hero(monkeypatch, tmp_path):
    """When hero generation fails, hero_path is None but sections still attempt."""
    def fake_hero(title, description, out_path, **kw):
        return None
    def fake_section(title, heading, out_path, **kw):
        return _make_fake_png(out_path)
    monkeypatch.setattr(bi, "generate_hero", fake_hero)
    monkeypatch.setattr(bi, "generate_section", fake_section)

    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=1)
    assert images["hero_path"] is None


def test_illustrate_handles_failed_section(monkeypatch, tmp_path):
    """When section generation fails, its entry is simply not added."""
    def fake_hero(title, description, out_path, **kw):
        return _make_fake_png(out_path)
    def fake_section(title, heading, out_path, **kw):
        return None
    monkeypatch.setattr(bi, "generate_hero", fake_hero)
    monkeypatch.setattr(bi, "generate_section", fake_section)

    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=3)
    assert images["hero_path"] is not None
    assert images["section_paths"] == {}


def test_default_max_sections_from_config(monkeypatch, tmp_path):
    """illustrate() defaults max_sections to config.BLOG_MAX_SECTION_IMAGES."""
    def fake_hero(title, description, out_path, **kw):
        return _make_fake_png(out_path)
    def fake_section(title, heading, out_path, **kw):
        return _make_fake_png(out_path)
    monkeypatch.setattr(bi, "generate_hero", fake_hero)
    monkeypatch.setattr(bi, "generate_section", fake_section)
    monkeypatch.setattr(config, "BLOG_MAX_SECTION_IMAGES", 2)

    images = bi.illustrate(_DRAFT, out_dir=tmp_path)
    assert len(images["section_paths"]) <= 2


def test_illustrate_no_fal_imports():
    """Verify no FAL imports in blog_illustrator module source code only."""
    import inspect
    src = inspect.getsource(bi)
    import_lines = [l.strip() for l in src.splitlines() if l.strip().startswith("import ") or l.strip().startswith("from ")]
    joined = chr(10).join(import_lines)
    assert "fal_client" not in joined
    assert "from imagery_transplant" not in joined
    assert "import imagery_transplant" not in joined
    assert "from budget" not in joined
    assert "import budget" not in joined



def test_illustrate_no_budget_calls():
    """Verify no budget.can_spend calls in blog_illustrator module."""
    import inspect
    src = inspect.getsource(bi)
    assert "can_spend" not in src


def test_illustrate_uses_codex_image_gen():
    """Verify codex_image_gen is imported and used."""
    import inspect
    src = inspect.getsource(bi)
    assert "codex_image_gen" in src
    assert "generate_hero" in src
    assert "generate_section" in src


def test_illustrate_passes_palette_to_codex(monkeypatch, tmp_path):
    """illustrate() passes palette guidance derived from stream brand."""
    received_palettes = []
    def fake_hero(title, description, out_path, **kw):
        received_palettes.append(kw.get("palette", ""))
        return _make_fake_png(out_path)
    def fake_section(title, heading, out_path, **kw):
        received_palettes.append(kw.get("palette", ""))
        return _make_fake_png(out_path)
    monkeypatch.setattr(bi, "generate_hero", fake_hero)
    monkeypatch.setattr(bi, "generate_section", fake_section)

    bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=1)
    # All palettes should contain neon-on-dark guidance.
    for p in received_palettes:
        assert "neon-on-dark" in p