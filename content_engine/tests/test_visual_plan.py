"""Tests for blog.visual_plan — provider-free per-article visual plan (P11)."""

import json

import pytest

from blog import visual_plan as vp


_HERO = {
    "role": "hero",
    "key": "hero",
    "reference_ids": ["ref-1"],
    "layout": "architectural cross-section",
    "style": "ninth-observatory",
    "palette": "stone-and-brass",
    "motif": "control hall",
}

_SEC1 = {
    "role": "section",
    "key": "sec-mechanism",
    "reference_ids": ["ref-2"],
    "layout": "bento-grid",
    "style": "ninth-observatory",
    "palette": "stone-and-brass",
    "motif": "control hall",
    "section_heading": "The mechanism",
}

_SEC2 = {
    "role": "section",
    "key": "sec-cost",
    "reference_ids": ["ref-3"],
    "layout": "comparison matrix",
    "style": "ninth-observatory",
    "palette": "stone-and-brass",
    "motif": "control hall",
    "section_heading": "The cost",
}


def _good_plan_dict():
    return {
        "article_id": "art-001",
        "art_brief": "crossover point between local and API inference",
        "assets": [_HERO, _SEC1, _SEC2],
    }


# ---- valid hero + section records ---------------------------------------

def test_build_valid_hero_and_sections():
    plan = vp.build_visual_plan(**_good_plan_dict())
    assert plan.version == vp.VISUAL_PLAN_VERSION
    assert plan.article_id == "art-001"
    assert len(plan.assets) == 3
    heroes = [a for a in plan.assets if a.role == "hero"]
    assert len(heroes) == 1
    sections = [a for a in plan.assets if a.role == "section"]
    assert len(sections) == 2
    assert sections[0].section_heading == "The mechanism"


def test_build_hero_only_is_valid():
    d = _good_plan_dict()
    d["assets"] = [_HERO]
    plan = vp.build_visual_plan(**d)
    assert len(plan.assets) == 1
    assert plan.assets[0].role == "hero"


# ---- deterministic JSON --------------------------------------------------

def test_to_json_is_deterministic():
    plan1 = vp.build_visual_plan(**_good_plan_dict())
    plan2 = vp.build_visual_plan(**_good_plan_dict())
    j1 = plan1.to_json()
    j2 = plan2.to_json()
    assert j1 == j2
    # round-trip via from_dict
    rt = vp.VisualPlan.from_dict(json.loads(j1))
    assert rt.to_json() == j1


def test_to_json_sorted_keys():
    plan = vp.build_visual_plan(**_good_plan_dict())
    data = json.loads(plan.to_json())
    keys = list(data.keys())
    assert keys == sorted(keys)


# ---- locked shared style/palette/motif ----------------------------------

def test_shared_style_palette_motif_across_assets():
    plan = vp.build_visual_plan(**_good_plan_dict())
    styles = {a.style for a in plan.assets}
    palettes = {a.palette for a in plan.assets}
    motifs = {a.motif for a in plan.assets}
    assert len(styles) == 1
    assert len(palettes) == 1
    assert len(motifs) == 1
    assert plan.style == "ninth-observatory"
    assert plan.palette == "stone-and-brass"
    assert plan.motif == "control hall"


def test_section_can_vary_layout():
    plan = vp.build_visual_plan(**_good_plan_dict())
    layouts = {a.layout for a in plan.assets}
    # hero + two sections all have distinct layouts
    assert len(layouts) == 3


def test_out_of_family_style_rejected():
    d = _good_plan_dict()
    d["assets"][1] = dict(_SEC1, style="mythic-tech-codex")
    with pytest.raises(vp.VisualPlanError, match="does not match family style"):
        vp.build_visual_plan(**d)


def test_out_of_family_palette_rejected():
    d = _good_plan_dict()
    d["assets"][1] = dict(_SEC1, palette="neon-hud")
    with pytest.raises(vp.VisualPlanError, match="does not match family palette"):
        vp.build_visual_plan(**d)


def test_out_of_family_motif_rejected():
    d = _good_plan_dict()
    d["assets"][1] = dict(_SEC1, motif="specimen card")
    with pytest.raises(vp.VisualPlanError, match="does not match family motif"):
        vp.build_visual_plan(**d)


# ---- reject missing hero, duplicate keys, invalid layout/reference IDs ---

def test_missing_hero_rejected():
    d = _good_plan_dict()
    d["assets"] = [_SEC1, _SEC2]
    with pytest.raises(vp.VisualPlanError, match="exactly one hero"):
        vp.build_visual_plan(**d)


def test_two_heroes_rejected():
    d = _good_plan_dict()
    hero2 = dict(_HERO, key="hero-2")
    d["assets"] = [_HERO, hero2]
    with pytest.raises(vp.VisualPlanError, match="exactly one hero"):
        vp.build_visual_plan(**d)


def test_duplicate_keys_rejected():
    d = _good_plan_dict()
    d["assets"][1] = dict(_SEC1, key="hero")
    with pytest.raises(vp.VisualPlanError, match="duplicate asset keys"):
        vp.build_visual_plan(**d)


def test_empty_reference_ids_rejected():
    d = _good_plan_dict()
    d["assets"][0] = dict(_HERO, reference_ids=[])
    with pytest.raises(vp.VisualPlanError, match="reference_ids must be a non-empty list"):
        vp.build_visual_plan(**d)


def test_missing_reference_ids_rejected():
    d = _good_plan_dict()
    bad = dict(_HERO)
    del bad["reference_ids"]
    d["assets"][0] = bad
    with pytest.raises(vp.VisualPlanError, match="reference_ids"):
        vp.build_visual_plan(**d)


def test_empty_layout_rejected():
    d = _good_plan_dict()
    d["assets"][0] = dict(_HERO, layout="")
    with pytest.raises(vp.VisualPlanError, match="layout is required"):
        vp.build_visual_plan(**d)


def test_hero_with_section_heading_rejected():
    d = _good_plan_dict()
    d["assets"][0] = dict(_HERO, section_heading="intro")
    with pytest.raises(vp.VisualPlanError, match="hero asset must not have section_heading"):
        vp.build_visual_plan(**d)


def test_section_without_section_heading_rejected():
    d = _good_plan_dict()
    bad = dict(_SEC1)
    del bad["section_heading"]
    d["assets"][1] = bad
    with pytest.raises(vp.VisualPlanError, match="section asset must have section_heading"):
        vp.build_visual_plan(**d)


def test_empty_article_id_rejected():
    d = _good_plan_dict()
    d["article_id"] = ""
    with pytest.raises(vp.VisualPlanError, match="article_id is required"):
        vp.build_visual_plan(**d)


def test_empty_art_brief_rejected():
    d = _good_plan_dict()
    d["art_brief"] = "   "
    with pytest.raises(vp.VisualPlanError, match="art_brief is required"):
        vp.build_visual_plan(**d)


def test_from_dict_version_check():
    d = _good_plan_dict()
    plan = vp.build_visual_plan(**d)
    data = plan.to_dict()
    data["version"] = "999"
    with pytest.raises(vp.VisualPlanError, match="unsupported visual plan version"):
        vp.VisualPlan.from_dict(data)
