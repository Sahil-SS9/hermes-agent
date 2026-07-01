"""Tests for blog.art_director — one art brief per article."""
import json

import pytest

import blog.art_director as ad


_DRAFT = {
    "title": "The crossover point: when local inference beats the API",
    "description": "API cost vs hardware amortisation.",
    "body_md": "# X\n\nFor two years the API won.\n\n## The mechanism\n\nHardware amortises.",
    "stream": "ai",
}
_HEADINGS = ["The mechanism"]


def _good_brief_json():
    return json.dumps({
        "style": "ninth-observatory",
        "palette": "slate, brass, amber",
        "motif": "converging rails",
        "art_direction": "vast architectural space, one warm focal light.",
        "hero_prompt": "two cost curves crossing inside a vast engine hall",
        "section_prompts": [
            {"heading": "The mechanism", "prompt": "amortising hardware as stone foundations"}
        ],
    })


def test_build_art_brief_parses_valid_llm_output():
    brief = ad.build_art_brief(_DRAFT, _HEADINGS, llm=lambda s, u: _good_brief_json())
    assert brief is not None
    assert brief["style"] == "ninth-observatory"
    assert brief["palette"]
    assert brief["hero_prompt"]
    assert brief["section_prompts"]["The mechanism"]


def test_build_art_brief_handles_fenced_json():
    fenced = "Here you go:\n```json\n" + _good_brief_json() + "\n```\n"
    brief = ad.build_art_brief(_DRAFT, _HEADINGS, llm=lambda s, u: fenced)
    assert brief is not None
    assert brief["style"] == "ninth-observatory"


def test_build_art_brief_rejects_unknown_style():
    bad = _good_brief_json().replace("ninth-observatory", "not-a-real-style")
    brief = ad.build_art_brief(_DRAFT, _HEADINGS, llm=lambda s, u: bad)
    assert brief is None


def test_build_art_brief_none_on_unparseable():
    brief = ad.build_art_brief(_DRAFT, _HEADINGS, llm=lambda s, u: "sorry, no JSON here")
    assert brief is None


def test_build_art_brief_none_on_llm_exception():
    def boom(s, u):
        raise RuntimeError("model down")
    assert ad.build_art_brief(_DRAFT, _HEADINGS, llm=boom) is None


def test_recent_styles_in_system_prompt():
    captured = {}
    def spy(system, user):
        captured["system"] = system
        return _good_brief_json()
    ad.build_art_brief(_DRAFT, _HEADINGS, recent_styles=["saga-noir", "pixel-art"], llm=spy)
    assert "saga-noir" in captured["system"]
    assert "pixel-art" in captured["system"]


def test_full_article_in_user_prompt():
    captured = {}
    def spy(system, user):
        captured["user"] = user
        return _good_brief_json()
    ad.build_art_brief(_DRAFT, _HEADINGS, llm=spy)
    assert "Hardware amortises" in captured["user"]  # body, not just title
    assert "The mechanism" in captured["user"]


def test_compose_prompt_includes_shared_direction():
    brief = {
        "style": "ninth-observatory", "palette": "slate, brass",
        "motif": "rails", "art_direction": "vast hall.",
        "hero_prompt": "x", "section_prompts": {},
    }
    p = ad.compose_prompt("two curves crossing", brief)
    assert "The Ninth Observatory" in p
    assert "slate, brass" in p
    assert "rails" in p
    assert "two curves crossing" in p
    assert "No text" in p  # global rules appended


def test_fallback_brief_picks_unused_style():
    recent = ["ninth-observatory", "mythic-tech-codex"]
    brief = ad.fallback_brief(_DRAFT, _HEADINGS, recent_styles=recent)
    assert brief["style"] in ad.STYLE_IDS
    assert brief["style"] not in recent
    assert brief["hero_prompt"]
    assert set(brief["section_prompts"].keys()) == set(_HEADINGS)


def test_section_prompts_mapped_by_order_tolerant_of_drift():
    # LLM returns fewer section prompts than headings — extras just absent.
    payload = json.loads(_good_brief_json())
    payload["section_prompts"] = []  # none returned
    brief = ad.build_art_brief(
        _DRAFT, ["The mechanism"], llm=lambda s, u: json.dumps(payload))
    assert brief is not None
    assert brief["section_prompts"] == {}
