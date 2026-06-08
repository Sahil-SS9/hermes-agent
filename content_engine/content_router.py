"""Decide whether a draft becomes an AI infographic (Track B, Seedream) or an
illustrated/photographic image (Track A, krea + overlay).

Infographic when the post is structured/data-led (comparison, list, framework,
stats, how-to with steps); otherwise an illustrated scene. An explicit
draft['format'] always wins.
"""
from __future__ import annotations

_IG_PILLARS = {"data", "data_driven", "comparison", "framework", "list", "tips", "stats", "howto"}
_IG_CUES = (" vs ", " vs.", "do and don", "do/don", "don't", "step 1", "steps to",
            "reasons", "ways to", "framework", "comparison", "checklist", "top ", "x vs y")


def suggest_layout(draft: dict):
    """Pick a layout that matches the content's natural shape, else None (let the
    brand's weighted rotation choose)."""
    t = ((draft.get("title") or "") + " " + (draft.get("body_text") or "")).lower()
    if " vs " in t or " vs." in t or "versus" in t or "comparison" in t:
        return "binary-comparison"
    if "do/don" in t or "do and don" in t or "don't" in t or "do's" in t:
        return "do-dont"
    if any(k in t for k in ("steps", "ways to", "reasons", "tips", "checklist", "top ")):
        return "feature-list"
    if "funnel" in t or "stages" in t or "pipeline" in t:
        return "funnel"
    if "framework" in t or "matrix" in t or "quadrant" in t:
        return "priority-quadrants"
    return None


def is_infographic(draft: dict) -> bool:
    fmt = (draft.get("format") or "").lower()
    if fmt == "infographic":
        return True
    if fmt in ("illustration", "photo", "scene", "hero"):
        return False
    pillar = (draft.get("pillar") or "").lower()
    ctype = (draft.get("content_type") or "").lower()
    if pillar in _IG_PILLARS or ctype in _IG_PILLARS:
        return True
    text = ((draft.get("title") or "") + " " + (draft.get("body_text") or "")).lower()
    return any(c in text for c in _IG_CUES)
