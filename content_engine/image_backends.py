"""Provider-plan seam for the converged image-generation workflow.

This module creates private, auditable *plans*. It deliberately contains no
subprocess, HTTP, ComfyUI or publishing call. A later explicitly approved lane
may execute one of these plans after service-account and output-correlation
proof exists.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from image_jobs import PreparedImageRequest
from image_reference_staging import StagedReference

ExecutableLocator = Callable[[str], str | None]


class BackendPlanError(RuntimeError):
    """The selected backend cannot safely be planned or made ready."""


@dataclass(frozen=True)
class ImageBackendPlan:
    backend: str
    argv: tuple[str, ...]
    job_dir: Path
    instruction_path: Path
    manifest_path: Path
    execution_enabled: bool
    reason: str


class ImageBackendRouter:
    """Create one selected backend plan; never choose a fallback backend."""

    def __init__(self, *, executable_locator: ExecutableLocator = shutil.which) -> None:
        self._executable_locator = executable_locator

    @staticmethod
    def _trusted_job_directory(job_dir: Path, staging_root: Path) -> tuple[Path, Path]:
        root = Path(staging_root)
        if root.is_symlink():
            raise BackendPlanError("trusted staging root must not be a symlink")
        try:
            resolved_root = root.resolve(strict=True)
            resolved_job = Path(job_dir).resolve(strict=True)
        except OSError as exc:
            raise BackendPlanError(f"trusted staging root and job directory must exist: {exc}") from exc
        if not resolved_root.is_dir() or not resolved_job.is_dir() or Path(job_dir).is_symlink():
            raise BackendPlanError("trusted staging root and job directory must be real directories")
        try:
            resolved_job.relative_to(resolved_root)
        except ValueError as exc:
            raise BackendPlanError("job directory must be beneath the trusted staging root") from exc
        return resolved_root, resolved_job

    @staticmethod
    def _write_private_json(path: Path, payload: dict) -> None:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        path.chmod(0o600)

    @staticmethod
    def _write_private_text(path: Path, text: str) -> None:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
        path.chmod(0o600)

    def assert_runtime_ready(self, request: PreparedImageRequest, *, raise_on_missing: bool = True) -> bool:
        """Check only runtime availability; never execute a backend."""
        if request.backend == "local":
            if raise_on_missing:
                raise BackendPlanError("Local execution is disabled pending manual quality acceptance")
            return False
        if request.backend != "codex":
            raise BackendPlanError(f"unsupported backend: {request.backend}")
        if self._executable_locator("codex"):
            return True
        if raise_on_missing:
            raise BackendPlanError("Codex runtime is unavailable for the service account")
        return False

    def plan(
        self,
        request: PreparedImageRequest,
        references: Iterable[StagedReference],
        *,
        job_dir: Path,
        staging_root: Path,
    ) -> ImageBackendPlan:
        """Persist private instructions and provenance for exactly one backend."""
        root, job = self._trusted_job_directory(job_dir, staging_root)
        staged = tuple(references)
        for reference in staged:
            try:
                (root / reference.relative_path).resolve(strict=True).relative_to(root)
            except (OSError, ValueError) as exc:
                raise BackendPlanError("staged reference escaped the trusted staging root") from exc

        manifest_path = job / "image-job.json"
        instruction_path = job / "backend-instructions.md"
        if manifest_path.exists() or instruction_path.exists():
            raise BackendPlanError("image job metadata already exists")
        self._write_private_json(
            manifest_path,
            {
                "schema_version": 1,
                "backend": request.backend,
                "prompt": request.prompt,
                "style_id": request.style_id,
                "reference_sha256": [reference.sha256 for reference in staged],
                "references": [
                    {
                        "relative_path": reference.relative_path,
                        "sha256": reference.sha256,
                        "roles": sorted(reference.realised_roles),
                        "text_excerpt": reference.text_excerpt,
                    }
                    for reference in staged
                ],
                "preview_only": True,
            },
        )

        if request.backend == "codex":
            instruction = (
                "# Codex image job\n\n"
                "Read `image-job.json` in this directory. Generate exactly one original preview image "
                "from its prompt, named style and staged references. Do not publish, deliver, queue, "
                "commit, push, edit source material or invoke another image backend.\n\n"
                "If an image is generated, write `codex-completion.json` in this directory with the exact "
                "absolute source image path and its SHA-256. If you cannot generate it, state the failure in "
                "that same file. Do not select a fallback provider.\n"
            )
            self._write_private_text(instruction_path, instruction)
            return ImageBackendPlan(
                backend="codex",
                argv=(
                    "codex",
                    "exec",
                    f"Read and follow only {instruction_path}",
                ),
                job_dir=job,
                instruction_path=instruction_path,
                manifest_path=manifest_path,
                execution_enabled=False,
                reason="Codex execution requires separate runtime/auth and output-correlation approval",
            )

        if request.backend == "local":
            self._write_private_text(
                instruction_path,
                "# Local ComfyUI image job\n\n"
                "This request is recorded for manual quality evaluation only. No local workflow may be "
                "submitted until P12 GPU admission and explicit quality acceptance are complete.\n",
            )
            return ImageBackendPlan(
                backend="local",
                argv=(),
                job_dir=job,
                instruction_path=instruction_path,
                manifest_path=manifest_path,
                execution_enabled=False,
                reason="Local execution is manual quality evaluation only and remains disabled",
            )

        raise BackendPlanError(f"unsupported backend: {request.backend}")
