"""Tests for per-post locked recipe (no intra-post style drift)."""

import pathlib
import random

import imagery_library as lib
import imagery_transplant as it


def test_select_recipe_honours_forced_palette():
    """When palette is forced, all calls return the same palette regardless of seed."""
    d = {"title": "AI framework comparison", "body_text": "framework comparison", "format": "infographic"}
    r1 = lib.select_recipe(d, "sahil_twitter", ctype="infographic", palette="blueprint_mono")
    r2 = lib.select_recipe(d, "sahil_twitter", ctype="infographic", palette="blueprint_mono", seed=99)
    assert r1 and r2, "both calls should return a recipe"
    assert r1["palette"] == "blueprint_mono" and r2["palette"] == "blueprint_mono"


def test_generate_accepts_recipe_override(monkeypatch, tmp_path):
    """When recipe is passed to generate, it skips select_recipe entirely."""
    recipe = {
        "kind": "infographic", "palette": "synthwave", "layout": "funnel",
        "layout_path": tmp_path / "L.webp", "style_path": tmp_path / "S.webp",
        "hex": "deep purple #1A0B2E", "light": False, "ctype": "infographic", "aspect": "4:5",
    }
    # Create minimal anchor files
    for p in [recipe["layout_path"], recipe["style_path"]]:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")

    called = {"select": 0}

    def fake_select(*a, **k):
        called["select"] += 1
        return recipe

    monkeypatch.setattr(it.lib, "select_recipe", fake_select)
    monkeypatch.setattr(it.budget, "can_spend", lambda c, cap=10.0, **k: True)
    monkeypatch.setattr(it.budget, "record", lambda c, label="", **k: None)
    monkeypatch.setattr(it.fal_client, "upload_file", lambda p, **k: "http://u")
    raw = tmp_path / "r.png"
    raw.write_bytes(b"x")
    monkeypatch.setattr(it.fal_client, "generate_image_edit", lambda *a, **k: str(raw))
    monkeypatch.setattr(it.pp, "finish_file", lambda r, o, light=False: o)
    monkeypatch.setattr(it.gemini_vision, "available", lambda: False)

    out = it.generate({"title": "t", "id": "x"}, "sahil_twitter", out_dir=tmp_path, recipe=recipe)
    assert out, "generate should return a path"
    assert called["select"] == 0, "should never re-select when recipe is given"


def test_illustrate_locks_palette(monkeypatch, tmp_path):
    """One consistent creative style across hero + all sections in one post.

    The skill rotation picks one style per post. All images in one post use
    the same style template, guaranteeing visual consistency.
    """
    import blog.blog_illustrator as bi
    seen_skills = []

    def fake_generate(prompt, out_path, **kw):
        # Infer which skill was used from the prompt content
        if "Mythic Tech Codex" in prompt:
            seen_skills.append("mythic-tech-codex-illustration")
        elif "Saga Noir Studio" in prompt:
            seen_skills.append("saga-noir-studio")
        elif "Ink & Ember Studio" in prompt:
            seen_skills.append("ink-ember-studio")
        elif "Cosmic Postcard Atelier" in prompt:
            seen_skills.append("cosmic-postcard-atelier")
        elif "The Ninth Observatory" in prompt:
            seen_skills.append("ninth-observatory")
        elif "Chromatic Institute" in prompt:
            seen_skills.append("chromatic-institute")
        else:
            seen_skills.append("unknown")
        p = tmp_path / f"img_{len(seen_skills)}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
        return out_path

    monkeypatch.setattr(bi, "_generate_codex_image", fake_generate)
    monkeypatch.setattr(bi.config, "BLOG_MAX_SECTION_IMAGES", 2)
    monkeypatch.setattr(bi, "ROTATION_STATE_PATH", tmp_path / "skill_rotation.json")

    draft = {
        "title": "Test post",
        "description": "a test description",
        "stream": "ai",
        "body_md": "## One\nx\n\n## Two\ny\n\n## Three\nz",
    }
    bi.illustrate(draft, out_dir=tmp_path, max_sections=2)
    # hero + 2 sections = 3 images, all same skill
    assert len(seen_skills) == 3, f"expected 3 images, got {len(seen_skills)}"
    assert len(set(seen_skills)) == 1, f"expected 1 skill across images, got {seen_skills}"


def test_illustrate_varies_palette_across_topics(monkeypatch, tmp_path):
    """Different topics should not all collapse into the same house image style.

    The creative skill rotation system (6 styles + recency penalty) ensures
    variety across posts. This test verifies that the skill selector produces
    different choices for different content profiles.
    """
    import blog.blog_illustrator as bi

    monkeypatch.setattr(bi, "ROTATION_STATE_PATH", tmp_path / "skill_rotation.json")

    # Three different content profiles should produce varied skill selections
    # via the scoring heuristics (stream + cue patterns).
    selections = set()
    for title, stream in [
        ("A spreadsheet for LLM inference", "builder"),
        ("Agent Memory Architecture", "builder"),
        ("Model Routing Decision Framework", "ai"),
    ]:
        skill = bi._select_skill(title, stream)
        selections.add(skill)

    # With 6+ styles and different cue patterns, we expect at least 2 different
    # selections across 3 distinct topics (recency penalty forces variety).
    assert len(selections) >= 2, (
        f"Expected at least 2 different skills across 3 topics, got {selections}"
    )
