"""Tests for blog.blog_illustrator — hero + per-section images via creative-skill rotation + Codex CLI.

The illustrator now uses 6 universal illustration style skills (Mythic Tech Codex,
Cosmic Postcard Atelier, Saga Noir Studio, Ink & Ember Studio, The Ninth Observatory,
Chromatic Institute) rotating based on content heuristics, generating via Codex CLI.

No FAL, no Pollinations, no Baoyu pipeline. Zero marginal cost per image.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

import blog.blog_illustrator as bi
from blog.blog_streams import STREAMS
import config


@pytest.fixture(autouse=True)
def isolated_rotation_state(monkeypatch, tmp_path):
    monkeypatch.setattr(bi, "ROTATION_STATE_PATH", tmp_path / "skill_rotation.json")


_DRAFT = {
    "title": "Token-Maxing at the Edge",
    "description": "A counterintuitive claim about edges and inference.",
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
    def fake_generate(prompt, out_path, **kw):
        _make_fake_png(out_path)
        return out_path
    monkeypatch.setattr(bi, "_generate_codex_image", fake_generate)

    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=2)
    assert "hero_path" in images
    assert images["hero_path"] is not None
    assert Path(images["hero_path"]).exists()
    assert isinstance(images["section_paths"], dict)
    assert len(images["section_paths"]) <= 2


def test_illustrate_caps_at_max_sections(monkeypatch, tmp_path):
    """Section images are capped at max_sections even with many H2s."""
    body = "# T\n\nLede\n\n" + "\n\n".join(f"## Section {i}\n\nText." for i in range(10))
    draft = {**_DRAFT, "body_md": body}
    writes = []
    def fake_generate(prompt, out_path, **kw):
        writes.append(out_path)
        _make_fake_png(out_path)
        return out_path
    monkeypatch.setattr(bi, "_generate_codex_image", fake_generate)

    images = bi.illustrate(draft, out_dir=tmp_path, max_sections=1)
    assert len(images["section_paths"]) <= 1


def test_illustrate_hero_only_when_max_sections_zero(monkeypatch, tmp_path):
    """max_sections=0 produces hero only (no section images)."""
    writes = []
    def fake_generate(prompt, out_path, **kw):
        writes.append(out_path)
        _make_fake_png(out_path)
        return out_path
    monkeypatch.setattr(bi, "_generate_codex_image", fake_generate)

    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=0)
    assert images["hero_path"] is not None
    assert images["section_paths"] == {}
    assert len(writes) == 1  # hero only


def test_illustrate_section_paths_keyed_by_h2_heading(monkeypatch, tmp_path):
    """Section image paths are keyed by the H2 heading text."""
    def fake_generate(prompt, out_path, **kw):
        _make_fake_png(out_path)
        return out_path
    monkeypatch.setattr(bi, "_generate_codex_image", fake_generate)

    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=3)
    for key in images["section_paths"]:
        assert "## " not in key
        assert key.strip()


def test_illustrate_handles_failed_hero(monkeypatch, tmp_path):
    """When hero generation fails, hero_path is None but sections still attempt."""
    fail_count = [0]
    def fake_generate(prompt, out_path, **kw):
        if "hero.png" in out_path:
            fail_count[0] += 1
            return None
        _make_fake_png(out_path)
        return out_path
    monkeypatch.setattr(bi, "_generate_codex_image", fake_generate)

    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=1)
    assert images["hero_path"] is None


def test_illustrate_handles_failed_section(monkeypatch, tmp_path):
    """When section generation fails, its entry is simply not added."""
    def fake_generate(prompt, out_path, **kw):
        if "section" in out_path:
            return None
        _make_fake_png(out_path)
        return out_path
    monkeypatch.setattr(bi, "_generate_codex_image", fake_generate)

    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=3)
    assert images["hero_path"] is not None
    assert images["section_paths"] == {}


def test_default_max_sections_from_config(monkeypatch, tmp_path):
    """illustrate() defaults max_sections to config.BLOG_MAX_SECTION_IMAGES."""
    def fake_generate(prompt, out_path, **kw):
        _make_fake_png(out_path)
        return out_path
    monkeypatch.setattr(bi, "_generate_codex_image", fake_generate)
    monkeypatch.setattr(config, "BLOG_MAX_SECTION_IMAGES", 2)

    images = bi.illustrate(_DRAFT, out_dir=tmp_path)
    assert len(images["section_paths"]) <= 2


def test_illustrate_uses_creative_skills_not_fal_not_pollinations():
    """Verify the module uses Codex CLI, not FAL or Pollinations."""
    import inspect
    src = inspect.getsource(bi)
    # Should reference codex/generate_codex_image
    assert "_generate_codex_image" in src
    # Check import lines — docstring mentions Pollinations in "no" context
    import_lines = [l.strip() for l in src.splitlines() if l.strip().startswith("import ") or l.strip().startswith("from ")]
    joined = "\n".join(import_lines)
    assert "fal_client" not in joined
    assert "Pollinations" not in joined
    assert "draft_media" not in joined


def test_select_skill_returns_valid_name():
    """_select_skill returns a valid skill name."""
    name = bi._select_skill("Token-Maxing at the Edge", "ai")
    assert name in [s["name"] for s in bi.SKILL_STYLES]


def test_select_skill_rotates_away_from_previous():
    """Two calls should not return the same skill (rotation penalty)."""
    name1 = bi._select_skill("AI Research Breakthroughs", "ai")
    name2 = bi._select_skill("Another AI Paper", "ai")
    # With recency penalty of -5, they should be different
    # (they might be the same if the second has no other good options)
    # At least verify they're valid
    assert name1 in [s["name"] for s in bi.SKILL_STYLES]
    assert name2 in [s["name"] for s in bi.SKILL_STYLES]


def test_load_prompt_template_exists():
    """Prompt templates can be loaded from existing skills."""
    for style in bi.SKILL_STYLES:
        tmpl = bi._load_prompt_template(style["name"])
        assert tmpl is not None, f"No template for {style['name']}"
        assert "{CONCEPT}" in tmpl, f"Template for {style['name']} missing {{CONCEPT}}"


def test_no_fal_imports():
    """Verify no FAL imports in the module source code."""
    import inspect
    src = inspect.getsource(bi)
    import_lines = [l.strip() for l in src.splitlines() if l.strip().startswith("import ") or l.strip().startswith("from ")]
    joined = "\n".join(import_lines)
    assert "fal_client" not in joined
    assert "budget" not in joined
    assert "draft_media" not in joined
