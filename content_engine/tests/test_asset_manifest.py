"""Tests for blog.asset_manifest — provider-free asset provenance/QA (P11)."""

import json

import pytest

from blog import asset_manifest as am


_D = "a" * 64  # valid 64-char lowercase hex


def _good_record(key="hero", qa_state="pending", qa_metadata=None, **over):
    rec = {
        "asset_key": key,
        "article_id": "art-001",
        "visual_plan_digest": _D,
        "prompt_digest": _D,
        "reference_ids": ["ref-1"],
        "output_path": "output/art-001/hero.png",
        "output_digest": _D,
        "generated_at": "2026-07-23T10:00:00Z",
        "qa_state": qa_state,
    }
    if qa_metadata is not None:
        rec["qa_metadata"] = qa_metadata
    rec.update(over)
    return rec


# ---- deterministic JSON / parse round trip --------------------------------

def test_record_to_json_deterministic():
    r1 = am._build_record(_good_record())
    r2 = am._build_record(_good_record())
    assert r1.to_json() == r2.to_json()


def test_manifest_to_json_deterministic():
    m1 = am.build_asset_manifest("art-001", [_good_record()])
    m2 = am.build_asset_manifest("art-001", [_good_record()])
    assert m1.to_json() == m2.to_json()


def test_manifest_round_trip():
    m = am.build_asset_manifest("art-001", [_good_record(), _good_record("sec-1")])
    j = m.to_json()
    rt = am.AssetManifest.from_json(j)
    assert rt.to_json() == j
    assert len(rt) == 2
    assert {r.asset_key for r in rt} == {"hero", "sec-1"}


def test_manifest_from_dict_version_check():
    m = am.build_asset_manifest("art-001", [_good_record()])
    data = m.to_dict()
    data["version"] = "999"
    with pytest.raises(am.AssetManifestError, match="unsupported manifest version"):
        am.AssetManifest.from_dict(data)


def test_manifest_sorted_keys():
    m = am.build_asset_manifest("art-001", [_good_record()])
    data = json.loads(m.to_json())
    assert list(data.keys()) == sorted(data.keys())


# ---- reject escaping path, missing digests, duplicate key, unapproved ---

def test_absolute_output_path_rejected():
    with pytest.raises(am.AssetManifestError, match="must be relative"):
        am._build_record(_good_record(output_path="/etc/passwd"))


def test_escaping_output_path_rejected():
    with pytest.raises(am.AssetManifestError, match="escape the root"):
        am._build_record(_good_record(output_path="../escape.png"))


def test_missing_visual_plan_digest_rejected():
    with pytest.raises(am.AssetManifestError, match="visual_plan_digest"):
        am._build_record(_good_record(visual_plan_digest=""))


def test_bad_digest_format_rejected():
    with pytest.raises(am.AssetManifestError, match="64-char lowercase hex"):
        am._build_record(_good_record(visual_plan_digest="not-a-hash"))


def test_missing_prompt_digest_rejected():
    with pytest.raises(am.AssetManifestError, match="prompt_digest"):
        am._build_record(_good_record(prompt_digest=""))


def test_missing_output_digest_rejected():
    with pytest.raises(am.AssetManifestError, match="output_digest"):
        am._build_record(_good_record(output_digest=""))


def test_empty_reference_ids_rejected():
    with pytest.raises(am.AssetManifestError, match="reference_ids"):
        am._build_record(_good_record(reference_ids=[]))


def test_duplicate_asset_key_rejected():
    with pytest.raises(am.AssetManifestError, match="duplicate asset keys"):
        am.build_asset_manifest(
            "art-001",
            [_good_record(key="hero"), _good_record(key="hero")],
        )


def test_published_without_qa_metadata_rejected():
    with pytest.raises(am.AssetManifestError, match="requires explicit qa_metadata"):
        am._build_record(_good_record(qa_state="published"))


def test_approved_without_qa_metadata_rejected():
    with pytest.raises(am.AssetManifestError, match="requires explicit qa_metadata"):
        am._build_record(_good_record(qa_state="approved"))


def test_rejected_without_qa_metadata_rejected():
    with pytest.raises(am.AssetManifestError, match="requires explicit qa_metadata"):
        am._build_record(_good_record(qa_state="rejected"))


def test_approved_with_qa_metadata_accepted():
    rec = am._build_record(_good_record(
        qa_state="approved",
        qa_metadata={"reviewer": "kensei", "decision": "ship"},
    ))
    assert rec.qa_state == "approved"
    assert rec.qa_metadata["reviewer"] == "kensei"


def test_pending_without_qa_metadata_accepted():
    rec = am._build_record(_good_record(qa_state="pending"))
    assert rec.qa_state == "pending"
    assert rec.qa_metadata is None


def test_invalid_qa_state_rejected():
    with pytest.raises(am.AssetManifestError, match="qa_state must be one of"):
        am._build_record(_good_record(qa_state="shipped"))


# ---- no raw prompt/token-like fields are emitted -------------------------

def test_no_raw_prompt_field_in_record_dict():
    rec = am._build_record(_good_record())
    d = rec.to_dict()
    forbidden = {"api_key", "provider_token", "token", "secret", "raw_prompt", "prompt"}
    assert not (forbidden.intersection(d.keys()))


def test_no_raw_prompt_field_in_manifest_json():
    m = am.build_asset_manifest("art-001", [_good_record()])
    data = json.loads(m.to_json())
    forbidden = {"api_key", "provider_token", "token", "secret", "raw_prompt", "prompt"}
    for rec in data["records"]:
        assert not (forbidden.intersection(rec.keys()))


def test_record_rejects_secret_field_in_input():
    bad = _good_record()
    bad["api_key"] = "sk-xxx"
    with pytest.raises(am.AssetManifestError, match="must not contain secret/raw-prompt fields"):
        am._build_record(bad)


def test_record_rejects_raw_prompt_field_in_input():
    bad = _good_record()
    bad["raw_prompt"] = "a vivid hero scene"
    with pytest.raises(am.AssetManifestError, match="must not contain secret/raw-prompt fields"):
        am._build_record(bad)


def test_empty_article_id_rejected():
    with pytest.raises(am.AssetManifestError, match="article_id is required"):
        am.build_asset_manifest("", [_good_record()])


def test_empty_asset_key_rejected():
    with pytest.raises(am.AssetManifestError, match="asset_key is required"):
        am._build_record(_good_record(key=""))
