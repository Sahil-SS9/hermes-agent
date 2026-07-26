from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "p13_catalogue_activation.py"


def _module():
    spec = importlib.util.spec_from_file_location("p13_catalogue_activation", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _catalogue(tmp_path: Path) -> tuple[Path, str]:
    payload = {
        "schema_version": 1,
        "status": "PRE_GO_PRIVATE_DISABLED_CATALOGUE",
        "source_denominator": 2,
        "accounting": {"registered": 0, "enabled": 0},
        "entries": [
            {
                "source_instance": "VPS:cron/jobs.json:source-a",
                "source_id": "source-a",
                "source_name": "a",
                "target_status": "ACTIVATION_CANDIDATE",
                "activation_wave": "WAVE_1_BOUNDED_SCRIPTS",
                "target_registration": False,
                "target_enabled": False,
                "blockers": [],
                "target_job": {
                    "id": "source-a",
                    "name": "a",
                    "prompt": "first",
                    "schedule": {"kind": "interval", "minutes": 15, "display": "every 15m"},
                    "repeat": {"times": None, "completed": 0},
                    "deliver": "local",
                    "skills": ["alpha"],
                    "no_agent": False,
                    "context_from": None,
                },
            },
            {
                "source_instance": "VPS:cron/jobs.json:source-b",
                "source_id": "source-b",
                "source_name": "b",
                "target_status": "ACTIVATION_CANDIDATE",
                "activation_wave": "WAVE_1_BOUNDED_SCRIPTS",
                "target_registration": False,
                "target_enabled": False,
                "blockers": [],
                "target_job": {
                    "id": "source-b",
                    "name": "b",
                    "prompt": "second",
                    "schedule": {"kind": "cron", "expr": "0 8 * * *", "display": "0 8 * * *"},
                    "repeat": {"times": None, "completed": 0},
                    "deliver": "local",
                    "skills": [],
                    "no_agent": False,
                    "context_from": ["source-a"],
                },
            },
        ],
    }
    path = tmp_path / "catalogue.json"
    text = json.dumps(payload, sort_keys=True) + "\n"
    path.write_text(text)
    path.chmod(0o600)
    return path, hashlib.sha256(text.encode()).hexdigest()


def test_load_catalogue_requires_private_mode_and_matching_checksum(tmp_path: Path) -> None:
    module = _module()
    path, digest = _catalogue(tmp_path)
    loaded = module.load_catalogue(path, digest)
    assert loaded["source_denominator"] == 2

    path.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        module.load_catalogue(path, digest)


def test_plan_is_pure_and_builds_disabled_create_contract(tmp_path: Path) -> None:
    module = _module()
    path, digest = _catalogue(tmp_path)
    catalogue = module.load_catalogue(path, digest)
    entries = module.select_wave(catalogue, "WAVE_1_BOUNDED_SCRIPTS")
    kwargs = module.build_create_kwargs(entries[0])
    assert kwargs["schedule"] == "every 15m"
    assert kwargs["enabled"] is False
    assert kwargs["context_from"] is None
    assert kwargs["skills"] == ["alpha"]


def test_stage_is_idempotent_and_remaps_context_dependencies(tmp_path: Path) -> None:
    module = _module()
    path, digest = _catalogue(tmp_path)
    catalogue = module.load_catalogue(path, digest)
    entries = module.select_wave(catalogue, "WAVE_1_BOUNDED_SCRIPTS")
    jobs: list[dict] = []
    updates: list[tuple[str, dict]] = []

    def create_job(**kwargs):
        job = {**kwargs, "id": f"target-{len(jobs) + 1}", "state": "paused"}
        jobs.append(job)
        return job

    def list_jobs(include_disabled=True):
        return list(jobs)

    def update_job(job_id, patch):
        updates.append((job_id, patch))
        return {"id": job_id, **patch}

    removed: list[str] = []
    receipt = tmp_path / "receipt.json"
    result = module.stage_wave(
        entries,
        catalogue_sha256=digest,
        receipt_path=receipt,
        create_job_fn=create_job,
        list_jobs_fn=list_jobs,
        update_job_fn=update_job,
        remove_job_fn=lambda job_id: removed.append(job_id) or True,
    )
    assert result["created"] == 2
    assert updates == [("target-2", {"context_from": ["target-1"]})]
    assert all(job["enabled"] is False for job in jobs)
    assert receipt.stat().st_mode & 0o777 == 0o600

    again = module.stage_wave(
        entries,
        catalogue_sha256=digest,
        receipt_path=receipt,
        create_job_fn=create_job,
        list_jobs_fn=list_jobs,
        update_job_fn=update_job,
        remove_job_fn=lambda job_id: True,
    )
    assert again["created"] == 0
    assert again["reused"] == 2


def test_mutating_actions_require_exact_go_authority() -> None:
    module = _module()
    for value in (None, "go", "!GO", " !go "):
        with pytest.raises(PermissionError):
            module.require_go_authority(value)
    module.require_go_authority("!go")


def test_select_authorised_wave_rejects_entries_not_explicitly_stage_approved(
    tmp_path: Path,
) -> None:
    module = _module()
    path, digest = _catalogue(tmp_path)
    catalogue = module.load_catalogue(path, digest)
    disposition = {
        "catalogue_sha256": digest,
        "entries": [
            {
                "source_instance": "VPS:cron/jobs.json:source-a",
                "audit_no_stage_state": "NO_STAGE_PENDING_ROW_PROOF",
            },
            {
                "source_instance": "VPS:cron/jobs.json:source-b",
                "audit_no_stage_state": "NO_STAGE_PENDING_ROW_PROOF",
            },
        ],
    }

    with pytest.raises(ValueError, match="not stage-approved"):
        module.select_authorised_wave(
            catalogue,
            disposition,
            "WAVE_1_BOUNDED_SCRIPTS",
        )


def test_main_plan_requires_a_checksum_bound_disposition_matrix(tmp_path: Path) -> None:
    module = _module()
    path, digest = _catalogue(tmp_path)

    with pytest.raises(SystemExit, match="--disposition is required"):
        module.main(
            [
                "plan",
                "--catalogue",
                str(path),
                "--sha256",
                digest,
                "--wave",
                "WAVE_1_BOUNDED_SCRIPTS",
            ]
        )


def test_select_authorised_wave_requires_complete_matrix_coverage(tmp_path: Path) -> None:
    module = _module()
    path, digest = _catalogue(tmp_path)
    catalogue = module.load_catalogue(path, digest)
    incomplete = {
        "catalogue_sha256": digest,
        "entries": [
            {
                "source_instance": "VPS:cron/jobs.json:source-a",
                "audit_no_stage_state": "STAGE_APPROVED",
            },
        ],
    }

    with pytest.raises(ValueError, match="entry set mismatch"):
        module.select_authorised_wave(
            catalogue,
            incomplete,
            "WAVE_1_BOUNDED_SCRIPTS",
        )
