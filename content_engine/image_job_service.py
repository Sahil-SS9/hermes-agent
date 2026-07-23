"""Provider-free orchestration: stage trusted inputs, then prepare one backend plan."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from image_backends import ImageBackendPlan, ImageBackendRouter
from image_jobs import PreparedImageRequest
from image_reference_staging import (
    Fetcher,
    ReferenceStager,
    Resolver,
    SafeReferenceFetcher,
    StagedReference,
    default_resolver,
)


class BackendPlanner(Protocol):
    def plan(
        self,
        request: PreparedImageRequest,
        references: tuple[StagedReference, ...],
        *,
        job_dir: Path,
        staging_root: Path,
    ) -> ImageBackendPlan: ...


@dataclass(frozen=True)
class StagedImageJob:
    """One private job which still has no provider execution side effect."""

    staged_references: tuple[StagedReference, ...]
    plan: ImageBackendPlan


def _remove_unplanned_job(staging_root: Path, job_id: str) -> None:
    root = Path(staging_root).resolve(strict=True)
    candidate = root / job_id
    if not candidate.exists():
        return
    if candidate.is_symlink():
        raise RuntimeError("refusing to clean a symlinked staging job")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("refusing to clean a job outside the staging root") from exc
    shutil.rmtree(resolved)


def stage_and_plan_image_job(
    request: PreparedImageRequest,
    *,
    staging_root: Path,
    job_id: str,
    resolver: Optional[Resolver] = None,
    fetcher: Fetcher | None = None,
    router: BackendPlanner | None = None,
) -> StagedImageJob:
    """Consume the shared staging and backend contracts without executing either backend."""
    active_resolver = resolver or default_resolver
    active_fetcher = fetcher or SafeReferenceFetcher(resolver=active_resolver)
    stager = ReferenceStager(staging_root, resolver=active_resolver, fetcher=active_fetcher)
    staged = stager.stage(request.references, job_id=job_id)
    try:
        plan = (router or ImageBackendRouter()).plan(
            request,
            staged,
            job_dir=Path(staging_root) / job_id,
            staging_root=staging_root,
        )
    except Exception:
        _remove_unplanned_job(staging_root, job_id)
        raise
    return StagedImageJob(staged_references=staged, plan=plan)
