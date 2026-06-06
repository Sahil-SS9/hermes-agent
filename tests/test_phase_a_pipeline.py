#!/usr/bin/env python3
"""Tests for Phase A — Front-Half Gates (feature pipeline).

Covers:
- New kanban states (research, prd, spec, council)
- Pipeline stage migration (pipeline_stage column)
- Gate functions (intake, research, prd, spec)
- Artifact storage helpers
- Pipeline state machine transitions
"""
import os
import sqlite3
import tempfile
import pytest

from hermes_cli import kanban_db as kb
from hermes_cli.feature_pipeline import (
    validate_intake_brief,
    validate_research_artifact,
    validate_prd_artifact,
    validate_spec_artifact,
    get_artifact_path,
    write_artifact,
    read_artifact,
    advance_pipeline,
    get_next_stage,
    PIPELINE_STAGES,
)


# ---------------------------------------------------------------------------
# Phase A.1 — Data model tests
# ---------------------------------------------------------------------------

class TestNewPipelineStates:
    """Verify new feature-pipeline states exist in VALID_STATUSES."""

    def test_research_in_valid_statuses(self):
        assert "research" in kb.VALID_STATUSES

    def test_prd_in_valid_statuses(self):
        assert "prd" in kb.VALID_STATUSES

    def test_spec_in_valid_statuses(self):
        assert "spec" in kb.VALID_STATUSES

    def test_council_in_valid_statuses(self):
        assert "council" in kb.VALID_STATUSES

    def test_existing_states_unchanged(self):
        """Original states must not be removed."""
        expected = {"triage", "todo", "scheduled", "ready", "running",
                    "blocked", "review", "done", "archived", "backlog"}
        assert expected.issubset(kb.VALID_STATUSES)


# ---------------------------------------------------------------------------
# Phase A.1 — Pipeline stage migration tests
# ---------------------------------------------------------------------------

@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    """Isolated HERMES_HOME with an empty kanban DB."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    from pathlib import Path
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


class TestPipelineStageMigration:
    """Verify pipeline_stage column is added by migration."""

    def test_pipeline_stage_column_exists_on_fresh_db(self, kanban_home):
        """A fresh DB should have the pipeline_stage column."""
        with kb.connect() as conn:
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
            assert "pipeline_stage" in cols

    def test_pipeline_stage_null_by_default(self, kanban_home):
        """New tasks should have NULL pipeline_stage."""
        with kb.connect() as conn:
            kb.create_task(conn, title="test task", assignee="test", triage=True)
            row = conn.execute("SELECT pipeline_stage FROM tasks LIMIT 1").fetchone()
            assert row["pipeline_stage"] is None

    def test_pipeline_stage_accepts_valid_values(self, kanban_home):
        """pipeline_stage should accept research, prd, spec, council."""
        with kb.connect() as conn:
            task_id = kb.create_task(conn, title="test", assignee="test", triage=True)
            for stage in ("research", "prd", "spec", "council"):
                conn.execute("UPDATE tasks SET pipeline_stage = ? WHERE id = ?", (stage, task_id))
                row = conn.execute("SELECT pipeline_stage FROM tasks WHERE id = ?", (task_id,)).fetchone()
                assert row["pipeline_stage"] == stage


# ---------------------------------------------------------------------------
# Gate function tests
# ---------------------------------------------------------------------------

class TestIntakeGate:
    """validate_intake_brief: checks body has problem + success criteria."""

    def test_passes_with_both_sections(self):
        body = "## Problem\nBuild a thing.\n\n## Success Criteria\nIt works."
        assert validate_intake_brief(body) is None

    def test_fails_without_problem(self):
        body = "## Success Criteria\nIt works."
        result = validate_intake_brief(body)
        assert result is not None
        assert "Problem" in result

    def test_fails_without_success_criteria(self):
        body = "## Problem\nBuild a thing."
        result = validate_intake_brief(body)
        assert result is not None
        assert "Success Criteria" in result

    def test_fails_with_empty_body(self):
        assert validate_intake_brief("") is not None

    def test_fails_with_none_body(self):
        assert validate_intake_brief(None) is not None


class TestResearchGate:
    """validate_research_artifact: checks research-brief.md exists with content."""

    def test_passes_with_valid_artifact(self, tmp_path):
        artifact_dir = tmp_path / "task-001"
        artifact_dir.mkdir()
        (artifact_dir / "research-brief.md").write_text(
            "# Research Brief\n\n## Findings\nNo prior art found.\n"
        )
        assert validate_research_artifact(str(artifact_dir)) is None

    def test_fails_without_artifact(self, tmp_path):
        artifact_dir = tmp_path / "task-002"
        artifact_dir.mkdir()
        result = validate_research_artifact(str(artifact_dir))
        assert result is not None
        assert "research-brief.md" in result

    def test_fails_with_empty_artifact(self, tmp_path):
        artifact_dir = tmp_path / "task-003"
        artifact_dir.mkdir()
        (artifact_dir / "research-brief.md").write_text("")
        assert validate_research_artifact(str(artifact_dir)) is not None

    def test_fails_without_findings_section(self, tmp_path):
        artifact_dir = tmp_path / "task-004"
        artifact_dir.mkdir()
        (artifact_dir / "research-brief.md").write_text("# Research Brief\n\nSome notes.\n")
        result = validate_research_artifact(str(artifact_dir))
        assert result is not None
        assert "Findings" in result


class TestPrdGate:
    """validate_prd_artifact: checks prd.md has required sections."""

    def test_passes_with_all_sections(self, tmp_path):
        artifact_dir = tmp_path / "task-005"
        artifact_dir.mkdir()
        (artifact_dir / "prd.md").write_text(
            "# PRD\n\n## Problem\nBuild a thing.\n\n## Users\nPMs.\n\n"
            "## Scope\nIn scope: everything.\n\n## Out of Scope\nNothing.\n\n"
            "## Metrics\nSuccess rate > 90%.\n"
        )
        assert validate_prd_artifact(str(artifact_dir)) is None

    def test_fails_without_problem(self, tmp_path):
        artifact_dir = tmp_path / "task-006"
        artifact_dir.mkdir()
        (artifact_dir / "prd.md").write_text(
            "# PRD\n\n## Users\nPMs.\n\n## Scope\nIn scope.\n\n"
            "## Out of Scope\nNone.\n\n## Metrics\n90%.\n"
        )
        result = validate_prd_artifact(str(artifact_dir))
        assert result is not None
        assert "Problem" in result

    def test_fails_without_prd_file(self, tmp_path):
        artifact_dir = tmp_path / "task-007"
        artifact_dir.mkdir()
        result = validate_prd_artifact(str(artifact_dir))
        assert result is not None
        assert "prd.md" in result


class TestSpecGate:
    """validate_spec_artifact: checks spec.md has required sections."""

    def test_passes_with_all_sections(self, tmp_path):
        artifact_dir = tmp_path / "task-008"
        artifact_dir.mkdir()
        (artifact_dir / "spec.md").write_text(
            "# Spec\n\n## Architecture\nMonolith.\n\n"
            "## Interfaces\nREST API.\n\n## Test Strategy\nUnit + integration.\n"
        )
        assert validate_spec_artifact(str(artifact_dir)) is None

    def test_fails_without_architecture(self, tmp_path):
        artifact_dir = tmp_path / "task-009"
        artifact_dir.mkdir()
        (artifact_dir / "spec.md").write_text(
            "# Spec\n\n## Interfaces\nREST.\n\n## Test Strategy\nUnit.\n"
        )
        result = validate_spec_artifact(str(artifact_dir))
        assert result is not None
        assert "Architecture" in result

    def test_fails_without_spec_file(self, tmp_path):
        artifact_dir = tmp_path / "task-010"
        artifact_dir.mkdir()
        result = validate_spec_artifact(str(artifact_dir))
        assert result is not None
        assert "spec.md" in result


# ---------------------------------------------------------------------------
# Artifact helper tests
# ---------------------------------------------------------------------------

class TestArtifactHelpers:
    """Test artifact path resolution and read/write helpers."""

    def test_get_artifact_path(self, tmp_path):
        path = get_artifact_path(str(tmp_path), "task-001", "research-brief.md")
        assert path.endswith("task-001/research-brief.md")
        assert str(tmp_path) in path

    def test_write_and_read_artifact(self, tmp_path):
        content = "# Research Brief\n\n## Findings\nNothing found.\n"
        write_artifact(str(tmp_path), "task-002", "research-brief.md", content)
        result = read_artifact(str(tmp_path), "task-002", "research-brief.md")
        assert result == content

    def test_read_nonexistent_returns_none(self, tmp_path):
        result = read_artifact(str(tmp_path), "task-003", "research-brief.md")
        assert result is None


# ---------------------------------------------------------------------------
# Pipeline state machine tests
# ---------------------------------------------------------------------------

class TestPipelineStateMachine:
    """Test pipeline stage transitions and gate checks."""

    def test_get_next_stage(self):
        assert get_next_stage("research") == "prd"
        assert get_next_stage("prd") == "spec"
        assert get_next_stage("spec") == "council"
        assert get_next_stage("council") is None

    def test_get_next_stage_invalid(self):
        assert get_next_stage("invalid") is None

    def test_advance_pipeline_research_passes(self, tmp_path):
        """Research gate passes when artifact exists with findings."""
        artifact_dir = tmp_path / "task-010"
        artifact_dir.mkdir()
        (artifact_dir / "research-brief.md").write_text(
            "# Research\n\n## Findings\nNothing found.\n"
        )
        result = advance_pipeline("task-010", "research", str(tmp_path))
        assert result["advanced"] is True
        assert result["gate_passed"] is True
        assert result["to_stage"] == "prd"

    def test_advance_pipeline_research_fails(self, tmp_path):
        """Research gate fails without artifact."""
        artifact_dir = tmp_path / "task-011"
        artifact_dir.mkdir()
        result = advance_pipeline("task-011", "research", str(tmp_path))
        assert result["advanced"] is False
        assert result["gate_passed"] is False
        assert result["gate_message"] is not None

    def test_advance_pipeline_prd_passes(self, tmp_path):
        """PRD gate passes when artifact has all required sections."""
        artifact_dir = tmp_path / "task-012"
        artifact_dir.mkdir()
        (artifact_dir / "prd.md").write_text(
            "# PRD\n\n## Problem\nX.\n\n## Users\nY.\n\n"
            "## Scope\nZ.\n\n## Out of Scope\nW.\n\n## Metrics\n90%.\n"
        )
        result = advance_pipeline("task-012", "prd", str(tmp_path))
        assert result["advanced"] is True
        assert result["gate_passed"] is True
        assert result["to_stage"] == "spec"

    def test_advance_pipeline_spec_passes(self, tmp_path):
        """Spec gate passes when artifact has all required sections."""
        artifact_dir = tmp_path / "task-013"
        artifact_dir.mkdir()
        (artifact_dir / "spec.md").write_text(
            "# Spec\n\n## Architecture\nA.\n\n## Interfaces\nB.\n\n## Test Strategy\nC.\n"
        )
        result = advance_pipeline("task-013", "spec", str(tmp_path))
        assert result["advanced"] is True
        assert result["gate_passed"] is True
        assert result["to_stage"] == "council"

    def test_advance_pipeline_council_no_gate(self, tmp_path):
        """Council has no gate (Phase B) — should advance to None."""
        artifact_dir = tmp_path / "task-014"
        artifact_dir.mkdir()
        result = advance_pipeline("task-014", "council", str(tmp_path))
        assert result["advanced"] is False
        assert result["gate_passed"] is True
        assert result["to_stage"] is None

    def test_pipeline_stages_order(self):
        """Pipeline stages are in correct order."""
        assert PIPELINE_STAGES == ["research", "prd", "spec", "council"]
