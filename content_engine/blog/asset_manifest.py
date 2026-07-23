"""Provider-free asset-provenance/QA manifest contract (P11).

Pure output-accountability contracts: versioned ``AssetManifest`` /
``GeneratedAssetRecord``. A record binds article ID, visual-plan digest,
prompt digest, selected reference IDs, relative output path, output digest,
generation timestamp, and QA state.

It rejects absolute/escaping output paths, missing digests, duplicate asset
keys, and a ``published`` or ``approved`` state without explicit QA
metadata. It stores no API key, provider token, or raw private prompt beyond
a SHA-256 digest. Deterministic JSON serialisation and parse/round-trip
support.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator, Mapping, Optional

__all__ = [
    "GeneratedAssetRecord",
    "AssetManifest",
    "AssetManifestError",
    "ASSET_MANIFEST_VERSION",
    "QAState",
]

ASSET_MANIFEST_VERSION = "1"

QAState = str
_QA_STATES = {"pending", "approved", "rejected", "published"}


class AssetManifestError(Exception):
    """Raised when an asset manifest or record is invalid."""


def _validate_digest(name: str, value: str) -> str:
    if not isinstance(value, str) or not value:
        raise AssetManifestError(f"{name} must be a non-empty string")
    v = value.strip().lower()
    if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
        raise AssetManifestError(
            f"{name} must be a 64-char lowercase hex sha256 digest, got {value!r}"
        )
    return v


def _validate_rel_path(name: str, p: str) -> str:
    if not isinstance(p, str) or not p.strip():
        raise AssetManifestError(f"{name} must be a non-empty string")
    pp = Path(p)
    if pp.is_absolute():
        raise AssetManifestError(f"{name} must be relative, got absolute path {p!r}")
    if ".." in pp.parts:
        raise AssetManifestError(f"{name} must not escape the root (contains dots): {p!r}")
    if pp.parts and pp.parts[0] == "..":
        raise AssetManifestError(f"{name} must not escape the root: {p!r}")
    return pp.as_posix()


def _validate_ref_ids(ref_ids) -> tuple:
    if not isinstance(ref_ids, list) or not ref_ids:
        raise AssetManifestError("reference_ids must be a non-empty list")
    out = tuple(str(r).strip() for r in ref_ids if str(r).strip())
    if not out:
        raise AssetManifestError("reference_ids must contain at least one id")
    return out


@dataclass(frozen=True)
class GeneratedAssetRecord:
    """Immutable record of one generated asset provenance and QA state."""

    asset_key: str
    article_id: str
    visual_plan_digest: str
    prompt_digest: str
    reference_ids: tuple
    output_path: str
    output_digest: str
    generated_at: str
    qa_state: str
    qa_metadata: Optional[Mapping] = None

    def to_dict(self) -> dict:
        d = {
            "asset_key": self.asset_key,
            "article_id": self.article_id,
            "visual_plan_digest": self.visual_plan_digest,
            "prompt_digest": self.prompt_digest,
            "reference_ids": list(self.reference_ids),
            "output_path": self.output_path,
            "output_digest": self.output_digest,
            "generated_at": self.generated_at,
            "qa_state": self.qa_state,
        }
        if self.qa_metadata is not None:
            d["qa_metadata"] = dict(self.qa_metadata)
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _build_record(data: Mapping) -> GeneratedAssetRecord:
    if not isinstance(data, Mapping):
        raise AssetManifestError(f"record must be an object, got {type(data).__name__}")
    asset_key = str(data.get("asset_key", "")).strip()
    if not asset_key:
        raise AssetManifestError("asset_key is required")
    article_id = str(data.get("article_id", "")).strip()
    if not article_id:
        raise AssetManifestError("article_id is required")
    vpd = _validate_digest("visual_plan_digest", str(data.get("visual_plan_digest", "")))
    pd = _validate_digest("prompt_digest", str(data.get("prompt_digest", "")))
    ref_ids = _validate_ref_ids(data.get("reference_ids"))
    output_path = _validate_rel_path("output_path", str(data.get("output_path", "")))
    od = _validate_digest("output_digest", str(data.get("output_digest", "")))
    generated_at = str(data.get("generated_at", "")).strip()
    if not generated_at:
        raise AssetManifestError("generated_at is required")
    qa_state = str(data.get("qa_state", "")).strip()
    if qa_state not in _QA_STATES:
        raise AssetManifestError(
            f"qa_state must be one of {sorted(_QA_STATES)}, got {qa_state!r}"
        )
    qa_metadata = data.get("qa_metadata")
    if qa_state in ("approved", "rejected", "published") and not qa_metadata:
        raise AssetManifestError(
            f"qa_state {qa_state!r} requires explicit qa_metadata"
        )
    if qa_metadata is not None:
        if not isinstance(qa_metadata, Mapping):
            raise AssetManifestError("qa_metadata must be an object if present")
        qa_metadata = dict(qa_metadata)
    forbidden = {"api_key", "provider_token", "token", "secret", "raw_prompt", "prompt"}
    present_forbidden = forbidden.intersection(data.keys())
    if present_forbidden:
        raise AssetManifestError(
            f"record must not contain secret/raw-prompt fields: {sorted(present_forbidden)}"
        )
    return GeneratedAssetRecord(
        asset_key=asset_key,
        article_id=article_id,
        visual_plan_digest=vpd,
        prompt_digest=pd,
        reference_ids=ref_ids,
        output_path=output_path,
        output_digest=od,
        generated_at=generated_at,
        qa_state=qa_state,
        qa_metadata=qa_metadata,
    )


@dataclass
class AssetManifest:
    """A collection of generated-asset records with deterministic JSON."""

    version: str
    article_id: str
    records: tuple = field(default_factory=tuple)

    def __iter__(self) -> Iterator[GeneratedAssetRecord]:
        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "article_id": self.article_id,
            "records": [r.to_dict() for r in self.records],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Mapping) -> "AssetManifest":
        if not isinstance(data, Mapping):
            raise AssetManifestError(f"manifest must be an object, got {type(data).__name__}")
        version = str(data.get("version", ""))
        if version != ASSET_MANIFEST_VERSION:
            raise AssetManifestError(f"unsupported manifest version: {version!r}")
        article_id = str(data.get("article_id", "")).strip()
        if not article_id:
            raise AssetManifestError("article_id is required")
        raw_records = data.get("records", [])
        if not isinstance(raw_records, list):
            raise AssetManifestError("records must be a list")
        records = tuple(_build_record(r) for r in raw_records)
        keys = [r.asset_key for r in records]
        if len(set(keys)) != len(keys):
            dup = [k for k in keys if keys.count(k) > 1]
            raise AssetManifestError(f"duplicate asset keys: {sorted(set(dup))}")
        return cls(version=version, article_id=article_id, records=records)

    @classmethod
    def from_json(cls, text: str) -> "AssetManifest":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AssetManifestError(f"invalid JSON: {exc.msg}") from exc
        return cls.from_dict(data)


def build_asset_manifest(article_id: str, records: list) -> AssetManifest:
    """Build an ``AssetManifest`` from a list of record dicts."""
    article_id = str(article_id).strip()
    if not article_id:
        raise AssetManifestError("article_id is required")
    if not isinstance(records, list):
        raise AssetManifestError("records must be a list")
    built = tuple(_build_record(r) for r in records)
    keys = [r.asset_key for r in built]
    if len(set(keys)) != len(keys):
        dup = [k for k in keys if keys.count(k) > 1]
        raise AssetManifestError(f"duplicate asset keys: {sorted(set(dup))}")
    return AssetManifest(version=ASSET_MANIFEST_VERSION, article_id=article_id, records=built)
