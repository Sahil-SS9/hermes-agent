"""Provider-free per-article visual-plan contract (P11).

Pure data contracts: versioned ``VisualPlan`` and ``VisualAssetPlan``
structures, plus a ``build_visual_plan`` constructor that validates one hero
plus zero-or-more section assets sharing a single style/palette/motif.

This module is provider-free: it never calls an LLM, a provider, writes
files, or selects an unreviewed image. JSON serialisation is deterministic.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional

__all__ = [
    "VisualAssetPlan",
    "VisualPlan",
    "VisualPlanError",
    "build_visual_plan",
]

VISUAL_PLAN_VERSION = "1"

# Allowed layout families (declared variants). Free-form but must be a
# non-empty string; we additionally validate that section layout variants are
# non-empty strings.


class VisualPlanError(Exception):
    """Raised when a visual plan cannot be built or is invalid."""


@dataclass(frozen=True)
class VisualAssetPlan:
    """A single asset (hero or section) inside a visual plan."""

    role: str  # "hero" or "section"
    key: str  # unique within the plan, e.g. "hero" or the section heading
    reference_ids: tuple  # exact reference IDs (validated by caller/catalogue)
    layout: str  # declared layout for this asset
    style: str
    palette: str
    motif: str
    section_heading: Optional[str] = None  # None for hero

    def to_dict(self) -> dict:
        d = asdict(self)
        d["reference_ids"] = list(self.reference_ids)
        return d


@dataclass(frozen=True)
class VisualPlan:
    """A per-article visual plan: one hero plus zero-or-more section assets."""

    version: str
    article_id: str
    art_brief: str
    style: str  # shared
    palette: str  # shared
    motif: str  # shared
    assets: tuple  # tuple[VisualAssetPlan, ...]

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "article_id": self.article_id,
            "art_brief": self.art_brief,
            "style": self.style,
            "palette": self.palette,
            "motif": self.motif,
            "assets": [a.to_dict() for a in self.assets],
        }

    def to_json(self) -> str:
        """Deterministic JSON serialisation (sorted keys, no trailing space)."""
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Mapping) -> "VisualPlan":
        version = str(data.get("version", ""))
        if version != VISUAL_PLAN_VERSION:
            raise VisualPlanError(
                f"unsupported visual plan version: {version!r}"
            )
        article_id = str(data.get("article_id", "")).strip()
        if not article_id:
            raise VisualPlanError("article_id is required")
        art_brief = str(data.get("art_brief", "")).strip()
        if not art_brief:
            raise VisualPlanError("art_brief is required")
        style = str(data.get("style", "")).strip()
        palette = str(data.get("palette", "")).strip()
        motif = str(data.get("motif", "")).strip()
        if not style or not palette or not motif:
            raise VisualPlanError(
                "style, palette and motif are all required"
            )
        raw_assets = data.get("assets", [])
        if not isinstance(raw_assets, list):
            raise VisualPlanError("assets must be a list")
        assets = tuple(_asset_from_dict(a, style, palette, motif) for a in raw_assets)
        _validate_assets(assets)
        return cls(
            version=version,
            article_id=article_id,
            art_brief=art_brief,
            style=style,
            palette=palette,
            motif=motif,
            assets=assets,
        )


def _asset_from_dict(data: Mapping, family_style: str, family_palette: str, family_motif: str) -> VisualAssetPlan:
    if not isinstance(data, Mapping):
        raise VisualPlanError(f"asset must be an object, got {type(data).__name__}")
    role = str(data.get("role", "")).strip()
    key = str(data.get("key", "")).strip()
    if role not in ("hero", "section"):
        raise VisualPlanError(f"asset role must be 'hero' or 'section', got {role!r}")
    if not key:
        raise VisualPlanError("asset key is required")
    ref_ids_raw = data.get("reference_ids")
    if not isinstance(ref_ids_raw, list) or not ref_ids_raw:
        raise VisualPlanError(
            f"asset {key!r}: reference_ids must be a non-empty list"
        )
    ref_ids = tuple(str(r).strip() for r in ref_ids_raw if str(r).strip())
    if not ref_ids:
        raise VisualPlanError(f"asset {key!r}: reference_ids must contain at least one id")
    layout = str(data.get("layout", "")).strip()
    if not layout:
        raise VisualPlanError(f"asset {key!r}: layout is required")
    # The shared style/palette/motif may be declared per-asset only if they
    # match the family values. Out-of-family values are rejected.
    a_style = str(data.get("style", family_style)).strip() or family_style
    a_palette = str(data.get("palette", family_palette)).strip() or family_palette
    a_motif = str(data.get("motif", family_motif)).strip() or family_motif
    if a_style != family_style:
        raise VisualPlanError(
            f"asset {key!r}: style {a_style!r} does not match family style {family_style!r}"
        )
    if a_palette != family_palette:
        raise VisualPlanError(
            f"asset {key!r}: palette {a_palette!r} does not match family palette {family_palette!r}"
        )
    if a_motif != family_motif:
        raise VisualPlanError(
            f"asset {key!r}: motif {a_motif!r} does not match family motif {family_motif!r}"
        )
    section_heading = data.get("section_heading")
    if section_heading is not None:
        section_heading = str(section_heading).strip() or None
    if role == "hero" and section_heading is not None:
        raise VisualPlanError(f"asset {key!r}: hero asset must not have section_heading")
    if role == "section" and not section_heading:
        raise VisualPlanError(f"asset {key!r}: section asset must have section_heading")
    return VisualAssetPlan(
        role=role,
        key=key,
        reference_ids=ref_ids,
        layout=layout,
        style=a_style,
        palette=a_palette,
        motif=a_motif,
        section_heading=section_heading,
    )


def _validate_assets(assets: tuple) -> None:
    if not assets:
        raise VisualPlanError("visual plan must have at least one asset")
    heroes = [a for a in assets if a.role == "hero"]
    if len(heroes) != 1:
        raise VisualPlanError(
            f"visual plan must have exactly one hero asset, got {len(heroes)}"
        )
    keys = [a.key for a in assets]
    if len(set(keys)) != len(keys):
        dup = [k for k in keys if keys.count(k) > 1]
        raise VisualPlanError(f"duplicate asset keys: {sorted(set(dup))}")


def build_visual_plan(
    article_id: str,
    art_brief: str,
    assets: list,
) -> VisualPlan:
    """Validate and build a ``VisualPlan``.

    ``assets`` is a list of dicts (or ``VisualAssetPlan``) each declaring a
    role, unique key, exact reference IDs, layout, and the shared
    style/palette/motif. Exactly one asset must be the hero; the rest are
    sections. The shared style/palette/motif are taken from the hero asset;
    every other asset must share them.
    """
    article_id = str(article_id).strip()
    if not article_id:
        raise VisualPlanError("article_id is required")
    art_brief = str(art_brief).strip()
    if not art_brief:
        raise VisualPlanError("art_brief is required")
    if not isinstance(assets, list) or not assets:
        raise VisualPlanError("assets must be a non-empty list")

    normalised: list = []
    for item in assets:
        if isinstance(item, VisualAssetPlan):
            normalised.append(item)
            continue
        if isinstance(item, Mapping):
            normalised.append(item)
            continue
        raise VisualPlanError(f"asset must be dict or VisualAssetPlan, got {type(item).__name__}")

    # Determine the family from the hero asset.
    hero_dicts = [a for a in normalised if (a.get("role") if isinstance(a, Mapping) else a.role) == "hero"]
    if len(hero_dicts) != 1:
        raise VisualPlanError(
            f"visual plan must have exactly one hero asset, got {len(hero_dicts)}"
        )
    hero = hero_dicts[0]
    if isinstance(hero, Mapping):
        family_style = str(hero.get("style", "")).strip()
        family_palette = str(hero.get("palette", "")).strip()
        family_motif = str(hero.get("motif", "")).strip()
    else:
        family_style = hero.style
        family_palette = hero.palette
        family_motif = hero.motif
    if not family_style or not family_palette or not family_motif:
        raise VisualPlanError(
            "hero asset must declare non-empty style, palette, motif"
        )

    built = tuple(_asset_from_dict(a, family_style, family_palette, family_motif) for a in normalised)
    _validate_assets(built)
    return VisualPlan(
        version=VISUAL_PLAN_VERSION,
        article_id=article_id,
        art_brief=art_brief,
        style=family_style,
        palette=family_palette,
        motif=family_motif,
        assets=built,
    )
