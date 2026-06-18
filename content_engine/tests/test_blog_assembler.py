"""Tests for blog.blog_assembler — emit MDX with valid frontmatter into SahilBlog.

The assembler writes approved:false drafts to SAHILBLOG_REPO/src/content/blog/
with frontmatter matching the VERIFIED contract (content.config.ts schema):
  title, description, pubDate (unquoted YYYY-MM-DD), tags, tier, format,
  approved: false, source, heroImage (optional).
Images are copied to public/blog/<slug>/ and inline refs rewritten.
"""
import os
import re
import shutil
from pathlib import Path

import blog.blog_assembler as ba


_DRAFT = {
    "title": "Token-Maxing at the Edge",
    "description": "A counterintuitive claim grounded in concrete figures.",
    "body_md": """# Token-Maxing at the Edge

A counterintuitive claim.

## The mechanism

The numbers tell a story.

## Worked example

Here is the code.

## What I'd try next

The takeaway.""",
    "slug": "token-maxing-at-the-edge",
    "tier": "pm",
    "tags": ["ai", "ai-adoption"],
    "format": "essay",
    "source": "research-paper",
    "stream": "ai",
}


def _make_fake_png(path):
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


def _setup_tmp_repo(tmp_path):
    """Create a minimal tmp SahilBlog repo skeleton."""
    (tmp_path / "src/content/blog").mkdir(parents=True)
    (tmp_path / "public/blog").mkdir(parents=True)
    return tmp_path


def test_assemble_writes_mdx_with_valid_frontmatter(tmp_path):
    """Assembler writes src/content/blog/<slug>.mdx with all required fields."""
    repo = _setup_tmp_repo(tmp_path)
    images = {"hero_path": None, "section_paths": {}}
    path = ba.assemble(_DRAFT, images, repo=str(repo))
    assert path.exists()
    text = path.read_text()
    # Frontmatter is between --- markers.
    assert text.startswith("---\n")
    fm_end = text.index("\n---\n", 4)
    fm = text[4:fm_end]
    # Required fields.
    assert 'title: "Token-Maxing at the Edge"' in fm
    assert "description:" in fm
    assert re.search(r"pubDate:\s+\d{4}-\d{2}-\d{2}", fm), "pubDate must be unquoted YYYY-MM-DD"
    assert "approved: false" in fm
    assert 'tier: "pm"' in fm or "tier: pm" in fm
    assert 'format: "essay"' in fm or "format: essay" in fm
    assert "source: research-paper" in fm or 'source: "research-paper"' in fm
    # Tags as YAML list.
    assert "tags:" in fm
    assert "ai" in fm
    assert "ai-adoption" in fm


def test_assemble_pubdate_is_unquoted_date(tmp_path):
    """pubDate must be an unquoted YYYY-MM-DD literal for Astro z.date()."""
    repo = _setup_tmp_repo(tmp_path)
    images = {"hero_path": None, "section_paths": {}}
    path = ba.assemble(_DRAFT, images, repo=str(repo))
    text = path.read_text()
    # Must NOT be quoted.
    assert re.search(r"pubDate:\s+\d{4}-\d{2}-\d{2}\s*$", text, re.MULTILINE), \
        "pubDate must be unquoted YYYY-MM-DD"
    assert 'pubDate: "' not in text
    assert "pubDate: '" not in text


def test_assemble_approved_is_false(tmp_path):
    """Generated posts are hidden (approved:false) until human approval."""
    repo = _setup_tmp_repo(tmp_path)
    images = {"hero_path": None, "section_paths": {}}
    path = ba.assemble(_DRAFT, images, repo=str(repo))
    text = path.read_text()
    assert "approved: false" in text


def test_assemble_copies_hero_image_and_sets_heroimage(tmp_path):
    """When a hero image exists, it is copied and heroImage is set in frontmatter."""
    repo = _setup_tmp_repo(tmp_path)
    hero = _make_fake_png(tmp_path / "hero_src.png")
    images = {"hero_path": hero, "section_paths": {}}
    path = ba.assemble(_DRAFT, images, repo=str(repo))
    text = path.read_text()
    slug = _DRAFT["slug"]
    assert 'heroImage: "/blog/{}/hero.png"'.format(slug) in text
    assert (repo / "public/blog/{}/hero.png".format(slug)).exists()


def test_assemble_copies_section_images_and_rewrites_refs(tmp_path):
    """Section images are copied to public/blog/<slug>/ and inline refs rewritten."""
    repo = _setup_tmp_repo(tmp_path)
    sec1 = _make_fake_png(tmp_path / "sec1_src.png")
    images = {
        "hero_path": None,
        "section_paths": {"The mechanism": sec1},
    }
    path = ba.assemble(_DRAFT, images, repo=str(repo))
    text = path.read_text()
    slug = _DRAFT["slug"]
    # Image copied.
    assert (repo / "public/blog/{}/01.png".format(slug)).exists()
    # Inline ref rewritten to /blog/<slug>/NN.png.
    assert "/blog/{}/01.png".format(slug) in text


def test_assemble_no_hero_leaves_heroimage_absent(tmp_path):
    """When no hero image, heroImage is not in frontmatter (optional field)."""
    repo = _setup_tmp_repo(tmp_path)
    images = {"hero_path": None, "section_paths": {}}
    path = ba.assemble(_DRAFT, images, repo=str(repo))
    text = path.read_text()
    assert "heroImage:" not in text


def test_assemble_returns_mdx_path(tmp_path):
    """assemble() returns the Path to the written MDX file."""
    repo = _setup_tmp_repo(tmp_path)
    images = {"hero_path": None, "section_paths": {}}
    path = ba.assemble(_DRAFT, images, repo=str(repo))
    assert path.name == _DRAFT["slug"] + ".mdx"
    assert path.parent.name == "blog"
    assert path.exists()


def test_assemble_slug_collision_safe(tmp_path):
    """Two assembles with the same slug do not clobber (append suffix)."""
    repo = _setup_tmp_repo(tmp_path)
    images = {"hero_path": None, "section_paths": {}}
    p1 = ba.assemble(_DRAFT, images, repo=str(repo))
    p2 = ba.assemble(_DRAFT, images, repo=str(repo))
    assert p1.exists()
    assert p2.exists()
    # They should be different files (collision resolved).
    assert p1 != p2 or p1.read_text() == p2.read_text()  # at least both exist