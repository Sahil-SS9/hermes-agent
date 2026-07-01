"""Tests for blog.schema_contract — enforce the Astro schema at write time."""
import pytest

import blog.schema_contract as sc


REAL_REPO = None  # use the real content.config.ts via SAHILBLOG_REPO


def test_loads_contract_from_real_schema():
    c = sc.load_contract(REAL_REPO)
    # Sanity: the real schema defines these.
    assert "manual" in c["sources"]
    assert "research-paper" in c["sources"]
    assert {"ai", "pm", "builder"} <= c["tiers"]
    assert "essay" in c["formats"]
    assert "evals" in c["tags"]
    assert "ai" in c["tags"]


def test_source_alias_manual_queue():
    fm = sc.normalise_frontmatter({"source": "manual_queue", "tags": []})
    assert fm["source"] == "manual"


def test_source_unknown_clamps_to_manual():
    fm = sc.normalise_frontmatter({"source": "wat", "tags": []})
    assert fm["source"] == "manual"


def test_source_valid_passthrough():
    fm = sc.normalise_frontmatter({"source": "research-paper", "tags": []})
    assert fm["source"] == "research-paper"


def test_tag_alias_evaluation_to_evals():
    fm = sc.normalise_frontmatter({"tags": ["ai", "evaluation"]})
    assert "evals" in fm["tags"]
    assert "evaluation" not in fm["tags"]


def test_invalid_tag_dropped():
    fm = sc.normalise_frontmatter({"tags": ["ai", "totally-made-up-tag-xyz"]})
    assert "ai" in fm["tags"]
    assert "totally-made-up-tag-xyz" not in fm["tags"]


def test_tags_deduped():
    fm = sc.normalise_frontmatter({"tags": ["ai", "ai", "AI"]})
    assert fm["tags"].count("ai") == 1


def test_tier_and_format_clamp():
    fm = sc.normalise_frontmatter(
        {"tier": "nonsense", "format": "nonsense", "tags": []})
    assert fm["tier"] == "pm"
    assert fm["format"] == "essay"


def test_valid_tier_format_passthrough():
    fm = sc.normalise_frontmatter(
        {"tier": "builder", "format": "blueprint", "tags": []})
    assert fm["tier"] == "builder"
    assert fm["format"] == "blueprint"


def test_normalise_preserves_other_fields():
    fm = sc.normalise_frontmatter(
        {"title": "X", "description": "Y", "approved": False,
         "source": "manual_queue", "tags": ["ai"]})
    assert fm["title"] == "X"
    assert fm["description"] == "Y"
    assert fm["approved"] is False


def test_tags_passthrough_when_schema_unreadable(tmp_path):
    # Point at a repo with no content.config.ts → allowed set empty → passthrough.
    sc.load_contract.cache_clear()
    kept, dropped = sc.normalise_tags(["anything", "goes"], frozenset())
    assert kept == ["anything", "goes"]
    assert dropped == []
