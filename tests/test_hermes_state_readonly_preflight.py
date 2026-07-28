"""Tests for the read-only DB preflight (port of Kilo-Org/kilocode#12508).

A stray read-only ``state.db`` / ``-wal`` / ``-shm`` (sudo run, restored
backup, copied dotfiles) used to surface as an opaque
``sqlite3.OperationalError: attempt to write a readonly database`` raised
from deep inside ``_init_schema`` — naming no file and no fix.

``preflight_db_writability`` now runs before the first connection:

- files inside the Hermes home tree are repaired with ``chmod u+rw``
  (the safe scope — chmod fails on files the user doesn't own);
- anything else fails fast with an error naming the exact file and the
  exact ``chmod`` command;
- WAL sidecars are never deleted, so committed frames survive repair.
"""

import os
import sqlite3
import stat
import sys
from pathlib import Path
from typing import Optional


import pytest

import hermes_state
from hermes_state import SessionDB, preflight_db_writability

pytestmark = [
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX chmod semantics"),
    pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root bypasses file permission checks",
    ),
]


@pytest.fixture()
def hermes_home(tmp_path, monkeypatch):
    """Isolated HERMES_HOME so the repair scope covers tmp DBs."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()


def _make_wal_db(path: Path) -> Optional[Path]:
    """Create a WAL-mode DB with committed-but-uncheckpointed frames.

    Returns the path to the ``-wal`` sidecar when it survives with pending
    frames, or ``None`` when the linked SQLite runtime checkpoints and
    removes the ``-wal`` on the last connection's close. SQLite versions
    vulnerable to the WAL-reset bug (see ``is_sqlite_wal_reset_vulnerable``
    in ``hermes_cli.sqlite_runtime``) and certain other builds reabsorb the
    WAL into the main DB file on final close; on those runtimes the
    committed row (42) lands in the main DB instead of the sidecar.
    Callers that require a live ``-wal`` sidecar must skip when ``None`` is
    returned — the preflight's never-delete-sidecar invariant can only be
    exercised when the sidecar is actually present, and forcing its
    persistence on a runtime that reabsorbs it would itself require the
    kind of sidecar manipulation the preflight exists to prevent.
    """
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (x)")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    # Keep a READ-ONLY second connection open so neither close can
    # checkpoint: the writer skips checkpoint-on-close because another
    # connection exists, and the ro holder cannot checkpoint at all.
    # The committed row therefore lives only in the -wal file — on
    # runtimes that preserve the -wal past the final close. Vulnerable
    # SQLite builds reabsorb it instead, so we probe rather than assert.
    holder = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    holder.execute("SELECT 1").fetchone()
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    conn.close()
    holder.close()
    wal = path.with_name(path.name + "-wal")
    return wal if wal.is_file() else None


class TestRepairScope:
    def test_repairs_readonly_db_inside_home(self, hermes_home):
        db = hermes_home / "state.db"
        _make_db(db)
        os.chmod(db, 0o444)

        preflight_db_writability(db, db_label="state.db")

        assert os.access(db, os.W_OK)

    def test_repairs_readonly_sidecars(self, hermes_home):
        db = hermes_home / "state.db"
        wal = _make_wal_db(db)
        if wal is None:
            pytest.skip(
                "-wal sidecar did not survive on this SQLite runtime; "
                "cannot exercise sidecar repair"
            )
        assert wal.is_file(), "fixture must leave a -wal behind"
        os.chmod(db, 0o444)
        os.chmod(wal, 0o444)

        preflight_db_writability(db, db_label="state.db")

        assert os.access(db, os.W_OK)
        assert os.access(wal, os.W_OK)

    def test_wal_data_survives_repair(self, hermes_home):
        """The committed WAL frame must be readable after repair — proof the
        preflight never drops/truncates a sidecar."""
        db = hermes_home / "state.db"
        wal = _make_wal_db(db)
        if wal is None:
            pytest.skip(
                "-wal sidecar did not survive on this SQLite runtime; "
                "cannot exercise never-truncate-sidecar invariant"
            )
        os.chmod(db, 0o444)
        os.chmod(wal, 0o444)

        preflight_db_writability(db, db_label="state.db")

        conn = sqlite3.connect(str(db))
        rows = conn.execute("SELECT x FROM t").fetchall()
        conn.close()
        assert (42,) in rows

    def test_repairs_readonly_parent_directory(self, hermes_home):
        sub = hermes_home / "kanban"
        sub.mkdir()
        db = sub / "kanban.db"
        _make_db(db)
        os.chmod(sub, 0o555)
        try:
            preflight_db_writability(db, db_label="kanban.db")
            assert os.access(sub, os.W_OK)
        finally:
            os.chmod(sub, 0o755)


class TestRefusalOutsideScope:
    def test_actionable_error_names_file_and_chmod(self, hermes_home, tmp_path):
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        db = outside / "custom.db"
        _make_db(db)
        os.chmod(db, 0o444)
        try:
            with pytest.raises(sqlite3.OperationalError) as exc_info:
                preflight_db_writability(db, db_label="custom.db")
            msg = str(exc_info.value)
            assert str(db) in msg
            assert "chmod u+rw" in msg
            # Must NOT have silently chmod'd a file outside the home tree.
            assert not os.access(db, os.W_OK)
        finally:
            os.chmod(db, 0o644)

    def test_wal_error_warns_against_deletion(self, hermes_home, tmp_path):
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        db = outside / "custom.db"
        wal = _make_wal_db(db)
        if wal is None:
            pytest.skip(
                "-wal sidecar did not survive on this SQLite runtime; "
                "cannot exercise WAL-deletion-warning refusal path"
            )
        os.chmod(wal, 0o444)
        try:
            with pytest.raises(sqlite3.OperationalError) as exc_info:
                preflight_db_writability(db, db_label="custom.db")
            msg = str(exc_info.value)
            assert str(wal) in msg
            assert "Do NOT delete" in msg
        finally:
            os.chmod(wal, 0o644)


class TestSkips:
    def test_memory_uri_skipped(self, hermes_home):
        preflight_db_writability(Path(":memory:"))

    def test_file_uri_skipped(self, hermes_home):
        preflight_db_writability(Path("file:whatever?mode=ro"))

    def test_missing_files_no_error(self, hermes_home):
        preflight_db_writability(hermes_home / "state.db")

    def test_healthy_db_untouched(self, hermes_home):
        db = hermes_home / "state.db"
        _make_db(db)
        before = stat.S_IMODE(db.stat().st_mode)
        preflight_db_writability(db)
        assert stat.S_IMODE(db.stat().st_mode) == before


class TestSessionDBIntegration:
    def test_sessiondb_selfheals_readonly_db_in_home(self, hermes_home):
        db_path = hermes_home / "state.db"
        first = SessionDB(db_path)
        first.close()
        for suffix in ("", "-wal", "-shm"):
            p = db_path.with_name(db_path.name + suffix)
            if p.is_file():
                os.chmod(p, 0o444)

        db = SessionDB(db_path)  # must not raise "readonly database"
        try:
            assert os.access(db_path, os.W_OK)
        finally:
            db.close()

    def test_sessiondb_actionable_error_outside_home(
        self, hermes_home, tmp_path
    ):
        outside = tmp_path / "custom-loc"
        outside.mkdir()
        db_path = outside / "state.db"
        first = SessionDB(db_path)
        first.close()
        os.chmod(db_path, 0o444)
        hermes_state._set_last_init_error(None)
        try:
            with pytest.raises(sqlite3.OperationalError) as exc_info:
                SessionDB(db_path)
            msg = str(exc_info.value)
            assert str(db_path) in msg
            assert "chmod" in msg
        finally:
            os.chmod(db_path, 0o644)
            hermes_state._set_last_init_error(None)
