"""Tests for imagery_library — recipe selection, palette gating, rotation."""
import json
import random

import pytest

import imagery_library as lib


def test_pick_avoids_recent():
    assert lib._pick(["a", "b", "c"], ["a", "b"], random.Random(0)) == "c"


def test_pick_falls_back_when_all_recent():
    # No fresh option -> still returns one of the options (no crash).
    assert lib._pick(["a", "b"], ["a", "b"], random.Random(0)) in ("a", "b")


def test_palette_brand_gating_definition():
    # acid/synthwave are Twitter-only; blueprint/warm/cyber are shared.
    assert "sahil_linkedin" not in lib.PALETTES["acid_duotone"]["brands"]
    assert "sahil_twitter" in lib.PALETTES["acid_duotone"]["brands"]
    assert "sahil_linkedin" in lib.PALETTES["warm_editorial"]["brands"]


def test_select_recipe_scene_returns_scene_recipe(monkeypatch, tmp_path):
    monkeypatch.setattr(lib, "_ROTATION", tmp_path / "rot.json")
    r = lib.select_recipe({"format": "scene", "title": "a calm dawn"}, "sahil_twitter")
    # Scene types now resolve to a scene recipe (or None if no scene anchors exist).
    if r is not None:
        assert r["kind"] == "scene"


def test_select_recipe_unknown_type_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(lib, "_ROTATION", tmp_path / "rot.json")
    # A type that is neither infographic-family nor scene-family.
    assert lib.select_recipe({}, "sahil_twitter", ctype="bogus") is None


def test_select_recipe_infographic(monkeypatch, tmp_path):
    monkeypatch.setattr(lib, "_ROTATION", tmp_path / "rot.json")
    draft = {"format": "infographic", "title": "5 ways to ship", "body_text": "a. b. c."}
    r = lib.select_recipe(draft, "sahil_twitter", seed=1)
    if r is None:
        pytest.skip("baoyu anchors not present on this box")
    assert r["layout"] and r["layout_path"].exists()
    assert r["palette"] in lib.PALETTES
    assert "sahil_twitter" in lib.PALETTES[r["palette"]]["brands"]
    assert r["layout_path"].exists() and r["style_path"].exists()
    assert r["aspect"] == "4:5"


def test_select_recipe_linkedin_excludes_twitter_only_palettes(monkeypatch, tmp_path):
    monkeypatch.setattr(lib, "_ROTATION", tmp_path / "rot.json")
    draft = {"format": "infographic", "title": "t", "body_text": "a. b."}
    for s in range(8):
        r = lib.select_recipe(draft, "sahil_linkedin", seed=s)
        if r is None:
            pytest.skip("baoyu anchors not present")
        assert r["palette"] not in ("acid_duotone", "synthwave")


def _has_anchors():
    return bool(lib._existing(lib._GENERAL_LAYOUTS))


def test_match_layout_levels_not_quadrants():
    """Regression: a 'levels/stack' topic must NOT get the Eisenhower quadrants
    template (the bug that reframed 'Agentic Autonomy Stack' as Do-First/Delegate)."""
    if not _has_anchors():
        import pytest; pytest.skip("anchors not present")
    got = lib.match_layout({"title": "5 Levels of Agent Autonomy", "body_text": "tiers"})
    assert "priority-quadrants" not in got
    assert any(x in got for x in ("pyramid", "layers-stack", "tree-hierarchy"))


def test_match_layout_matrix_uses_quadrants():
    if not _has_anchors():
        import pytest; pytest.skip("anchors not present")
    got = lib.match_layout({"title": "An urgent vs important prioritisation matrix",
                            "body_text": ""})
    if lib._layout_path("priority-quadrants").exists():
        assert got == ["priority-quadrants"]


def test_match_layout_generic_is_semantically_neutral():
    if not _has_anchors():
        import pytest; pytest.skip("anchors not present")
    got = lib.match_layout({"title": "Tips for shipping faster", "body_text": "a. b. c."})
    assert all(x not in got for x in
               ("priority-quadrants", "venn", "fishbone", "timeline-horizontal"))


def test_match_layout_comparison():
    if not _has_anchors():
        import pytest; pytest.skip("anchors not present")
    got = lib.match_layout({"title": "Codex vs Claude for agent loops", "body_text": ""})
    assert any(x in got for x in ("comparison-table", "scale-balance"))


def _has_scenes():
    return bool(lib._existing_scenes(list(lib.SCENE_ARCHETYPES)))


def test_match_scene_philosophy_is_abstract():
    if not _has_scenes():
        import pytest; pytest.skip("scene anchors not present")
    got = lib.match_scene({"title": "The ghost in the transformer", "body_text": "nature of meaning"})
    assert any(a in got for a in ("abstract", "tarot"))


def test_match_scene_default_no_figure_bias():
    if not _has_scenes():
        import pytest; pytest.skip("scene anchors not present")
    got = lib.match_scene({"title": "A quiet note", "body_text": "no strong cue here"})
    assert got and all(a in lib.SCENE_ARCHETYPES for a in got)


def test_select_recipe_scene_kind(monkeypatch, tmp_path):
    monkeypatch.setattr(lib, "_ROTATION", tmp_path / "rot.json")
    draft = {"title": "The ghost in the transformer",
             "body_text": "A meditation on what models actually understand."}
    r = lib.select_recipe(draft, "sahil_twitter", seed=1)
    if r is None:
        import pytest; pytest.skip("scene anchors not present")
    assert r["kind"] == "scene"
    assert r["archetype"] in lib.SCENE_ARCHETYPES
    assert r["anchor_path"].exists()
    assert r["palette"] in lib.PALETTES


def test_select_recipe_records_rotation(monkeypatch, tmp_path):
    rot = tmp_path / "rot.json"
    monkeypatch.setattr(lib, "_ROTATION", rot)
    r = lib.select_recipe({"format": "infographic", "title": "t", "body_text": "a. b."},
                          "sahil_twitter", seed=2)
    if r is None:
        pytest.skip("baoyu anchors not present")
    data = json.loads(rot.read_text())
    assert data["sahil_twitter"] and "|" in data["sahil_twitter"][-1]
