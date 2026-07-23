"""Provider-free reference catalogue contract (P11).

A stdlib-only layer that loads the canonical reference manifest and optional
core pack, validates them, and exposes typed records. It is intentionally
provider-free: nothing here calls Codex, OpenAI, FAL, ComfyUI, or any cloud
tool, and it writes no files.

Design notes
-----------
- The caller supplies the filesystem root. There is no implicit root and no
  global mutable state.
- A ``ReferenceRecord`` is immutable (``frozen=True``).
- ``ReferenceCatalog.load`` reads ``manifest.jsonl`` (the baseline) and the
  optional ``core-pack.jsonl`` (visually reviewed candidates). Core rows MUST
  resolve to a baseline row with the same path and hash.
- ``records_for_contract`` returns the core set — visually reviewed, but
  *not* generation-approved. Every real core row today is
  ``usage_classification == "review-required"`` and must fail closed for
  generation.
- ``references_for_generation`` fails closed unless an explicit
  ``usage_classification == "permitted"`` record is present. A future P10 owner
  would promote records individually after provenance review.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Mapping, Optional

__all__ = [
    "ReferenceRecord",
    "ReferenceCatalog",
    "CatalogError",
    "CatalogIntegrityError",
    "CatalogLoadError",
    "GenerationEligibilityError",
]

# Allowed classification values. "permitted" is the only one eligible for
# generation; "review-required" and "blocked" must fail closed.
_ALLOWED_CLASSIFICATIONS = {"permitted", "review-required", "blocked"}


class CatalogError(Exception):
    """Base class for reference-catalogue errors."""


class CatalogLoadError(CatalogError):
    """Raised when the manifest/core files cannot be read or parsed."""


class CatalogIntegrityError(CatalogError):
    """Raised when manifest/core integrity checks fail (hash, path, ID)."""


class GenerationEligibilityError(CatalogError):
    """Raised when a generation request cannot be satisfied fail-closed."""


@dataclass(frozen=True)
class ReferenceRecord:
    """Immutable reference-image record.

    Fields mirror the canonical manifest schema. ``core_*`` fields are only
    populated on core-pack rows; they default to ``None``/empty on baseline
    rows.
    """

    reference_id: str
    path: str  # relative to the catalogue root
    sha256: str
    usage_classification: str
    collection: str = ""
    source: str = ""
    provenance_state: str = ""
    bytes_: int = 0
    # core-pack only
    core_role: str = ""
    core_tag: str = ""
    curation_status: str = ""
    allowed_roles: tuple = field(default_factory=tuple)
    blocked_roles: tuple = field(default_factory=tuple)
    visual_rationale: str = ""
    is_core: bool = False

    def resolved_path(self, root: Path) -> Path:
        """Return the absolute path of this record under ``root``."""
        return (Path(root) / self.path).resolve(strict=False)


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out: list = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            s = raw.strip()
            if not s:
                continue
            try:
                out.append(json.loads(s))
            except json.JSONDecodeError as exc:
                raise CatalogLoadError(
                    f"{path.name}:{lineno}: invalid JSON ({exc.msg})"
                ) from exc
    return out


def _safe_rel(path_str: str, root: Path) -> str:
    """Validate and normalise a relative path.

    Rejects empty, absolute, escaping, or normalising paths. Returns the
    POSIX-style relative path.
    """
    if not path_str or not isinstance(path_str, str):
        raise CatalogIntegrityError(f"empty/non-string reference path: {path_str!r}")
    p = Path(path_str)
    # Reject absolute paths in the manifest.
    if p.is_absolute():
        raise CatalogIntegrityError(
            f"reference path must be relative, got absolute: {path_str!r}"
        )
    # Reject any component that escapes the root.
    if p.parts and p.parts[0] == "..":
        raise CatalogIntegrityError(
            f"reference path must not escape the root: {path_str!r}"
        )
    normal = p.as_posix()
    if ".." in p.parts:
        raise CatalogIntegrityError(
            f"reference path must not contain '..': {path_str!r}"
        )
    return normal


@dataclass
class ReferenceCatalog:
    """A loaded, validated reference catalogue bound to a root path."""

    root: Path
    baseline: dict = field(default_factory=dict)  # reference_id -> ReferenceRecord
    core: dict = field(default_factory=dict)  # reference_id -> ReferenceRecord

    # ---- iteration helpers ------------------------------------------------
    def __iter__(self) -> Iterator[ReferenceRecord]:
        for rid in self.baseline:
            yield self.baseline[rid]
        for rid in self.core:
            yield self.core[rid]

    def __len__(self) -> int:
        return len(self.baseline) + len(self.core)

    # ---- accessors ---------------------------------------------------------
    def get(self, reference_id: str) -> Optional[ReferenceRecord]:
        if reference_id in self.core:
            return self.core[reference_id]
        return self.baseline.get(reference_id)

    def all_records(self) -> list:
        return [*self.baseline.values(), *self.core.values()]

    def records_for_contract(self) -> list:
        """Return the visually reviewed core records.

        These are candidates, *not* generation-approved input. Today every
        real core row is ``review-required``.
        """
        return list(self.core.values())

    # ---- generation eligibility (fail-closed) -----------------------------
    def references_for_generation(self, ids: list) -> list:
        """Return the records usable for image generation.

        Fails closed: raises ``GenerationEligibilityError`` if any ID is
        absent, is not a core record, or has
        ``usage_classification != "permitted"``.
        """
        if not isinstance(ids, list):
            raise GenerationEligibilityError("ids must be a list")
        out: list = []
        for rid in ids:
            rec = self.get(rid)
            if rec is None:
                raise GenerationEligibilityError(
                    f"unknown reference id: {rid!r}"
                )
            if not rec.is_core:
                raise GenerationEligibilityError(
                    f"reference id is not a core record: {rid!r}"
                )
            if rec.usage_classification != "permitted":
                raise GenerationEligibilityError(
                    f"reference id {rid!r} is not permitted for generation "
                    f"(usage_classification={rec.usage_classification!r})"
                )
            out.append(rec)
        return out

    # ---- construction ------------------------------------------------------
    @classmethod
    def load(cls, root: Path) -> "ReferenceCatalog":
        """Load and validate the catalogue from ``root``.

        Reads ``manifest.jsonl`` (baseline) and the optional
        ``core-pack.jsonl``. Performs strict validation:

        - unique reference IDs within each file and across files;
        - safe relative paths (no absolute, no ``..``);
        - the referenced file must exist under ``root``;
        - declared SHA-256 must match the file content;
        - ``usage_classification`` must be one of the allowed values;
        - every core row must resolve to a baseline row with the same path
          and hash.
        """
        root = Path(root).resolve()
        manifest_path = root / "manifest.jsonl"
        if not manifest_path.exists():
            raise CatalogLoadError(
                f"manifest.jsonl not found under root {root}"
            )

        baseline_rows = _read_jsonl(manifest_path)
        baseline: dict = {}
        seen_ids: set = set()
        seen_paths: set = set()
        for idx, row in enumerate(baseline_rows):
            rid = row.get("reference_id")
            if not rid:
                raise CatalogIntegrityError(
                    f"manifest row {idx}: missing reference_id"
                )
            if rid in seen_ids:
                raise CatalogIntegrityError(
                    f"manifest row {idx}: duplicate reference_id {rid!r}"
                )
            rel = _safe_rel(row.get("path", ""), root)
            if rel in seen_paths:
                raise CatalogIntegrityError(
                    f"manifest row {idx}: duplicate path {rel!r}"
                )
            sha = row.get("sha256")
            if not sha or not isinstance(sha, str):
                raise CatalogIntegrityError(
                    f"manifest row {idx}: missing/invalid sha256 for {rid!r}"
                )
            cls_value = row.get("usage_classification", "review-required")
            if cls_value not in _ALLOWED_CLASSIFICATIONS:
                raise CatalogIntegrityError(
                    f"manifest row {idx}: invalid usage_classification "
                    f"{cls_value!r} for {rid!r}"
                )
            abs_path = (root / rel).resolve(strict=False)
            if not abs_path.exists():
                raise CatalogIntegrityError(
                    f"manifest row {idx}: missing file for {rid!r}: {rel}"
                )
            actual = _sha256_of(abs_path)
            if actual.lower() != sha.lower():
                raise CatalogIntegrityError(
                    f"manifest row {idx}: sha256 mismatch for {rid!r}: "
                    f"declared={sha!r} actual={actual!r}"
                )
            rec = ReferenceRecord(
                reference_id=rid,
                path=rel,
                sha256=sha.lower(),
                usage_classification=cls_value,
                collection=str(row.get("collection", "")),
                source=str(row.get("source", "")),
                provenance_state=str(row.get("provenance_state", "")),
                bytes_=int(row.get("bytes", 0) or 0),
                is_core=False,
            )
            baseline[rid] = rec
            seen_ids.add(rid)
            seen_paths.add(rel)

        # Core-pack rows are enrichments of baseline rows. A core row shares
        # its reference_id with exactly one baseline row (the same image,
        # visually reviewed). The baseline entry stays intact; the core entry
        # carries the extra core_* fields and is_core=True. A core row must
        # resolve to a baseline row with the same reference_id, path, and hash.
        core_rows = _read_jsonl(root / "core-pack.jsonl")
        core: dict = {}
        core_seen_ids: set = set()
        for idx, row in enumerate(core_rows):
            rid = row.get("reference_id")
            if not rid:
                raise CatalogIntegrityError(
                    f"core-pack row {idx}: missing reference_id"
                )
            if rid in core_seen_ids:
                raise CatalogIntegrityError(
                    f"core-pack row {idx}: duplicate core reference_id {rid!r}"
                )
            base = baseline.get(rid)
            if base is None:
                raise CatalogIntegrityError(
                    f"core-pack row {idx}: {rid!r} has no baseline row with "
                    f"the same reference_id"
                )
            rel = _safe_rel(row.get("path", ""), root)
            sha = row.get("sha256")
            if not sha or not isinstance(sha, str):
                raise CatalogIntegrityError(
                    f"core-pack row {idx}: missing/invalid sha256 for {rid!r}"
                )
            cls_value = row.get("usage_classification", "review-required")
            if cls_value not in _ALLOWED_CLASSIFICATIONS:
                raise CatalogIntegrityError(
                    f"core-pack row {idx}: invalid usage_classification "
                    f"{cls_value!r} for {rid!r}"
                )
            # Core path/hash must match the baseline row for the same id.
            if rel != base.path:
                raise CatalogIntegrityError(
                    f"core-pack row {idx}: {rid!r} path {rel!r} differs from "
                    f"baseline path {base.path!r}"
                )
            if sha.lower() != base.sha256:
                raise CatalogIntegrityError(
                    f"core-pack row {idx}: {rid!r} hash differs from baseline: "
                    f"core={sha!r} baseline={base.sha256!r}"
                )
            allowed = row.get("allowed_roles") or []
            blocked = row.get("blocked_roles") or []
            rec = ReferenceRecord(
                reference_id=rid,
                path=rel,
                sha256=sha.lower(),
                usage_classification=cls_value,
                collection=str(row.get("collection", base.collection)),
                source=str(row.get("source", base.source)),
                provenance_state=str(row.get("provenance_state", base.provenance_state)),
                bytes_=int(row.get("bytes", base.bytes_) or 0),
                core_role=str(row.get("core_role", "")),
                core_tag=str(row.get("core_tag", "")),
                curation_status=str(row.get("curation_status", "")),
                allowed_roles=tuple(allowed) if isinstance(allowed, list) else (),
                blocked_roles=tuple(blocked) if isinstance(blocked, list) else (),
                visual_rationale=str(row.get("visual_rationale", "")),
                is_core=True,
            )
            core[rid] = rec
            core_seen_ids.add(rid)

        return cls(root=root, baseline=baseline, core=core)
