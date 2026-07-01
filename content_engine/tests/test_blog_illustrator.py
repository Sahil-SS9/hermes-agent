"""Tests for blog.blog_illustrator — art-directed image set via Codex CLI.

The illustrator now drives every image from a single art brief (art_director):
one style + locked palette/motif + shared direction, with a unique prompt for
the hero and each section. Generation backend is Codex CLI (no FAL/Pollinations).
"""
from pathlib import Path

import pytest

import blog.blog_illustrator as bi
import blog.art_director as ad
import config


@pytest.fixture(autouse=True)
def isolated_rotation_state(monkeypatch, tmp_path):
    monkeypatch.setattr(bi, "ROTATION_STATE_PATH", tmp_path / "skill_rotation.json")


@pytest.fixture(autouse=True)
def stub_art_brief(monkeypatch):
    """Force a deterministic brief so tests never hit the LLM."""
    def fake_brief(draft, headings, recent_styles=None, llm=None):
        return {
            "style": "ninth-observatory",
            "palette": "stone grey, brass, warm amber",
            "motif": "a recurring archway",
            "art_direction": "vast, awe-of-scale, one warm focal light.",
            "hero_prompt": f"hero for {draft.get('title','')}",
            "section_prompts": {h: f"section image for {h}" for h in headings},
        }
    monkeypatch.setattr(bi, "build_art_brief", fake_brief)


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
}


def test_illustrate_returns_hero_and_section_paths(monkeypatch, tmp_path):
    def fake_generate(prompt, out_path, **kw):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("png")
        return out_path
    monkeypatch.setattr(bi, "_generate_codex_image", fake_generate)
    monkeypatch.setattr(bi, "_generate_webp", lambda p: p)

    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=2)
    assert images["hero_path"] is not None
    assert Path(images["hero_path"]).exists()
    assert isinstance(images["section_paths"], dict)
    assert len(images["section_paths"]) <= 2


def test_illustrate_caps_at_max_sections(monkeypatch, tmp_path):
    body = "# T\n\nLede\n\n" + "\n\n".join(f"## Section {i}\n\nText." for i in range(10))
    draft = {**_DRAFT, "body_md": body}
    monkeypatch.setattr(bi, "_generate_codex_image",
                        lambda prompt, out_path, **kw: (Path(out_path).write_text("x"), out_path)[1])
    monkeypatch.setattr(bi, "_generate_webp", lambda p: p)
    images = bi.illustrate(draft, out_dir=tmp_path, max_sections=1)
    assert len(images["section_paths"]) <= 1


def test_illustrate_hero_only_when_max_sections_zero(monkeypatch, tmp_path):
    writes = []
    def fake_generate(prompt, out_path, **kw):
        writes.append(out_path)
        Path(out_path).write_text("x")
        return out_path
    monkeypatch.setattr(bi, "_generate_codex_image", fake_generate)
    monkeypatch.setattr(bi, "_generate_webp", lambda p: p)
    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=0)
    assert images["hero_path"] is not None
    assert images["section_paths"] == {}
    assert len(writes) == 1


def test_illustrate_section_paths_keyed_by_h2_heading(monkeypatch, tmp_path):
    monkeypatch.setattr(bi, "_generate_codex_image",
                        lambda prompt, out_path, **kw: (Path(out_path).write_text("x"), out_path)[1])
    monkeypatch.setattr(bi, "_generate_webp", lambda p: p)
    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=3)
    for key in images["section_paths"]:
        assert "## " not in key
        assert key.strip()


def test_illustrate_handles_failed_hero(monkeypatch, tmp_path):
    def fake_generate(prompt, out_path, **kw):
        if "hero.png" in out_path:
            return None
        Path(out_path).write_text("x")
        return out_path
    monkeypatch.setattr(bi, "_generate_codex_image", fake_generate)
    monkeypatch.setattr(bi, "_generate_webp", lambda p: p)
    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=1)
    assert images["hero_path"] is None


def test_all_images_share_one_style(monkeypatch, tmp_path):
    """Hero and every section use the same style/palette (consistency)."""
    prompts = []
    def fake_generate(prompt, out_path, **kw):
        prompts.append(prompt)
        Path(out_path).write_text("x")
        return out_path
    monkeypatch.setattr(bi, "_generate_codex_image", fake_generate)
    monkeypatch.setattr(bi, "_generate_webp", lambda p: p)
    bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=2)
    assert len(prompts) == 3  # hero + 2 sections
    # The Ninth Observatory label and the locked palette appear in every prompt.
    assert all("Ninth Observatory" in p for p in prompts)
    assert all("brass" in p for p in prompts)


def test_prompts_are_unique_per_image(monkeypatch, tmp_path):
    """Consistent style, but each image depicts its own concept."""
    prompts = []
    def fake_generate(prompt, out_path, **kw):
        prompts.append(prompt)
        Path(out_path).write_text("x")
        return out_path
    monkeypatch.setattr(bi, "_generate_codex_image", fake_generate)
    monkeypatch.setattr(bi, "_generate_webp", lambda p: p)
    bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=2)
    assert len(set(prompts)) == 3  # all distinct


def test_default_max_sections_from_config(monkeypatch, tmp_path):
    monkeypatch.setattr(bi, "_generate_codex_image",
                        lambda prompt, out_path, **kw: (Path(out_path).write_text("x"), out_path)[1])
    monkeypatch.setattr(bi, "_generate_webp", lambda p: p)
    monkeypatch.setattr(config, "BLOG_MAX_SECTION_IMAGES", 2)
    images = bi.illustrate(_DRAFT, out_dir=tmp_path)
    assert len(images["section_paths"]) <= 2


def test_falls_back_to_deterministic_brief(monkeypatch, tmp_path):
    """When the LLM brief returns None, the fallback brief still drives images."""
    monkeypatch.setattr(bi, "build_art_brief",
                        lambda draft, headings, recent_styles=None, llm=None: None)
    prompts = []
    def fake_generate(prompt, out_path, **kw):
        prompts.append(prompt)
        Path(out_path).write_text("x")
        return out_path
    monkeypatch.setattr(bi, "_generate_codex_image", fake_generate)
    monkeypatch.setattr(bi, "_generate_webp", lambda p: p)
    images = bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=1)
    assert images["hero_path"] is not None
    assert len(prompts) == 2  # hero + 1 section


def test_records_style_to_rotation_state(monkeypatch, tmp_path):
    monkeypatch.setattr(bi, "_generate_codex_image",
                        lambda prompt, out_path, **kw: (Path(out_path).write_text("x"), out_path)[1])
    monkeypatch.setattr(bi, "_generate_webp", lambda p: p)
    bi.illustrate(_DRAFT, out_dir=tmp_path, max_sections=0)
    assert (tmp_path / "skill_rotation.json").exists()
    assert "ninth-observatory" in bi._load_recent_styles()


def test_no_fal_imports():
    import inspect
    src = inspect.getsource(bi)
    import_lines = [l.strip() for l in src.splitlines()
                    if l.strip().startswith(("import ", "from "))]
    joined = "\n".join(import_lines)
    assert "fal_client" not in joined
    assert "draft_media" not in joined
    assert "Pollinations" not in joined
