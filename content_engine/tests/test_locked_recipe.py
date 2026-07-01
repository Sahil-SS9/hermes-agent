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


def test_illustrate_locks_style_across_post(monkeypatch, tmp_path):
    """One consistent style + palette across hero + all sections in one post.

    The art brief locks one style/palette for the whole post; every image
    prompt is composed against it, guaranteeing visual consistency.
    """
    import blog.blog_illustrator as bi

    def fake_brief(draft, headings, recent_styles=None, llm=None):
        return {
            "style": "chromatic-institute",
            "palette": "cobalt, coral, cream",
            "motif": "interlocking nodes",
            "art_direction": "clean modern research abstraction.",
            "hero_prompt": "hero concept",
            "section_prompts": {h: f"concept for {h}" for h in headings},
        }

    prompts = []

    def fake_generate(prompt, out_path, **kw):
        prompts.append(prompt)
        p = tmp_path / f"img_{len(prompts)}.png"
        p.write_text("x")
        return out_path

    monkeypatch.setattr(bi, "build_art_brief", fake_brief)
    monkeypatch.setattr(bi, "_generate_codex_image", fake_generate)
    monkeypatch.setattr(bi, "_generate_webp", lambda p: p)
    monkeypatch.setattr(bi.config, "BLOG_MAX_SECTION_IMAGES", 2)
    monkeypatch.setattr(bi, "ROTATION_STATE_PATH", tmp_path / "skill_rotation.json")

    draft = {
        "title": "Test post",
        "description": "a test description",
        "stream": "ai",
        "body_md": "## One\nx\n\n## Two\ny\n\n## Three\nz",
    }
    bi.illustrate(draft, out_dir=tmp_path, max_sections=2)
    assert len(prompts) == 3, f"expected 3 images, got {len(prompts)}"
    # Same style label + palette in every prompt = locked visual identity.
    assert all("Chromatic Institute" in p for p in prompts)
    assert all("coral" in p for p in prompts)


def test_art_director_varies_style_across_topics(monkeypatch):
    """The fallback selector spreads styles across posts (variety).

    Recording each pick as "recent" pushes the next post to a different style,
    so distinct posts don't collapse into one house style.
    """
    import blog.art_director as ad

    recent = []
    picks = set()
    for title in ["A spreadsheet for LLM inference",
                  "Agent memory architecture",
                  "Model routing decision framework"]:
        brief = ad.fallback_brief({"title": title, "description": ""}, [],
                                  recent_styles=recent)
        picks.add(brief["style"])
        recent.append(brief["style"])

    assert len(picks) >= 2, f"expected variety across topics, got {picks}"
