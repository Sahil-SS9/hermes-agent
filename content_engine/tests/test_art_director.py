"""Tests for blog.art_director — one rich art brief per article."""
import json

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
        "style_candidates": ["ninth-observatory", "technical-diorama", "baoyu-infographic"],
        "layout": "architectural cross-section with labelled chambers",
        "layout_variants": ["architectural cross-section", "control hall", "vault map"],
        "text_policy": "labels",
        "text_elements": ["API", "LOCAL", "CROSSOVER"],
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
    assert brief["style"] in {"ninth-observatory", "technical-diorama", "baoyu-infographic"}
    assert brief["layout"]
    assert brief["layout_variants"]
    assert brief["selection_seed"] == ad._selection_seed(_DRAFT)
    assert len(brief["selection_seed"]) == 16
    assert brief["style_candidates"]
    assert brief["style_native_compiler"].startswith("Redraft")
    assert brief["text_policy"] == "labels"
    assert brief["text_elements"] == ["API", "LOCAL", "CROSSOVER"]
    assert brief["palette"]
    assert brief["hero_prompt"]
    assert brief["section_prompts"]["The mechanism"]


def test_build_art_brief_handles_fenced_json():
    fenced = "Here you go:\n```json\n" + _good_brief_json() + "\n```\n"
    brief = ad.build_art_brief(_DRAFT, _HEADINGS, llm=lambda s, u: fenced)
    assert brief is not None
    assert brief["style"] in {"ninth-observatory", "technical-diorama", "baoyu-infographic"}


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
    assert "Hardware amortises" in captured["user"]
    assert "The mechanism" in captured["user"]


def test_compose_prompt_includes_shared_direction_and_labels():
    brief = {
        "style": "ninth-observatory",
        "layout": "architectural cross-section",
        "text_policy": "labels",
        "text_elements": ["API", "LOCAL"],
        "palette": "slate, brass",
        "motif": "rails",
        "art_direction": "vast hall.",
        "hero_prompt": "x",
        "section_prompts": {},
    }
    p = ad.compose_prompt("two curves crossing", brief)
    assert "The Ninth Observatory" in p
    assert "slate, brass" in p
    assert "rails" in p
    assert "two curves crossing" in p
    assert "Text is allowed" in p
    assert "API" in p and "LOCAL" in p
    assert "Creative Concept Direction" in p


def test_fallback_brief_picks_unused_style():
    recent = ["ninth-observatory", "mythic-tech-codex"]
    brief = ad.fallback_brief(_DRAFT, _HEADINGS, recent_styles=recent)
    assert brief["style"] in ad.STYLE_IDS
    assert brief["style"] not in recent
    assert brief["selection_seed"] == ad._selection_seed(_DRAFT)
    assert brief["hero_prompt"]
    assert set(brief["section_prompts"].keys()) == set(_HEADINGS)


def test_section_prompts_mapped_by_order_tolerant_of_drift():
    payload = json.loads(_good_brief_json())
    payload["section_prompts"] = []
    brief = ad.build_art_brief(
        _DRAFT, ["The mechanism"], llm=lambda s, u: json.dumps(payload))
    assert brief is not None
    assert brief["section_prompts"] == {}


def test_style_catalogue_includes_missing_workflow_and_design_modes():
    expected = {
        "baoyu-article-illustrator",
        "baoyu-infographic",
        "baoyu-comic",
        "technical-diorama",
        "data-atlas",
        "typographic-poster-design",
        "vintage-print-atelier",
        "photographic-realism",
        "pixel-art",
        "signal-hud",
    }
    assert expected.issubset(ad.STYLE_IDS)


def test_art_director_system_prompt_uses_creative_concept_direction_and_baoyu():
    captured = {}
    def spy(system, user):
        captured["system"] = system
        return _good_brief_json()

    ad.build_art_brief(_DRAFT, _HEADINGS, llm=spy)
    system = captured["system"]
    assert "Creative Concept Direction" in system
    assert "5-12 concrete interacting elements" in system
    assert "Baoyu" in system
    assert "21 layout" in system or "21 layout families" in system


def test_text_capable_styles_do_not_inherit_blanket_text_ban():
    brief = {
        "style": "typographic-poster-design",
        "layout": "Swiss grid poster",
        "text_policy": "typography",
        "text_elements": ["EVALS BEFORE VIBES"],
        "palette": "black, cream, signal red",
        "motif": "red proof stamp",
        "art_direction": "poster-grade hierarchy.",
        "hero_prompt": "x",
        "section_prompts": {},
    }
    p = ad.compose_prompt("a poster built from the title phrase", brief)
    assert "Typography is the image" in p
    assert "EVALS BEFORE VIBES" in p
    assert "No text" not in p


def test_no_text_styles_still_ban_readable_text():
    brief = {
        "style": "photographic-realism",
        "layout": "documentary still",
        "text_policy": "none",
        "text_elements": ["SHOULD NOT APPEAR"],
        "palette": "muted office grey",
        "motif": "paper audit trail",
        "art_direction": "grounded.",
        "hero_prompt": "x",
        "section_prompts": {},
    }
    p = ad.compose_prompt("a real office scene", brief)
    assert "No readable text" in p
    assert "SHOULD NOT APPEAR" not in p



def test_system_prompt_requests_constrained_exploration_candidates():
    captured = {}
    def spy(system, user):
        captured["system"] = system
        return _good_brief_json()

    ad.build_art_brief(_DRAFT, _HEADINGS, llm=spy)
    system = captured["system"]
    assert "constrained exploration" in system
    assert "style_candidates" in system
    assert "layout_variants" in system


def test_recent_style_penalty_can_override_safe_default():
    draft = {
        "title": "Bank of England reviews agentic AI rules for finance",
        "description": "Regulators test autonomous agents in financial markets",
        "body_md": "bank rules finance risk governance agentic ai capital controls",
        "stream": "pm",
    }
    payload = {
        "style": "mythic-tech-codex",
        "style_candidates": [
            "mythic-tech-codex", "baoyu-infographic", "ninth-observatory",
            "data-atlas", "vintage-print-atelier",
        ],
        "layout": "annotated plate",
        "layout_variants": ["annotated plate", "comparison matrix", "control hall"],
        "text_policy": "labels",
        "text_elements": ["RISK"],
        "palette": "black, brass, red",
        "motif": "regulatory seal",
        "art_direction": "dense finance control system.",
        "hero_prompt": "finance agents inside a regulatory machine",
        "section_prompts": [],
    }
    brief = ad.build_art_brief(
        draft,
        [],
        recent_styles=["mythic-tech-codex"],
        llm=lambda s, u: json.dumps(payload),
    )
    assert brief is not None
    assert brief["style"] != "mythic-tech-codex"
    assert brief["style"] in brief["style_candidates"]


def test_sampler_is_stable_but_varies_across_articles():
    candidates = [
        "mythic-tech-codex", "technical-diorama", "data-atlas",
        "baoyu-infographic", "photographic-realism",
    ]
    articles = [
        "NVIDIA BioNeMo accelerates Anthropic Claude science",
        "Ford rehires human engineers after AI fails quality checks",
        "How multi-agent AI economics influence business automation",
        "Bank of England agentic AI finance rules",
    ]
    chosen = []
    for title in articles:
        draft = {"title": title, "description": title, "body_md": title, "stream": "ai"}
        assert ad._selection_seed(draft) == ad._selection_seed(draft)
        first = ad._choose_style(draft, "mythic-tech-codex", [], candidates)
        second = ad._choose_style(draft, "mythic-tech-codex", [], candidates)
        assert first == second
        chosen.append(first)
    assert len(set(chosen)) >= 2


def test_compose_prompt_includes_style_native_redrafting_and_layout_variants():
    brief = {
        "style": "baoyu-infographic",
        "layout": "bento grid",
        "layout_variants": ["bento grid", "comparison matrix"],
        "style_native_compiler": ad._native_compiler_for("baoyu-infographic"),
        "text_policy": "labels",
        "text_elements": ["COST", "RISK"],
        "palette": "cream, teal, black",
        "motif": "numbered cards",
        "art_direction": "dense editorial information design.",
        "hero_prompt": "x",
        "section_prompts": {},
    }
    prompt = ad.compose_prompt("explain agent economics", brief)
    assert "Style-native prompt redraft rule" in prompt
    assert "dense infographic" in prompt
    assert "Allowed layout variation" in prompt
    assert "comparison matrix" in prompt



def test_sampler_override_resets_layout_to_chosen_style_grammar():
    draft = {
        "title": "Bank of England reviews agentic AI rules for finance",
        "description": "Regulators test autonomous agents in financial markets",
        "body_md": "bank rules finance risk governance agentic ai capital controls",
        "stream": "pm",
    }
    payload = {
        "style": "mythic-tech-codex",
        "style_candidates": ["mythic-tech-codex", "data-atlas", "ninth-observatory"],
        "layout": "antique scientific plate with specimen card",
        "layout_variants": ["specimen plate"],
        "text_policy": "labels",
        "text_elements": ["RISK"],
        "palette": "black, brass, red",
        "motif": "regulatory seal",
        "art_direction": "dense finance control system.",
        "hero_prompt": "finance agents inside a regulatory machine",
        "section_prompts": [],
    }
    brief = ad.build_art_brief(
        draft,
        [],
        recent_styles=["mythic-tech-codex"],
        llm=lambda s, u: json.dumps(payload),
    )
    assert brief is not None
    if brief["style"] != "mythic-tech-codex":
        chosen_native_layout = ad.STYLE_BY_ID[brief["style"]]["layout"]
        assert brief["layout"] == chosen_native_layout
        assert "antique scientific plate" not in brief["layout"]




def test_text_policy_normalisation_respects_style_defaults():
    assert ad._normalise_text_policy("ink-ember-studio", "labels") == "none"
    assert ad._normalise_text_policy("photographic-realism", "typography") == "none"
    assert ad._normalise_text_policy("typographic-poster-design", "labels") == "typography"
    assert ad._normalise_text_policy("baoyu-infographic", "none") == "labels"
