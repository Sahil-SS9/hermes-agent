#!/usr/bin/env python3
"""Fail-closed P13 cron catalogue staging and activation utility.

Planning is read-only. Staging always creates jobs disabled. Mutating actions
require the exact KENSEI_MIGRATION_AUTHORITY=!go environment value.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Callable

GO_AUTHORITY = "!go"
CATALOGUE_STATUS = "PRE_GO_PRIVATE_DISABLED_CATALOGUE"
MIGRATION_MARKER = "P13_DISABLED_CATALOGUE"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_go_authority(value: str | None) -> None:
    if value != GO_AUTHORITY:
        raise PermissionError(
            "mutating P13 catalogue actions require exact "
            "KENSEI_MIGRATION_AUTHORITY=!go"
        )


def load_catalogue(path: Path, expected_sha256: str) -> dict[str, Any]:
    path = path.resolve()
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise ValueError(f"private catalogue must have mode 0600, found {mode:04o}")
    actual = _sha256(path)
    if actual != expected_sha256:
        raise ValueError(
            f"catalogue checksum mismatch: expected {expected_sha256}, found {actual}"
        )
    catalogue = json.loads(path.read_text(encoding="utf-8"))
    if catalogue.get("status") != CATALOGUE_STATUS:
        raise ValueError(f"unexpected catalogue status: {catalogue.get('status')!r}")
    entries = catalogue.get("entries")
    if not isinstance(entries, list):
        raise ValueError("catalogue entries must be a list")
    if len(entries) != catalogue.get("source_denominator"):
        raise ValueError("catalogue denominator does not match entry count")
    if catalogue.get("accounting", {}).get("registered") != 0:
        raise ValueError("catalogue claims pre-existing target registrations")
    if catalogue.get("accounting", {}).get("enabled") != 0:
        raise ValueError("catalogue claims enabled target jobs")
    if any(entry.get("target_registration") or entry.get("target_enabled") for entry in entries):
        raise ValueError("catalogue contains a registered or enabled target entry")
    return catalogue


def select_wave(catalogue: dict[str, Any], wave: str) -> list[dict[str, Any]]:
    selected = [entry for entry in catalogue["entries"] if entry.get("activation_wave") == wave]
    if not selected:
        raise ValueError(f"no catalogue entries found for wave {wave!r}")
    for entry in selected:
        if entry.get("target_status") != "ACTIVATION_CANDIDATE":
            raise ValueError(
                f"wave {wave!r} includes non-candidate {entry.get('source_instance')}: "
                f"{entry.get('target_status')}"
            )
        if entry.get("blockers"):
            raise ValueError(f"candidate has blockers: {entry.get('source_instance')}")
        if not isinstance(entry.get("target_job"), dict):
            raise ValueError(f"candidate lacks target job: {entry.get('source_instance')}")
    return selected


def _schedule_text(schedule: Any, display: str | None = None) -> str:
    if isinstance(schedule, str):
        return schedule
    if not isinstance(schedule, dict):
        raise ValueError(f"unsupported schedule: {schedule!r}")
    kind = schedule.get("kind")
    if kind == "cron" and schedule.get("expr"):
        return str(schedule["expr"])
    if kind == "interval" and schedule.get("minutes") is not None:
        minutes = schedule["minutes"]
        return f"every {minutes}m"
    if kind == "once" and (schedule.get("run_at") or schedule.get("timestamp")):
        return str(schedule.get("run_at") or schedule.get("timestamp"))
    if display:
        return display
    raise ValueError(f"cannot convert schedule: {schedule!r}")


def build_create_kwargs(entry: dict[str, Any]) -> dict[str, Any]:
    job = entry["target_job"]
    if job.get("profile") or job.get("fallback_providers"):
        raise ValueError(
            f"unsupported legacy execution fields for {entry['source_instance']}"
        )
    if job.get("deliver") == "origin":
        raise ValueError(
            f"origin delivery cannot be reconstructed safely for {entry['source_instance']}"
        )
    repeat = job.get("repeat")
    repeat_times = repeat.get("times") if isinstance(repeat, dict) else repeat
    return {
        "prompt": job.get("prompt") or "",
        "schedule": _schedule_text(job.get("schedule"), job.get("schedule_display")),
        "name": job.get("name"),
        "repeat": repeat_times,
        "deliver": job.get("deliver") or "local",
        "skill": job.get("skill"),
        "skills": job.get("skills"),
        "model": job.get("model"),
        "provider": job.get("provider"),
        "base_url": job.get("base_url"),
        "script": job.get("script"),
        "context_from": None,
        "enabled_toolsets": job.get("enabled_toolsets"),
        "workdir": job.get("workdir"),
        "no_agent": bool(job.get("no_agent")),
        "enabled": False,
    }


def _target_fingerprint(entry: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(build_create_kwargs(entry)).encode()).hexdigest()


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)
    path.chmod(0o600)


def stage_wave(
    entries: list[dict[str, Any]],
    *,
    catalogue_sha256: str,
    receipt_path: Path,
    create_job_fn: Callable[..., dict[str, Any]],
    list_jobs_fn: Callable[..., list[dict[str, Any]]],
    update_job_fn: Callable[[str, dict[str, Any]], dict[str, Any] | None],
    remove_job_fn: Callable[[str], bool],
) -> dict[str, Any]:
    existing_jobs = list_jobs_fn(include_disabled=True)
    by_source: dict[str, dict[str, Any]] = {}
    for job in existing_jobs:
        origin = job.get("origin")
        if isinstance(origin, dict) and origin.get("migration") == MIGRATION_MARKER:
            source_instance = origin.get("source_instance")
            if source_instance:
                by_source[str(source_instance)] = job

    created_ids: list[str] = []
    mapping: dict[str, str] = {}
    source_id_mapping: dict[str, str] = {}
    reused = 0
    try:
        for entry in entries:
            source_instance = entry["source_instance"]
            fingerprint = _target_fingerprint(entry)
            current = by_source.get(source_instance)
            if current is not None:
                origin = current.get("origin") or {}
                if origin.get("catalogue_sha256") != catalogue_sha256:
                    raise ValueError(f"catalogue checksum drift for staged job {source_instance}")
                if origin.get("target_fingerprint") != fingerprint:
                    raise ValueError(f"target contract drift for staged job {source_instance}")
                if current.get("enabled") or current.get("state") != "paused":
                    raise ValueError(f"staged job is not paused: {current.get('id')}")
                target_id = current["id"]
                reused += 1
            else:
                kwargs = build_create_kwargs(entry)
                kwargs["origin"] = {
                    "migration": MIGRATION_MARKER,
                    "source_instance": source_instance,
                    "catalogue_sha256": catalogue_sha256,
                    "target_fingerprint": fingerprint,
                }
                created = create_job_fn(**kwargs)
                if created.get("enabled") or created.get("state") != "paused":
                    raise RuntimeError(f"create_job did not persist disabled: {source_instance}")
                target_id = created["id"]
                created_ids.append(target_id)
            mapping[source_instance] = target_id
            source_id_mapping[entry["source_id"]] = target_id

        current_ids = {job.get("id") for job in list_jobs_fn(include_disabled=True)} | set(mapping.values())
        for entry in entries:
            refs = entry["target_job"].get("context_from") or []
            if isinstance(refs, str):
                refs = [refs]
            remapped: list[str] = []
            for ref in refs:
                target_ref = source_id_mapping.get(ref, ref)
                if target_ref not in current_ids:
                    raise ValueError(
                        f"unresolved context dependency {ref!r} for {entry['source_instance']}"
                    )
                remapped.append(target_ref)
            if remapped:
                updated = update_job_fn(mapping[entry["source_instance"]], {"context_from": remapped})
                if updated is None:
                    raise RuntimeError(f"failed to update dependencies for {entry['source_instance']}")
    except Exception:
        for job_id in reversed(created_ids):
            remove_job_fn(job_id)
        raise

    receipt = {
        "schema_version": 1,
        "migration": MIGRATION_MARKER,
        "catalogue_sha256": catalogue_sha256,
        "wave": entries[0]["activation_wave"] if entries else None,
        "jobs": [
            {
                "source_instance": entry["source_instance"],
                "source_id": entry["source_id"],
                "target_id": mapping[entry["source_instance"]],
            }
            for entry in entries
        ],
    }
    _write_private_json(receipt_path, receipt)
    return {
        "wave": receipt["wave"],
        "created": len(created_ids),
        "reused": reused,
        "receipt": str(receipt_path.resolve()),
        "target_ids": [job["target_id"] for job in receipt["jobs"]],
    }


def _read_receipt(path: Path, catalogue_sha256: str) -> dict[str, Any]:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("migration") != MIGRATION_MARKER:
        raise ValueError("invalid migration receipt")
    if receipt.get("catalogue_sha256") != catalogue_sha256:
        raise ValueError("receipt catalogue checksum mismatch")
    return receipt


def enable_receipt(
    receipt: dict[str, Any],
    *,
    resume_job_fn: Callable[[str], dict[str, Any] | None],
    pause_job_fn: Callable[..., dict[str, Any] | None],
) -> dict[str, Any]:
    enabled: list[str] = []
    try:
        for item in receipt["jobs"]:
            target_id = item["target_id"]
            result = resume_job_fn(target_id)
            if result is None or not result.get("enabled"):
                raise RuntimeError(f"failed to enable {target_id}")
            enabled.append(target_id)
    except Exception:
        for target_id in reversed(enabled):
            pause_job_fn(target_id, reason="p13_wave_enable_rollback")
        raise
    return {"enabled": len(enabled), "target_ids": enabled}


def pause_receipt(
    receipt: dict[str, Any],
    *,
    pause_job_fn: Callable[..., dict[str, Any] | None],
) -> dict[str, Any]:
    paused: list[str] = []
    for item in receipt["jobs"]:
        target_id = item["target_id"]
        result = pause_job_fn(target_id, reason="p13_operator_rollback")
        if result is not None:
            paused.append(target_id)
    return {"paused": len(paused), "target_ids": paused}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "stage", "enable", "pause"])
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--wave")
    parser.add_argument("--receipt", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    catalogue = load_catalogue(args.catalogue, args.sha256)
    entries: list[dict[str, Any]] = []
    if args.action in {"plan", "stage"}:
        if not args.wave:
            raise SystemExit("--wave is required for plan/stage")
        entries = select_wave(catalogue, args.wave)
        if args.action == "plan":
            print(json.dumps({"wave": args.wave, "jobs": len(entries), "mutation": False}, indent=2))
            return 0

    if not args.receipt:
        raise SystemExit("--receipt is required for stage/enable/pause")

    from cron.jobs import create_job, list_jobs, pause_job, remove_job, resume_job, update_job

    if args.action == "pause":
        receipt = _read_receipt(args.receipt, args.sha256)
        print(json.dumps(pause_receipt(receipt, pause_job_fn=pause_job), indent=2))
        return 0

    require_go_authority(os.environ.get("KENSEI_MIGRATION_AUTHORITY"))
    if args.action == "stage":
        result = stage_wave(
            entries,
            catalogue_sha256=args.sha256,
            receipt_path=args.receipt,
            create_job_fn=create_job,
            list_jobs_fn=list_jobs,
            update_job_fn=update_job,
            remove_job_fn=remove_job,
        )
    else:
        receipt = _read_receipt(args.receipt, args.sha256)
        result = enable_receipt(receipt, resume_job_fn=resume_job, pause_job_fn=pause_job)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, PermissionError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
