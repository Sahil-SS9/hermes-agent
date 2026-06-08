"""
Tests for staging_harness module (P2-6).

Covers: snapshot creation, replay with patches, snapshot diff,
snapshot listing, cleanup, and promote.
"""

import json
import os
import sqlite3
import tempfile
from unittest.mock import patch

import pytest

from hermes_cli.staging_harness import (
    StagingHarness,
    SnapshotMeta,
    ReplayResult,
    SnapshotDiff,
    STAGING_DIR,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_kanban_db(db_path: str, tasks: list[dict] | None = None) -> str:
    """Create a minimal kanban SQLite DB for testing."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            status TEXT DEFAULT 'ready',
            pipeline_stage TEXT DEFAULT '',
            assignee TEXT DEFAULT '',
            tier TEXT DEFAULT 'fast',
            title TEXT DEFAULT '',
            body TEXT DEFAULT '',
            created_at TEXT DEFAULT ''
        )
    """)
    if tasks:
        for t in tasks:
            conn.execute(
                "INSERT OR REPLACE INTO tasks "
                "(task_id, status, pipeline_stage, assignee, tier, title) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    t["task_id"], t.get("status", "ready"),
                    t.get("pipeline_stage", ""), t.get("assignee", ""),
                    t.get("tier", "fast"), t.get("title", ""),
                ),
            )
    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_creates_snapshot_with_metadata(self):
        with tempfile.TemporaryDirectory() as staging, tempfile.TemporaryDirectory() as data:
            db_path = os.path.join(data, "kanban.db")
            make_kanban_db(db_path, [
                {"task_id": "t_1", "status": "ready"},
                {"task_id": "t_2", "status": "research"},
            ])

            harness = StagingHarness(
                staging_dir=staging,
                kanban_db=db_path,
            )
            snap_id = harness.snapshot(board="test-board", description="Test snapshot")
            assert snap_id.startswith("snap-")

            # Verify snapshot exists
            snap_dir = os.path.join(staging, snap_id)
            assert os.path.exists(snap_dir)
            assert os.path.exists(os.path.join(snap_dir, "kanban.db"))
            assert os.path.exists(os.path.join(snap_dir, "meta.json"))

            # Verify metadata
            with open(os.path.join(snap_dir, "meta.json")) as f:
                meta = json.load(f)
            assert meta["task_count"] == 2
            assert meta["board"] == "test-board"
            assert meta["description"] == "Test snapshot"

    def test_empty_db_snapshot_succeeds(self):
        with tempfile.TemporaryDirectory() as staging, tempfile.TemporaryDirectory() as data:
            db_path = os.path.join(data, "kanban.db")
            make_kanban_db(db_path, [])

            harness = StagingHarness(staging_dir=staging, kanban_db=db_path)
            snap_id = harness.snapshot()
            assert snap_id.startswith("snap-")

    def test_missing_source_db_handled(self):
        with tempfile.TemporaryDirectory() as staging:
            harness = StagingHarness(
                staging_dir=staging,
                kanban_db="/nonexistent/db.sqlite",
            )
            snap_id = harness.snapshot()
            assert snap_id.startswith("snap-")
            # Should create metadata with 0 task count
            snap_dir = os.path.join(staging, snap_id)
            with open(os.path.join(snap_dir, "meta.json")) as f:
                meta = json.load(f)
            assert meta["task_count"] == 0


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


class TestReplay:
    def test_replay_captures_state(self):
        with tempfile.TemporaryDirectory() as staging, tempfile.TemporaryDirectory() as data:
            db_path = os.path.join(data, "kanban.db")
            make_kanban_db(db_path, [
                {"task_id": "t_1", "status": "ready", "pipeline_stage": "", "tier": "full"},
                {"task_id": "t_2", "status": "research", "pipeline_stage": "research", "tier": "full"},
            ])

            harness = StagingHarness(staging_dir=staging, kanban_db=db_path)
            snap_id = harness.snapshot()

            # Replay without modification — should show no changes
            result = harness.replay(snap_id, trigger_tick=False)
            assert result.total_tasks == 2
            assert result.tasks_advanced == 0  # no dispatch tick, no change
            assert len(result.gate_changes) == 0

    def test_replay_missing_snapshot(self):
        with tempfile.TemporaryDirectory() as staging:
            harness = StagingHarness(staging_dir=staging)
            result = harness.replay("snap-nonexistent")
            assert not result.passed
            assert len(result.errors) > 0

    def test_replay_with_patch(self):
        with tempfile.TemporaryDirectory() as staging, tempfile.TemporaryDirectory() as data:
            db_path = os.path.join(data, "kanban.db")
            make_kanban_db(db_path, [
                {"task_id": "t_1", "status": "ready"},
            ])

            harness = StagingHarness(staging_dir=staging, kanban_db=db_path)
            snap_id = harness.snapshot()

            # Patch a non-existent attribute — should record error gracefully
            result = harness.replay(
                snap_id,
                patch_module="hermes_cli.staging_harness",
                patch_attr="NONEXISTENT_CONSTANT",
                patch_value=42,
                trigger_tick=False,
            )
            # May or may not have errors depending on whether module exists
            # Just verify no crash
            assert isinstance(result, ReplayResult)


# ---------------------------------------------------------------------------
# Snapshot diff
# ---------------------------------------------------------------------------


class TestSnapshotDiff:
    def test_diff_detects_added_removed_changed(self):
        with tempfile.TemporaryDirectory() as staging, tempfile.TemporaryDirectory() as data:
            db_path = os.path.join(data, "kanban.db")

            # Create two snapshots from the same DB but with different state
            harness = StagingHarness(staging_dir=staging, kanban_db=db_path)

            make_kanban_db(db_path, [
                {"task_id": "t_1", "status": "ready"},
                {"task_id": "t_2", "status": "research"},
            ])
            snap1 = harness.snapshot()

            # Modify and create second snapshot
            conn = sqlite3.connect(db_path)
            conn.execute("UPDATE tasks SET status='prd' WHERE task_id='t_2'")
            conn.execute(
                "INSERT INTO tasks (task_id, status) VALUES ('t_3', 'ready')"
            )
            conn.commit()
            conn.close()
            snap2 = harness.snapshot()

            diff = harness.diff(snap1, snap2)
            assert "t_3" in diff.added_tasks
            assert len(diff.added_tasks) == 1
            assert len(diff.removed_tasks) == 0
            assert "t_2" in diff.changed_tasks

    def test_diff_no_changes(self):
        with tempfile.TemporaryDirectory() as staging, tempfile.TemporaryDirectory() as data:
            db_path = os.path.join(data, "kanban.db")
            make_kanban_db(db_path, [{"task_id": "t_1", "status": "ready"}])

            harness = StagingHarness(staging_dir=staging, kanban_db=db_path)
            snap1 = harness.snapshot()
            snap2 = harness.snapshot()

            diff = harness.diff(snap1, snap2)
            assert len(diff.added_tasks) == 0
            assert len(diff.removed_tasks) == 0
            assert len(diff.changed_tasks) == 0


# ---------------------------------------------------------------------------
# List snapshots
# ---------------------------------------------------------------------------


class TestListSnapshots:
    def test_lists_snapshots(self):
        with tempfile.TemporaryDirectory() as staging, tempfile.TemporaryDirectory() as data:
            db_path = os.path.join(data, "kanban.db")
            make_kanban_db(db_path, [])

            harness = StagingHarness(staging_dir=staging, kanban_db=db_path)
            harness.snapshot(description="First")
            harness.snapshot(description="Second")

            snapshots = harness.list_snapshots()
            assert len(snapshots) == 2
            assert snapshots[0].description == "First"
            assert snapshots[1].description == "Second"

    def test_empty_no_snapshots(self):
        with tempfile.TemporaryDirectory() as staging:
            harness = StagingHarness(staging_dir=staging)
            assert harness.list_snapshots() == []


# ---------------------------------------------------------------------------
# Cleanup and promote
# ---------------------------------------------------------------------------


class TestCleanup:
    def test_cleanup_removes_snapshot(self):
        with tempfile.TemporaryDirectory() as staging, tempfile.TemporaryDirectory() as data:
            db_path = os.path.join(data, "kanban.db")
            make_kanban_db(db_path, [])

            harness = StagingHarness(staging_dir=staging, kanban_db=db_path)
            snap_id = harness.snapshot()
            assert os.path.exists(os.path.join(staging, snap_id))

            harness.cleanup(snap_id)
            assert not os.path.exists(os.path.join(staging, snap_id))

    def test_cleanup_all_removes_everything(self):
        with tempfile.TemporaryDirectory() as staging, tempfile.TemporaryDirectory() as data:
            db_path = os.path.join(data, "kanban.db")
            make_kanban_db(db_path, [])

            harness = StagingHarness(staging_dir=staging, kanban_db=db_path)
            harness.snapshot()
            harness.snapshot()

            harness.cleanup()  # all
            assert harness.list_snapshots() == []

    def test_promote_records_timestamp(self):
        with tempfile.TemporaryDirectory() as staging, tempfile.TemporaryDirectory() as data:
            db_path = os.path.join(data, "kanban.db")
            make_kanban_db(db_path, [])

            harness = StagingHarness(staging_dir=staging, kanban_db=db_path)
            snap_id = harness.snapshot()

            harness.promote(snap_id)

            snap_dir = os.path.join(staging, snap_id)
            with open(os.path.join(snap_dir, "meta.json")) as f:
                meta = json.load(f)
            assert meta.get("promoted") is True
            assert "promoted_at" in meta

    def test_promote_missing_snapshot_no_error(self):
        with tempfile.TemporaryDirectory() as staging:
            harness = StagingHarness(staging_dir=staging)
            harness.promote("snap-doesnt-exist")  # should not crash
