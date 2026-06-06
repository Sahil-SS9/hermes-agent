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


def validate_council_artifact(artifact_dir: str) -> Optional[str]:
    """Gate: council-verdict.md must exist and contain APPROVED.

    If the verdict artifact doesn't exist yet, this runs the council
    deliberation (LLM calls). This is intentionally expensive — it only
    fires once per council stage entry.

    Returns None if APPROVED, reason string if REVISE or error.
    """
    verdict_path = os.path.join(artifact_dir, "council-verdict.md")

    if not os.path.exists(verdict_path):
        # No verdict yet — run the deliberation
        import logging
        _log = logging.getLogger(__name__)
        # Extract task_id from artifact_dir (last path component)
        task_id = os.path.basename(os.path.normpath(artifact_dir))
        try:
            from hermes_cli.council import deliberate as run_council
            verdict = run_council(task_id, artifact_dir)
            if verdict.verdict == "APPROVED":
                return None
            else:
                # Build REVISE reason from issues
                issue_lines = []
                for issue in verdict.issues:
                    sev = issue.get("severity", "medium")
                    desc = issue.get("description", "")
                    issue_lines.append(f"[{sev.upper()}] {desc}")
                reason = "Council REVISE. Issues:\n" + "\n".join(issue_lines)
                if verdict.chairman_rationale:
                    reason += f"\n\nChairman: {verdict.chairman_rationale}"
                return reason
        except Exception as exc:
            _log.exception("Council deliberation failed for %s", task_id)
            return f"Council deliberation failed: {exc}"

    # Verdict artifact exists — read and check
    try:
        with open(verdict_path) as f:
            content = f.read()
    except OSError as exc:
        return f"Cannot read council-verdict.md: {exc}"

    if not content or not content.strip():
        return "council-verdict.md is empty"

    # Parse the verdict from the markdown
    content_lower = content.lower()
    if "**verdict: approved**" in content_lower or "verdict: approved" in content_lower:
        return None

    # Extract issues for REVISE reason
    if "**verdict: revise**" in content_lower or "verdict: revise" in content_lower:
        # Try to extract issues from the markdown
        import re
        issue_matches = re.findall(
            r"- \*?\*?\[(CRITICAL|HIGH|MEDIUM|LOW)\]\*?\*?\s+(.+)",
            content, re.IGNORECASE,
        )
        if issue_matches:
            issue_lines = [f"[{m[0].upper()}] {m[1]}" for m in issue_matches]
            return "Council REVISE. Issues:\n" + "\n".join(issue_lines)
        return "Council REVISE — see council-verdict.md for details"

    # Verdict unclear — treat as REVISE
    return "Council verdict unclear — see council-verdict.md"


def validate_tech_review_artifact(artifact_dir: str) -> Optional[str]:
    """Gate: tech-review.md must exist with Architecture, Risk Assessment sections."""
    path = os.path.join(artifact_dir, "tech-review.md")
    if not os.path.exists(path):
        return "Missing tech-review.md artifact"
    with open(path) as f:
        content = f.read()

    if not content or not content.strip():
        return "tech-review.md is empty"

    _MARKERS = {
        "architecture": ("## architecture", "# architecture", "architecture:", "**architecture**"),
        "risks": ("## risks", "# risks", "risks:", "**risks**", "## risk assessment", "# risk assessment"),
    }
    return _check_body_markers(content, _MARKERS)


def validate_decompose_artifact(artifact_dir: str) -> Optional[str]:
    """Gate: decompose-output.md must exist with child task listing.

    The decompose stage breaks the parent task into child tasks, each
    carrying ## Acceptance Criteria and ## Test Plan (WS-1 contract).
    This gate verifies the decomposition file was produced and lists
    at least one child task with both required sections.
    """
    path = os.path.join(artifact_dir, "decompose-output.md")
    if not os.path.exists(path):
        return "Missing decompose-output.md artifact"
    try:
        with open(path) as f:
            content = f.read()
    except OSError as exc:
        return f"Cannot read decompose-output.md: {exc}"

    if not content or not content.strip():
        return "decompose-output.md is empty"

    # At minimum: a child tasks section and at least one AC + Test Plan pair
    content_lower = content.lower()
    has_children = any(
        marker in content_lower
        for marker in ("## child tasks", "# child tasks", "child tasks:", "**child tasks**")
    )
    if not has_children:
        return "Missing required section: Child Tasks"

    # The decomposition may inline multiple children, each with AC + Test Plan.
    # We require at least one AC marker and one Test Plan marker anywhere
    # in the document — the per-child validation is the WS-1 contract gate
    # on the actual child tasks, not this parent-level summary.
    has_ac = any(
        marker in content_lower
        for marker in (
            "## acceptance criteria", "acceptance criteria:",
            "## ac", "# ac",
        )
    )
    has_test_plan = any(
        marker in content_lower
        for marker in (
            "## test plan", "## test strategy", "test plan:",
            "**test plan**",
        )
    )
    missing = []
    if not has_ac:
        missing.append("Acceptance Criteria")
    if not has_test_plan:
        missing.append("Test Plan")
    if missing:
        return f"Decomposition missing required sections: {', '.join(missing)}"
    return None


# ---------------------------------------------------------------------------
# Audit gate (Phase D)
# ---------------------------------------------------------------------------

# Quan's six-worker fleet writes one sub-section per reviewer. The aggregated
# verdict is parsed from the **Verdict:** line. kensei-review adds its own
# section independently — both must be present for the gate to pass.
_AUDIT_FLEET_REVIEWERS = ("code", "arch", "perf", "security", "ux")
_AUDIT_REQUIRED_SECTIONS = (
    "## quan-fleet", "## kensei-review", "## verdict",
)


def _parse_audit_verdict(content: str) -> Optional[str]:
    """Extract the aggregated verdict from an audit-report.md.

    Recognised forms (case-insensitive):
        **Verdict: PASS**
        **Verdict: CONDITIONAL**
        **Verdict: BLOCKED**
    Returns the uppercased verdict string, or None if not found.
    """
    import re
    m = re.search(
        r"\*\*\s*verdict\s*:\s*(PASS|CONDITIONAL|BLOCKED)\s*\*\*",
        content, re.IGNORECASE,
    )
    if m:
        return m.group(1).upper()
    # Fallback: plain "Verdict: PASS" line
    m = re.search(
        r"^verdict\s*:\s*(PASS|CONDITIONAL|BLOCKED)\s*$",
        content, re.IGNORECASE | re.MULTILINE,
    )
    if m:
        return m.group(1).upper()
    return None


def _check_audit_fleet_section(content: str) -> Optional[str]:
    """Verify the quan-fleet block contains all five reviewer sub-verdicts."""
    import re
    fleet_block = re.search(
        r"##\s*quan-fleet\s*(.+?)(?=^##\s|\Z)",
        content, re.IGNORECASE | re.DOTALL | re.MULTILINE,
    )
    if not fleet_block:
        return "Missing quan-fleet section"
    body = fleet_block.group(1)
    # Strip all bold markers before matching so both "**code:** PASS" and
    # "code: PASS" match identically. This is a lenient parser that prefers
    # not to miss valid input over strict formatting requirements.
    import re
    clean = re.sub(r'\*{1,2}', '', body)
    missing = []
    for reviewer in _AUDIT_FLEET_REVIEWERS:
        if not re.search(
            rf"\b{re.escape(reviewer)}\s*:\s*(PASS|CONDITIONAL|BLOCKED)\b",
            clean, re.IGNORECASE,
        ):
            missing.append(reviewer)
    if missing:
        return f"Quan fleet missing verdicts for: {', '.join(missing)}"
    return None


def _check_kensei_review_section(content: str) -> Optional[str]:
    """Verify the kensei-review section is present and non-empty."""
    import re
    block = re.search(
        r"##\s*kensei-review\s*(.+?)(?=^##\s|\Z)",
        content, re.IGNORECASE | re.DOTALL | re.MULTILINE,
    )
    if not block:
        return "Missing kensei-review section"
    body = block.group(1).strip()
    if len(body) < 50:
        return "kensei-review section is too short (need substantive content)"
    return None


def validate_audit_artifact(artifact_dir: str) -> Optional[str]:
    """Gate: audit-report.md must exist with quan fleet + kensei-review + verdict.

    Verdict semantics (design doc §3 [11]):
        - PASS        — gate passes; advance to final_sign_off.
        - CONDITIONAL — gate passes; auto-creates a follow-up task so the
                        conditional issues are tracked, then advance.
        - BLOCKED     — gate fails; bounces to spec (capped) so the spec
                        author can address the blockers.

    Returns None if PASS/CONDITIONAL, reason string if BLOCKED or invalid.
    """
    path = os.path.join(artifact_dir, "audit-report.md")
    if not os.path.exists(path):
        return "Missing audit-report.md artifact"
    try:
        with open(path) as f:
            content = f.read()
    except OSError as exc:
        return f"Cannot read audit-report.md: {exc}"

    if not content or not content.strip():
        return "audit-report.md is empty"

    content_lower = content.lower()
    missing_sections = [
        marker for marker in _AUDIT_REQUIRED_SECTIONS
        if marker not in content_lower
    ]
    if missing_sections:
        return f"audit-report.md missing sections: {', '.join(missing_sections)}"

    fleet_err = _check_audit_fleet_section(content)
    if fleet_err:
        return fleet_err

    review_err = _check_kensei_review_section(content)
    if review_err:
        return review_err

    verdict = _parse_audit_verdict(content)
    if verdict is None:
        return "audit-report.md has no parseable Verdict line (PASS/CONDITIONAL/BLOCKED)"

    if verdict == "BLOCKED":
        return "Audit BLOCKED — see audit-report.md for blocker list"
    # PASS or CONDITIONAL: gate passes. The dispatcher reads the verdict
    # via get_audit_verdict_for_dispatch() to decide whether to spawn a
    # follow-up task for CONDITIONAL issues.
    return None


def get_audit_verdict(artifact_dir: str) -> Optional[str]:
    """Read the audit verdict from audit-report.md. Returns None on miss."""
    path = os.path.join(artifact_dir, "audit-report.md")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            content = f.read()
    except OSError:
        return None
    return _parse_audit_verdict(content)


def validate_document_artifact(artifact_dir: str) -> Optional[str]:
    """Gate: docs-output.md must exist with sections for the wiki entry."""
    path = os.path.join(artifact_dir, "docs-output.md")
    if not os.path.exists(path):
        return "Missing docs-output.md artifact"
    try:
        with open(path) as f:
            content = f.read()
    except OSError as exc:
        return f"Cannot read docs-output.md: {exc}"

    if not content or not content.strip():
        return "docs-output.md is empty"

    # Light is responsible for docs; require an overview + usage section so
    # the wiki entry is self-contained.
    _MARKERS = {
        "overview": ("## overview", "# overview", "overview:", "**overview**"),
        "usage": ("## usage", "# usage", "usage:", "**usage**"),
    }
    return _check_body_markers(content, _MARKERS)


def check_human_approved(conn: "sqlite3.Connection", task_id: str, stage: str) -> bool:
    """Check if a task has been approved by a human for the given stage.

    Looks for ``human_approved`` events in the events table.
    The stage field in the event payload must match the current stage.
    """
    row = conn.execute(
        "SELECT 1 FROM task_events "
        "WHERE task_id = ? AND kind = 'human_approved' "
        "AND json_extract(payload, '$.stage') = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (task_id, stage),
    ).fetchone()
    return row is not None


def time_in_stage_hours(conn: "sqlite3.Connection", task_id: str, stage: str) -> float:
    """Return hours since the task entered the given stage."""
    row = conn.execute(
        "SELECT created_at FROM task_events "
        "WHERE task_id = ? AND kind = 'pipeline_advanced' "
        "AND json_extract(payload, '$.to_stage') = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (task_id, stage),
    ).fetchone()
    if not row:
        return 0.0
    import datetime
    created = datetime.datetime.fromisoformat(row[0])
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - created).total_seconds() / 3600.0


# ---------------------------------------------------------------------------
# Pipeline state machine
# ---------------------------------------------------------------------------

# Stage order in the feature pipeline (matches design doc §3).
# Full tier=full path: 1.research 2.prd 3.spec 4.council 5.sign_off
# 6.tech_review 7.decompose 8.execute 9.pr+qa 10.audit
# 11.final_sign_off 12.document
PIPELINE_STAGES = [
    "research",      # [2] research brief
    "prd",           # [3] product requirements doc
    "spec",          # [4] tech spec
    "council",       # [5] LLM council deliberation
    "sign_off",      # [6] ⏸ spec sign-off (human)
    "tech_review",   # [7] octacon architectural review
    "decompose",     # [8] child task decomposition (WS-1 contract gate)
    "execute",       # [9] workers claim and ship code
    "pr+qa",         # [10] PR open + tests green
    "audit",         # [11] multi-layer audit (quan fleet + kensei-review)
    "final_sign_off",# [12] ⏸ final sign-off (human)
    "document",      # [13] light → wiki/docs
]

# Gate function mapping per stage. Stages without a gate (execute, pr+qa,
# pass-through) auto-advance; the dispatcher moves tasks forward when no
# gate function is registered for the current stage.
# document has its own gate (validate_document_artifact).
GATE_FUNCTIONS = {
    "research": validate_research_artifact,
    "prd": validate_prd_artifact,
    "spec": validate_spec_artifact,
    "council": validate_council_artifact,
    "tech_review": validate_tech_review_artifact,
    "decompose": validate_decompose_artifact,
    "audit": validate_audit_artifact,
    "document": validate_document_artifact,
}

# Human-gate stages: these stages require manual approval via CLI/Discord.
# The dispatcher checks for a ``human_approved`` event in the events table
# rather than running a gate function on disk artifacts.
HUMAN_GATE_STAGES = {"sign_off", "final_sign_off"}

# Pass-through stages: gate function returns None (auto-advance). Workers
# claim and ship; the dispatcher just moves the task forward when there is
# no artifact gate blocking.
PASS_THROUGH_STAGES = {"execute", "pr+qa"}

# Express path: drops PRD, Council, Tech Review; keeps the two human gates
# and the full audit. Used by ``hermes feature create --express`` and the
# /feature express skill. Skipped stages are logged as bypass-records.
EXPRESS_PIPELINE_STAGES = [
    "research", "spec", "sign_off", "decompose", "execute",
    "pr+qa", "audit", "final_sign_off", "document",
]


def get_next_stage(current_stage: str, pipeline_mode: str = "full") -> Optional[str]:
    """Return the next pipeline stage, or None if at the end.

    ``pipeline_mode`` selects which stage set to walk:
        - ``"full"`` (default): all 12 stages (design doc §3 full path).
        - ``"express"``: 9 stages (design doc §4a express path), skipping
          PRD, Council, and Tech Review.
    """
    if pipeline_mode == "express":
        stages = EXPRESS_PIPELINE_STAGES
    else:
        stages = PIPELINE_STAGES
    try:
        idx = stages.index(current_stage)
        if idx + 1 < len(stages):
            return stages[idx + 1]
    except ValueError:
        pass
    return None


def get_pipeline_mode(task_row: dict) -> str:
    """Return ``"express"`` if the task is in express mode, else ``"full"``.

    Reads the ``pipeline_mode`` column from the task row. Defaults to
    ``"full"`` when unset so the existing data is unaffected.
    """
    if not task_row:
        return "full"
    mode = task_row.get("pipeline_mode") or "full"
    return mode if mode in ("full", "express") else "full"


def get_skipped_stages(pipeline_mode: str = "full") -> list[str]:
    """Return the set of full-pipeline stages that the given mode skips.

    For express: PRD, Council, Tech Review. For full: empty.
    """
    if pipeline_mode == "express":
        return [s for s in PIPELINE_STAGES if s not in EXPRESS_PIPELINE_STAGES]
    return []


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
