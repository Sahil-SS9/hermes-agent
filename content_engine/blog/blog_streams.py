"""Blog stream configuration — the single source of per-stream truth.

Three streams map to the VERIFIED SahilBlog ingestion contract:
  - ai:      tier=pm + an AI-recognised tag (surfaced on /ai). source=research-paper.
  - pm:      tier=pm with non-AI tags. source=manual.
  - builder: tier=builder. source=gitradar or manual.

Voices match the real blog pages:
  - PM/AI essays: reflective, considered, read in one sitting; analytical and
    numbers-first for AI (ref: groktop.us "token-maxing").
  - Builders Log: direct, dense, skimmable in 30s; code-blocks-as-proof
    (ref: magnus919.com research-engine post).

Imagery reuses the sahil_twitter palette pool via imagery_transplant, so all
streams set image_palette_brand="sahil_twitter".
"""
from __future__ import annotations

STREAMS: dict[str, dict] = {
    "ai": {
        # Surfaced on /ai (filters tier=pm + AI tag).
        "tier": "pm",
        "base_tags": ["ai"],
        "source": "research-paper",
        "format": "essay",
        "voice": (
            "Analytical, numbers-first, thesis-driven (a la groktop token-maxing). "
            "Lead with a counterintuitive claim grounded in concrete figures; "
            "bold 'signal' callouts; clinical, no hype."
        ),
        "word_target": 1700,
        "section_target": 6,
        "sources": ["paper_synthesis", "ai_news", "ai_labs", "harness_cli"],
        "image_palette_brand": "sahil_twitter",
    },
    "pm": {
        "tier": "pm",
        "base_tags": ["product-management"],
        "source": "manual",
        "format": "essay",
        "voice": (
            "Reflective, considered, read in one sitting. Frameworks, AI adoption "
            "in enterprise SaaS, product strategy."
        ),
        "word_target": 1500,
        "section_target": 5,
        "sources": ["pm_frameworks", "pm_tools", "ai_adoption"],
        "image_palette_brand": "sahil_twitter",
    },
    "builder": {
        "tier": "builder",
        "base_tags": ["kensei", "build"],
        "source": "gitradar",
        "format": "essay",
        "voice": (
            "Direct, dense, skimmable in 30s. Code-blocks-as-proof (a la magnus919): "
            "every claim followed by a terminal command + real output. Practitioner."
        ),
        "word_target": 1400,
        "section_target": 5,
        "sources": ["gitradar", "kensei_app", "on_demand"],
        "image_palette_brand": "sahil_twitter",
    },
}


def tags_for(stream: str, topic_tags: list[str]) -> list[str]:
    """Merge a stream's base_tags with topic-specific tags, de-duplicated,
    order-preserved (base_tags first, then new topic_tags)."""
    base = STREAMS[stream]["base_tags"]
    merged: list[str] = list(base)
    for t in topic_tags or []:
        if t not in merged:
            merged.append(t)
    return merged