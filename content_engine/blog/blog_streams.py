"""Blog stream configuration - the single source of per-stream truth.

Three streams map to the VERIFIED SahilBlog ingestion contract:
  - ai:      tier=pm + an AI-recognised tag (surfaced on /ai). source=research-paper.
  - pm:      tier=pm with non-AI tags. source=research-paper.
  - builder: tier=builder. source=manual.

Voices match the real blog pages and the back-population refined voice brief:
  - AI: numbers-first, thesis-driven; two modes — evergreen technical concept
    analysis AND strict-bar industry/economics analysis (compute, GPUs, pricing,
    acquisitions, regulation) with what/why/how/implications. Verify named events.
  - PM: research-to-PM translation — explain the research concept, apply it to
    PM work (workflows, adoption, skills, decisions). Mandatory reflective section.
  - Builder's Log: practitioner learning log — concept from paper/repo, then
    application and problem it solves, then hype-vs-reality reality-check.

Imagery reuses the sahil_twitter palette pool via imagery_transplant, so all
streams set image_palette_brand="sahil_twitter".
"""
from __future__ import annotations

STREAMS: dict[str, dict] = {
    "ai": {
        # Surfaced on /ai (tier=ai, its own page).
        "tier": "ai",
        "base_tags": ["ai"],
        "source": "research-paper",
        "format": "essay",
        "voice": (
            "Analytical, numbers-first, thesis-driven (a la groktop token-maxing). "
            "Lead with a counterintuitive, concretely-grounded claim; bold 'signal' "
            "callouts; clinical, no hype. Two modes: (a) evergreen technical concept "
            "analysis, (b) strict-bar industry/economics analysis (compute, GPUs, "
            "pricing, acquisitions, regulation) with what/why/how/implications."
        ),
        "structure": (
            "Open with the thesis. Explain the mechanism with real figures. For any "
            "NAMED current event (acquisition, regulation, product launch) you MUST "
            "only state facts that were verified via news_verify; if unverified, "
            "reframe to the durable pattern/economics and do not assert the event as "
            "fact. Close with implications."
        ),
        "word_target": 1700,
        "section_target": 6,
        "sources": ["paper_synthesis", "ai_news", "ai_labs", "harness_cli", "compute_economics"],
        "image_palette_brand": "sahil_twitter",
        # Blueprint format: architectural analysis with primitive mapping tables
        # and Mermaid diagrams. Rotate based on topic type.
        "formats": ["essay", "blueprint"],
    },
    "pm": {
        "tier": "pm",
        "base_tags": ["product-management"],
        "source": "research-paper",
        "format": "essay",
        "voice": (
            "Educational for the PM market: translate AI research findings into "
            "product-management practice. Explain the concept plainly, then apply it "
            "to PM work -- workflows, adoption, skills, decisions. Authoritative but "
            "accessible; minimal jargon. Personal experience is occasional seasoning, "
            "not the substance."
        ),
        "structure": (
            "1) the research concept explained simply; 2) why it matters for PMs; "
            "3) concrete application (workflow / adoption / skill); 4) a short "
            "'## Reflection' section with a considered personal take. Every post "
            "carries the reflective section."
        ),
        "word_target": 1500,
        "section_target": 5,
        "sources": ["paper_synthesis", "pm_frameworks", "ai_adoption", "pm_tools"],
        "image_palette_brand": "sahil_twitter",
    },
    "builder": {
        "tier": "builder",
        "base_tags": ["kensei", "build"],
        "source": "manual",
        "format": "essay",
        "voice": (
            "Practitioner learning log. Lead with a useful concept or idea found in a "
            "research paper or GitHub repo, then what it means in practice and what you "
            "built or explored with it. Explain tools for the TAKEAWAY, never the "
            "proprietary internals (guard the secret sauce). Honest hype-vs-reality "
            "throughout: share what others won't, call out oversold claims when the "
            "real practice is harder. Failures only as the occasional honest aside."
        ),
        "structure": (
            "1) the concept/idea (from a paper or repo) and why it is useful; 2) how it "
            "applies / what you built or explored and the problem it solves; 3) a candid "
            "reality-check vs the hype. Code snippets illustrate the concept, they do not "
            "expose internals."
        ),
        "word_target": 1400,
        "section_target": 5,
        "sources": ["paper_synthesis", "github_repos", "kensei_app", "tool_exploration"],
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
