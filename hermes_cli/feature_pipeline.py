#!/usr/bin/env python3
"""Feature Pipeline — Phase A front-half gates.

Provides:
- Artifact storage helpers (get_artifact_path, write_artifact, read_artifact)
- Gate functions for each pipeline stage (intake, research, prd, spec)
- Pipeline state machine (advance_pipeline, get_pipeline_status)
"""
import os
from typing import Optional


# ---------------------------------------------------------------------------
# Artifact storage helpers
# ---------------------------------------------------------------------------

def get_artifact_dir(base_dir: str, task_id: str) -> str:
    """Return the artifact directory path for a task."""
    return os.path.join(base_dir, task_id)


def get_artifact_path(base_dir: str, task_id: str, filename: str) -> str:
    """Return the full path to a specific artifact file."""
    return os.path.join(get_artifact_dir(base_dir, task_id), filename)


def write_artifact(base_dir: str, task_id: str, filename: str, content: str) -> None:
    """Write content to an artifact file, creating directories as needed."""
    artifact_dir = get_artifact_dir(base_dir, task_id)
    os.makedirs(artifact_dir, exist_ok=True)
    with open(os.path.join(artifact_dir, filename), "w") as f:
        f.write(content)


def read_artifact(base_dir: str, task_id: str, filename: str) -> Optional[str]:
    """Read content from an artifact file. Returns None if not found."""
    path = get_artifact_path(base_dir, task_id, filename)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Gate functions — return None if gate passes, reason string if blocked
# ---------------------------------------------------------------------------

# Section markers (case-insensitive matching)
_INTAKE_MARKERS = {
    "problem": ("## problem", "# problem", "problem:", "**problem**"),
    "success_criteria": (
        "## success criteria", "# success criteria",
        "success criteria:", "**success criteria**",
        "## success metric", "# success metric",
    ),
}

_RESEARCH_MARKERS = {
    "findings": ("## findings", "# findings", "findings:", "**findings**"),
}

_PRD_MARKERS = {
    "problem": ("## problem", "# problem", "problem:", "**problem**"),
    "users": ("## users", "# users", "users:", "**users**"),
    "scope": ("## scope", "# scope", "scope:", "**scope**"),
    "out_of_scope": (
        "## out of scope", "# out of scope",
        "out of scope:", "**out of scope**",
    ),
    "metrics": ("## metrics", "# metrics", "metrics:", "**metrics**"),
}

_SPEC_MARKERS = {
    "architecture": ("## architecture", "# architecture", "architecture:", "**architecture**"),
    "interfaces": ("## interfaces", "# interfaces", "interfaces:", "**interfaces**"),
    "test_strategy": (
        "## test strategy", "# test strategy",
        "test strategy:", "**test strategy**",
    ),
}


def _check_body_markers(body: Optional[str], markers: dict) -> Optional[str]:
    """Check that body contains all required section markers.

    Returns None if all present, or a human-readable reason string.
    """
    if not body:
        missing = [name.replace("_", " ").title() for name in markers]
        return f"Body is empty. Required sections: {', '.join(missing)}"

    body_lower = body.lower()
    missing = []
    for name, variants in markers.items():
        if not any(v in body_lower for v in variants):
            missing.append(name.replace("_", " ").title())

    if missing:
        return f"Missing required sections: {', '.join(missing)}"
    return None


def validate_intake_brief(body: Optional[str]) -> Optional[str]:
    """Gate: intake brief must have Problem and Success Criteria sections."""
    return _check_body_markers(body, _INTAKE_MARKERS)


def validate_research_artifact(artifact_dir: str) -> Optional[str]:
    """Gate: research-brief.md must exist and have a Findings section."""
    path = os.path.join(artifact_dir, "research-brief.md")
    if not os.path.exists(path):
        return "Missing research-brief.md artifact"
    with open(path) as f:
        content = f.read()

    if not content or not content.strip():
        return "research-brief.md is empty"

    return _check_body_markers(content, _RESEARCH_MARKERS)


def validate_prd_artifact(artifact_dir: str) -> Optional[str]:
    """Gate: prd.md must exist with Problem, Users, Scope, Out of Scope, Metrics."""
    path = os.path.join(artifact_dir, "prd.md")
    if not os.path.exists(path):
        return "Missing prd.md artifact"
    with open(path) as f:
        content = f.read()

    if not content or not content.strip():
        return "prd.md is empty"

    return _check_body_markers(content, _PRD_MARKERS)


def validate_spec_artifact(artifact_dir: str) -> Optional[str]:
    """Gate: spec.md must exist with Architecture, Interfaces, Test Strategy."""
    path = os.path.join(artifact_dir, "spec.md")
    if not os.path.exists(path):
        return "Missing spec.md artifact"
    with open(path) as f:
        content = f.read()

    if not content or not content.strip():
        return "spec.md is empty"

    return _check_body_markers(content, _SPEC_MARKERS)


# ---------------------------------------------------------------------------
# Pipeline state machine
# ---------------------------------------------------------------------------

# Stage order in the feature pipeline
PIPELINE_STAGES = ["research", "prd", "spec", "council"]

# Gate function mapping per stage
GATE_FUNCTIONS = {
    "research": validate_research_artifact,
    "prd": validate_prd_artifact,
    "spec": validate_spec_artifact,
    # council gate is Phase B — no gate function yet
}


def get_next_stage(current_stage: str) -> Optional[str]:
    """Return the next pipeline stage, or None if at the end."""
    try:
        idx = PIPELINE_STAGES.index(current_stage)
        if idx + 1 < len(PIPELINE_STAGES):
            return PIPELINE_STAGES[idx + 1]
    except ValueError:
        pass
    return None


def get_pipeline_status(task_id: str, artifact_base_dir: str) -> dict:
    """Return the current pipeline status for a task.

    Returns dict with keys:
        task_id: str
        current_stage: Optional[str]  # None if not in pipeline
        gate_status: str  # "pass", "fail", "pending", "unknown"
        gate_message: Optional[str]  # reason if gate fails
        next_stage: Optional[str]  # next stage if gate passes
    """
    # This is a stub — real implementation reads from DB
    return {
        "task_id": task_id,
        "current_stage": None,
        "gate_status": "unknown",
        "gate_message": None,
        "next_stage": None,
    }


def advance_pipeline(task_id: str, current_stage: str, artifact_base_dir: str) -> dict:
    """Try to advance a task to the next pipeline stage.

    Returns dict with keys:
        advanced: bool
        from_stage: str
        to_stage: Optional[str]
        gate_passed: bool
        gate_message: Optional[str]
    """
    gate_fn = GATE_FUNCTIONS.get(current_stage)
    if gate_fn is None:
        # No gate for this stage (e.g. council — Phase B)
        next_stage = get_next_stage(current_stage)
        return {
            "advanced": next_stage is not None,
            "from_stage": current_stage,
            "to_stage": next_stage,
            "gate_passed": True,
            "gate_message": None,
        }

    artifact_dir = os.path.join(artifact_base_dir, task_id)
    gate_result = gate_fn(artifact_dir)

    if gate_result is None:
        # Gate passed
        next_stage = get_next_stage(current_stage)
        return {
            "advanced": next_stage is not None,
            "from_stage": current_stage,
            "to_stage": next_stage,
            "gate_passed": True,
            "gate_message": None,
        }
    else:
        # Gate failed
        return {
            "advanced": False,
            "from_stage": current_stage,
            "to_stage": None,
            "gate_passed": False,
            "gate_message": gate_result,
        }
