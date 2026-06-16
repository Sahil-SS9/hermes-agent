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


def test_select_recipe_scene_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(lib, "_ROTATION", tmp_path / "rot.json")
    assert lib.select_recipe({"format": "scene", "title": "a calm dawn"}, "sahil_twitter") is None


def test_select_recipe_infographic(monkeypatch, tmp_path):
    monkeypatch.setattr(lib, "_ROTATION", tmp_path / "rot.json")
    draft = {"format": "infographic", "title": "5 ways to ship", "body_text": "a. b. c."}
    r = lib.select_recipe(draft, "sahil_twitter", seed=1)
    if r is None:
        pytest.skip("baoyu anchors not present on this box")
    assert r["layout"] in lib.LAYOUT_MAP["infographic"]
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


def test_select_recipe_records_rotation(monkeypatch, tmp_path):
    rot = tmp_path / "rot.json"
    monkeypatch.setattr(lib, "_ROTATION", rot)
    r = lib.select_recipe({"format": "infographic", "title": "t", "body_text": "a. b."},
                          "sahil_twitter", seed=2)
    if r is None:
        pytest.skip("baoyu anchors not present")
    data = json.loads(rot.read_text())
    assert data["sahil_twitter"] and "|" in data["sahil_twitter"][-1]
