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
    monkeypatch.setattr(it.budget, "can_spend", lambda c, cap=10.0: True)
    monkeypatch.setattr(it.budget, "record", lambda c, label="": None)
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
    """One palette across hero + all sections."""
    import blog.blog_illustrator as bi
    seen = []

    def fake_generate(draft, brand, out_dir=None, recipe=None, **k):
        seen.append(recipe["palette"])
        p = tmp_path / f"{len(seen)}.png"
        p.write_text("x")
        return str(p)

    monkeypatch.setattr(bi, "generate", fake_generate)
    monkeypatch.setattr(bi.budget, "can_spend", lambda c: True)
    monkeypatch.setattr(bi.config, "BLOG_MAX_SECTION_IMAGES", 2)
    monkeypatch.setattr(bi.config, "BLOG_IMAGE_MODEL", "fal-ai/nano-banana-2/edit")
    monkeypatch.setattr(bi.config, "BLOG_IMAGE_COST_GBP", 0.06)

    draft = {
        "title": "Test post",
        "description": "a test description with enough text for a recipe",
        "stream": "ai",
        "body_md": "## One\nx\n\n## Two\ny\n\n## Three\nz",
    }
    bi.illustrate(draft, out_dir=tmp_path, max_sections=2)
    # hero + 2 sections = 3 images, all same palette
    assert len(set(seen)) == 1, f"expected 1 palette, got {seen}"
    assert len(seen) == 3, f"expected 3 images, got {len(seen)}"
