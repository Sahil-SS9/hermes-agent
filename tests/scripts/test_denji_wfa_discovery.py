"""Tests for WFA discover_dbs() — canonical 7-DB topology enumeration.

P05 Batch 1: proves discover_dbs() enumerates all 7 canonical boards
(default→core, apps, content, core, kensei-rebuild, research, security-ops)
plus profile-scoped boards from a fixture HERMES_HOME.  Uses a temporary
HERMES_HOME — never touches live ``~/.hermes``.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SCRIPTS))


def _make_board(home: Path, slug: str) -> Path:
    """Create a board directory + board.json + minimal kanban.db."""
    d = home / "kanban" / "boards" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "board.json").write_text(
        f'{{"slug":"{slug}","name":"{slug}","archived":false}}'
    )
    db = d / "kanban.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE IF NOT EXISTS task_runs (id TEXT, task_id TEXT, profile TEXT, status TEXT, outcome TEXT, started_at TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS task_events (task_id TEXT, kind TEXT, payload TEXT, created_at TEXT)")
    conn.close()
    return db


def _make_profile_board(home: Path, profile: str, slug: str) -> Path:
    """Create a profile-scoped board under profiles/<profile>/kanban/boards/."""
    d = home / "profiles" / profile / "kanban" / "boards" / slug
    d.mkdir(parents=True, exist_ok=True)
    db = d / "kanban.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE IF NOT EXISTS task_runs (id TEXT, task_id TEXT, profile TEXT, status TEXT, outcome TEXT, started_at TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS task_events (task_id TEXT, kind TEXT, payload TEXT, created_at TEXT)")
    conn.close()
    return db


def _load_wfa(home: Path, monkeypatch):
    """Import denji-wfa.py with HERMES_HOME pointed at the fixture."""
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(home))
    # Also clear HERMES_KANBAN_DB so it doesn't override
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)
    spec = importlib.util.spec_from_file_location(
        "denji_wfa_under_test", str(SCRIPTS / "denji-wfa.py")
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    h = tmp_path / "hermes"
    h.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(h))
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(h))
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)
    return h


class TestCanonicalDiscovery:
    """discover_dbs must enumerate the full canonical 7-DB topology."""

    def test_all_seven_canonical_boards_discovered(self, fake_home, monkeypatch):
        """Create all 7 canonical board DBs; discover_dbs must find all 7."""
        # The canonical slugs (post-compat): core, apps, content,
        # kensei-rebuild, research, security-ops.  "default" maps to core.
        for slug in (
            "core", "apps", "content", "kensei-rebuild", "research", "security-ops"
        ):
            _make_board(fake_home, slug)

        mod = _load_wfa(fake_home, monkeypatch)
        dbs = mod.discover_dbs()

        # We created 6 distinct board DBs (default resolves to core, so
        # the "default" entry and any "core" board resolve to the same path
        # and get deduplicated).  Expect 6 unique DBs.
        assert len(dbs) == 6
        boards = {db["board"] for db in dbs}
        # The canonical board labels (legacy keys preserved):
        assert "default" in boards or "core" in boards
        assert "apps" in boards
        assert "research" in boards
        assert "kensei-rebuild" in boards
        # ops → security-ops, content-lead → content
        assert "ops" in boards or "security-ops" in boards
        assert "content-lead" in boards or "content" in boards

    def test_kensei_rebuild_included(self, fake_home, monkeypatch):
        """kensei-rebuild was missing from the legacy REQUIRED_BOARDS; it
        must now be discovered."""
        _make_board(fake_home, "kensei-rebuild")
        mod = _load_wfa(fake_home, monkeypatch)
        dbs = mod.discover_dbs()
        boards = {db["board"] for db in dbs}
        assert "kensei-rebuild" in boards

    def test_legacy_slug_resolves_to_canonical(self, fake_home, monkeypatch):
        """When only the canonical board exists (no legacy), the legacy slug
        resolves to it."""
        _make_board(fake_home, "security-ops")
        mod = _load_wfa(fake_home, monkeypatch)
        dbs = mod.discover_dbs()
        paths = {db["path"] for db in dbs}
        assert any("security-ops" in p for p in paths)

    def test_default_resolves_to_core(self, fake_home, monkeypatch):
        """When no legacy kanban.db exists, default resolves to core."""
        _make_board(fake_home, "core")
        mod = _load_wfa(fake_home, monkeypatch)
        dbs = mod.discover_dbs()
        paths = [db["path"] for db in dbs]
        assert any("boards" in p and "core" in p for p in paths)

    def test_content_lead_resolves_to_content(self, fake_home, monkeypatch):
        _make_board(fake_home, "content")
        mod = _load_wfa(fake_home, monkeypatch)
        dbs = mod.discover_dbs()
        paths = {db["path"] for db in dbs}
        assert any("content" in p and "content-lead" not in p for p in paths)


class TestProfileScopedDiscovery:
    """discover_dbs must also enumerate profile-scoped boards."""

    def test_profile_scoped_board_discovered(self, fake_home, monkeypatch):
        _make_board(fake_home, "core")
        _make_profile_board(fake_home, "dezzy", "ops")
        mod = _load_wfa(fake_home, monkeypatch)
        dbs = mod.discover_dbs()
        boards = {db["board"] for db in dbs}
        assert "dezzy/ops" in boards

    def test_multiple_profile_scoped_boards(self, fake_home, monkeypatch):
        _make_board(fake_home, "core")
        _make_profile_board(fake_home, "dezzy", "ops")
        _make_profile_board(fake_home, "wesker", "default")
        _make_profile_board(fake_home, "octacon", "apps")
        mod = _load_wfa(fake_home, monkeypatch)
        dbs = mod.discover_dbs()
        boards = {db["board"] for db in dbs}
        assert "dezzy/ops" in boards
        assert "wesker/default" in boards
        assert "octacon/apps" in boards

    def test_no_profiles_dir_does_not_crash(self, fake_home, monkeypatch):
        """If profiles/ doesn't exist, discover_dbs still works."""
        _make_board(fake_home, "core")
        mod = _load_wfa(fake_home, monkeypatch)
        dbs = mod.discover_dbs()
        assert len(dbs) >= 1


class TestDedupAndExistence:
    """discover_dbs must deduplicate by resolved path and skip non-existent."""

    def test_deduplication_by_resolved_path(self, fake_home, monkeypatch):
        """If default and core resolve to the same path, only one entry."""
        _make_board(fake_home, "core")
        mod = _load_wfa(fake_home, monkeypatch)
        dbs = mod.discover_dbs()
        paths = [db["path"] for db in dbs]
        assert len(paths) == len(set(paths))  # no duplicates

    def test_nonexistent_boards_skipped(self, fake_home, monkeypatch):
        """Boards that don't exist on disk are skipped."""
        mod = _load_wfa(fake_home, monkeypatch)
        dbs = mod.discover_dbs()
        assert len(dbs) == 0


class TestNoStaticLabelReliance:
    """discover_dbs must not rely on the legacy REQUIRED_BOARDS list alone."""

    def test_canonical_boards_constant_exists(self, fake_home, monkeypatch):
        mod = _load_wfa(fake_home, monkeypatch)
        assert hasattr(mod, "CANONICAL_BOARDS")
        assert "kensei-rebuild" in mod.CANONICAL_BOARDS

    def test_required_boards_is_alias(self, fake_home, monkeypatch):
        """REQUIRED_BOARDS is kept as a back-compat alias."""
        mod = _load_wfa(fake_home, monkeypatch)
        assert mod.REQUIRED_BOARDS == mod.CANONICAL_BOARDS
