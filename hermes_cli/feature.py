#!/usr/bin/env python3
"""Feature pipeline CLI commands.

Provides ``hermes feature`` subcommands for managing the feature pipeline:
- ``hermes feature create`` — create a feature task with intake format
- ``hermes feature status`` — view pipeline status for a task or board
- ``hermes feature advance`` — manually advance a task to the next stage

The pipeline follows: triage → research → prd → spec → council
Each stage has a gate function that validates the artifact before promotion.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Optional

from hermes_cli.kanban_db import (
    connect,
    create_task,
    get_task,
    promote_task,
)
from hermes_cli.feature_pipeline import (
    PIPELINE_STAGES,
    GATE_FUNCTIONS,
    HUMAN_GATE_STAGES,
    get_next_stage,
    validate_intake_brief,
    check_human_approved,
    get_artifact_path,
    write_artifact,
    read_artifact,
)


def _get_pipeline_tasks(board: Optional[str] = None) -> list[dict]:
    """Get all tasks in pipeline stages (research/prd/spec/council)."""
    try:
        with connect(board=board) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, title, status, pipeline_stage, assignee, tier "
                "FROM tasks WHERE status IN ('research', 'prd', 'spec', 'council') "
                "ORDER BY priority DESC, created_at ASC"
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def cmd_feature_create(args: argparse.Namespace) -> int:
    """Create a feature task with proper intake format."""
    title = args.title
    body = args.body or ""
    assignee = args.assignee
    board = args.board

    # Validate intake format
    gate_fail = validate_intake_brief(body)
    if gate_fail:
        print(f"Intake gate failed: {gate_fail}", file=sys.stderr)
        print("Feature tasks require:", file=sys.stderr)
        print("  ## Problem — what problem does this solve?", file=sys.stderr)
        print("  ## Success Criteria — how do we know it's done?", file=sys.stderr)
        return 1

    # Create task in triage with tier=full
    try:
        with connect() as conn:
            task_id = create_task(
                conn,
                title=title,
                body=body,
                assignee=assignee,
                triage=True,
                tier="full",
                board=board,
            )
            print(f"Created feature task: {task_id}")
            print(f"Title: {title}")
            if assignee:
                print(f"Assignee: {assignee}")
            print("Status: triage (tier=full)")
            print("Next: triage processor will promote to 'research'")
            return 0
    except Exception as exc:
        print(f"Error creating task: {exc}", file=sys.stderr)
        return 1


def cmd_feature_status(args: argparse.Namespace) -> int:
    """View pipeline status for a task or board."""
    board = args.board
    task_id = args.task_id

    if task_id:
        # Show status for a specific task
        try:
            with connect() as conn:
                task = get_task(conn, task_id)
                if not task:
                    print(f"Task not found: {task_id}", file=sys.stderr)
                    return 1
                print(f"Task: {task.id}")
                print(f"Title: {task.title}")
                print(f"Status: {task.status}")
                print(f"Pipeline stage: {task.pipeline_stage or 'N/A'}")
                print(f"Tier: {task.tier or 'unclassified'}")
                print(f"Assignee: {task.assignee or 'unassigned'}")

                # Show gate status for current stage
                stage = task.pipeline_stage
                if stage and stage in GATE_FUNCTIONS:
                    gate_fn = GATE_FUNCTIONS[stage]
                    artifact_base = os.path.join(
                        os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")),
                        "feature-artifacts",
                    )
                    artifact_dir = os.path.join(artifact_base, task_id)
                    gate_result = gate_fn(artifact_dir)
                    if gate_result is None:
                        print(f"Gate: PASS (ready to advance)")
                    else:
                        print(f"Gate: FAIL — {gate_result}")
                return 0
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    else:
        # Show all pipeline tasks for the board
        tasks = _get_pipeline_tasks(board)
        if not tasks:
            print("No tasks in pipeline.")
            return 0

        print(f"Pipeline tasks ({len(tasks)}):")
        print("-" * 60)
        for task in tasks:
            stage = task.get("pipeline_stage", "N/A")
            status = task.get("status", "N/A")
            assignee = task.get("assignee", "unassigned")
            title = task.get("title", "N/A")[:50]
            print(f"  {task['id']}: {title}")
            print(f"    Status: {status} | Stage: {stage} | Assignee: {assignee}")
        return 0


def cmd_feature_advance(args: argparse.Namespace) -> int:
    """Manually advance a task to the next pipeline stage."""
    task_id = args.task_id
    force = args.force

    try:
        with connect() as conn:
            task = get_task(conn, task_id)
            if not task:
                print(f"Task not found: {task_id}", file=sys.stderr)
                return 1

            current_stage = task.pipeline_stage
            if not current_stage:
                print(f"Task {task_id} is not in the pipeline", file=sys.stderr)
                return 1

            next_stage = get_next_stage(current_stage)
            if not next_stage:
                print(f"Task {task_id} is at the end of the pipeline ({current_stage})", file=sys.stderr)
                return 1

            # Check gate unless forced
            if not force:
                gate_fn = GATE_FUNCTIONS.get(current_stage)
                if gate_fn:
                    artifact_base = os.path.join(
                        os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")),
                        "feature-artifacts",
                    )
                    artifact_dir = os.path.join(artifact_base, task_id)
                    gate_result = gate_fn(artifact_dir)
                    if gate_result is not None:
                        print(f"Gate failed: {gate_result}", file=sys.stderr)
                        print("Use --force to bypass the gate", file=sys.stderr)
                        return 1

            # Advance
            conn.execute(
                "UPDATE tasks SET status = ?, pipeline_stage = ? WHERE id = ?",
                (next_stage, next_stage, task_id),
            )
            conn.commit()
            print(f"Advanced {task_id}: {current_stage} → {next_stage}")
            return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def build_parser(parent_subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Attach the ``feature`` subcommand tree under an existing subparsers.

    Returns the top-level ``feature`` parser so caller can ``set_defaults``.
    """
    feature_parser = parent_subparsers.add_parser(
        "feature",
        help="Feature pipeline management (intake, research, PRD, spec, council)",
        description=(
            "Manage the feature pipeline: intake → research → prd → spec → council. "
            "Each stage has a gate function that validates the artifact before promotion."
        ),
    )
    feature_subparsers = feature_parser.add_subparsers(dest="feature_action")

    # hermes feature create
    create_parser = feature_subparsers.add_parser(
        "create",
        help="Create a feature task with intake format",
    )
    create_parser.add_argument("title", help="Feature title")
    create_parser.add_argument("--body", "-b", help="Feature body (must have ## Problem and ## Success Criteria)")
    create_parser.add_argument("--assignee", "-a", help="Assign to a profile")
    create_parser.add_argument("--board", "-B", help="Board name (default: current)")

    # hermes feature status
    status_parser = feature_subparsers.add_parser(
        "status",
        help="View pipeline status for a task or board",
    )
    status_parser.add_argument("task_id", nargs="?", help="Task ID (optional, shows all if omitted)")
    status_parser.add_argument("--board", "-B", help="Board name (default: current)")

    # hermes feature advance
    advance_parser = feature_subparsers.add_parser(
        "advance",
        help="Manually advance a task to the next pipeline stage",
    )
    advance_parser.add_argument("task_id", help="Task ID to advance")
    advance_parser.add_argument("--force", "-f", action="store_true", help="Bypass gate check")

    # hermes feature sign-off — approve a human-gate stage
    signoff_parser = feature_subparsers.add_parser(
        "sign-off",
        help="Approve a task at a human-gate stage (sign_off/final_sign_off)",
    )
    signoff_parser.add_argument("task_id", help="Task ID to approve")
    signoff_parser.add_argument("--note", "-n", help="Optional approval note")

    # hermes feature reject — reject a human-gate stage
    reject_parser = feature_subparsers.add_parser(
        "reject",
        help="Reject a task at a human-gate stage (bounces back to spec or tech_review)",
    )
    reject_parser.add_argument("task_id", help="Task ID to reject")
    reject_parser.add_argument("reason", nargs="?", default="No reason given", help="Rejection reason")

    return feature_parser


def cmd_feature(args: argparse.Namespace) -> int:
    """Dispatch ``hermes feature`` subcommands."""
    action = getattr(args, "feature_action", None)

    if action == "create":
        return cmd_feature_create(args)
    elif action == "status":
        return cmd_feature_status(args)
    elif action == "advance":
        return cmd_feature_advance(args)
    elif action == "sign-off":
        return cmd_feature_signoff(args)
    elif action == "reject":
        return cmd_feature_reject(args)
    else:
        print("Usage: hermes feature {create|status|advance|sign-off|reject}", file=sys.stderr)
        return 1


def cmd_feature_signoff(args: argparse.Namespace) -> int:
    """Approve a task at a human-gate stage."""
    task_id = args.task_id
    note = args.note

    try:
        with connect() as conn:
            task = get_task(conn, task_id)
            if not task:
                print(f"Task not found: {task_id}", file=sys.stderr)
                return 1

            stage = task.pipeline_stage
            if stage not in HUMAN_GATE_STAGES:
                print(f"Task {task_id} is at '{stage}', not a human-gate stage. "
                      f"Human gate stages: {', '.join(sorted(HUMAN_GATE_STAGES))}",
                      file=sys.stderr)
                return 1

            # Write human_approved event
            payload = json.dumps({"stage": stage, "note": note or ""})
            conn.execute(
                "INSERT INTO task_events (task_id, kind, payload) VALUES (?, ?, ?)",
                (task_id, "human_approved", payload),
            )
            conn.commit()
            print(f"Approved {task_id} at {stage} stage.")
            print("The dispatcher will advance the task on the next tick.")
            return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def cmd_feature_reject(args: argparse.Namespace) -> int:
    """Reject a task at a human-gate stage, bouncing it back."""
    task_id = args.task_id
    reason = args.reason

    try:
        with connect() as conn:
            task = get_task(conn, task_id)
            if not task:
                print(f"Task not found: {task_id}", file=sys.stderr)
                return 1

            stage = task.pipeline_stage
            if stage not in HUMAN_GATE_STAGES:
                print(f"Task {task_id} is at '{stage}', not a human-gate stage.",
                      file=sys.stderr)
                return 1

            # Write human_rejected event
            payload = json.dumps({"stage": stage, "reason": reason})
            conn.execute(
                "INSERT INTO task_events (task_id, kind, payload) VALUES (?, ?, ?)",
                (task_id, "human_rejected", payload),
            )

            # Bounce back: sign_off → spec, final_sign_off → tech_review
            bounce_stage = "spec" if stage == "sign_off" else "tech_review"
            conn.execute(
                "UPDATE tasks SET status = ?, pipeline_stage = ? WHERE id = ?",
                (bounce_stage, bounce_stage, task_id),
            )
            conn.commit()
            print(f"Rejected {task_id}: {reason}")
            print(f"Bounced back: {stage} → {bounce_stage}")
            return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
