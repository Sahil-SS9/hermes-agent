"""Tests for Temporal Knowledge Graph Extension in Mnemosyne TripleStore.

Covers:
1. Temporal fields (valid_from, valid_until) storage and retrieval
2. Conflict invalidation (supersede=True) — old facts get valid_until set
3. get_facts_valid_at for past, present, and future timestamps
4. Existing query functions with temporal filters
5. MCP tool schema registration for mnemosyne_triple_facts_valid_at
"""

import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from mnemosyne.core.triples import TripleStore, init_triples
from mnemosyne.tool_schemas import ALL_TOOL_SCHEMAS, TRIPLE_FACTS_VALID_AT_SCHEMA


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path():
    """Yield a temporary DB path; cleanup after test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    if path.exists():
        path.unlink()


@pytest.fixture
def store(db_path):
    """Return a TripleStore backed by a temp DB."""
    return TripleStore(db_path=db_path)


# ---------------------------------------------------------------------------
# 1. Temporal fields — storage and retrieval
# ---------------------------------------------------------------------------

class TestTemporalFields:
    """Verify valid_from / valid_until are stored and retrieved correctly."""

    def test_add_sets_valid_from_default(self, store):
        """add() without valid_from defaults to today's date."""
        tid = store.add("alice", "assigned_to", "auth-migration")
        row = store.conn.execute(
            "SELECT * FROM triples WHERE id = ?", (tid,)
        ).fetchone()
        assert row is not None
        # valid_from should be set to today (YYYY-MM-DD)
        import datetime
        today = datetime.date.today().isoformat()
        assert row["valid_from"] == today
        assert row["valid_until"] is None

    def test_add_with_explicit_valid_from(self, store):
        """add() with explicit valid_from stores the given date."""
        tid = store.add(
            "alice", "assigned_to", "auth-migration",
            valid_from="2026-01-15",
        )
        row = store.conn.execute(
            "SELECT * FROM triples WHERE id = ?", (tid,)
        ).fetchone()
        assert row["valid_from"] == "2026-01-15"
        assert row["valid_until"] is None

    def test_add_with_explicit_valid_until(self, store):
        """add() with explicit valid_until stores the expiry date."""
        tid = store.add(
            "alice", "assigned_to", "temp-task",
            valid_from="2026-01-15",
            valid_until="2026-03-01",
        )
        row = store.conn.execute(
            "SELECT * FROM triples WHERE id = ?", (tid,)
        ).fetchone()
        assert row["valid_from"] == "2026-01-15"
        assert row["valid_until"] == "2026-03-01"

    def test_retrieve_temporal_fields_in_query(self, store):
        """query() returns valid_from and valid_until in results."""
        store.add("bob", "role", "developer", valid_from="2026-02-01")
        results = store.query(subject="bob")
        assert len(results) == 1
        assert "valid_from" in results[0]
        assert "valid_until" in results[0]
        assert results[0]["valid_from"] == "2026-02-01"

    def test_retrieve_temporal_fields_in_get_facts_valid_at(self, store):
        """get_facts_valid_at() returns valid_from and valid_until."""
        store.add("carol", "prefers", "vim", valid_from="2026-03-01")
        results = store.get_facts_valid_at("2026-06-01")
        carol_rows = [r for r in results if r["subject"] == "carol"]
        assert len(carol_rows) == 1
        assert "valid_from" in carol_rows[0]
        assert "valid_until" in carol_rows[0]
        assert carol_rows[0]["valid_from"] == "2026-03-01"


# ---------------------------------------------------------------------------
# 2. Conflict invalidation
# ---------------------------------------------------------------------------

class TestConflictInvalidation:
    """Verify supersede=True closes prior facts and inserts new ones."""

    def test_supersede_closes_prior(self, store):
        """Adding same (subject, predicate) with supersede=True closes old."""
        store.add("dave", "assigned_to", "project-alpha",
                  valid_from="2026-01-01")
        store.add("dave", "assigned_to", "project-beta",
                  valid_from="2026-03-01")

        # Old row should have valid_until set
        old = store.conn.execute(
            "SELECT * FROM triples WHERE subject = ? AND predicate = ? AND object = ?",
            ("dave", "assigned_to", "project-alpha"),
        ).fetchone()
        assert old is not None
        assert old["valid_until"] == "2026-03-01"

        # New row should have valid_until NULL
        new = store.conn.execute(
            "SELECT * FROM triples WHERE subject = ? AND predicate = ? AND object = ?",
            ("dave", "assigned_to", "project-beta"),
        ).fetchone()
        assert new is not None
        assert new["valid_until"] is None
        assert new["valid_from"] == "2026-03-01"

    def test_supersede_query_current(self, store):
        """query() without as_of returns only current (non-superseded) facts."""
        store.add("eve", "assigned_to", "task-1", valid_from="2026-01-01")
        store.add("eve", "assigned_to", "task-2", valid_from="2026-02-01")

        results = store.query(subject="eve")
        # Only the current (non-superseded) fact should appear
        assert len(results) == 1
        assert results[0]["object"] == "task-2"

    def test_supersede_query_as_of_past(self, store):
        """query() with as_of returns facts valid at that past date."""
        store.add("frank", "assigned_to", "task-old",
                  valid_from="2026-01-01")
        store.add("frank", "assigned_to", "task-new",
                  valid_from="2026-03-01")

        # Query as of Feb 1 — should see the old fact
        results = store.query(subject="frank", as_of="2026-02-01")
        assert len(results) == 1
        assert results[0]["object"] == "task-old"

    def test_supersede_query_as_of_future(self, store):
        """query() with future as_of returns current fact."""
        store.add("grace", "assigned_to", "task-current",
                  valid_from="2026-01-01")
        results = store.query(subject="grace", as_of="2026-12-01")
        assert len(results) == 1
        assert results[0]["object"] == "task-current"

    def test_supersede_false_preserves_multiple(self, store):
        """supersede=False allows multiple values for same (subject, predicate)."""
        store.add("hugo", "speaks", "English", supersede=False)
        store.add("hugo", "speaks", "Spanish", supersede=False)

        results = store.query(subject="hugo")
        assert len(results) == 2
        objects = {r["object"] for r in results}
        assert objects == {"English", "Spanish"}

    def test_supersede_false_no_invalidation(self, store):
        """supersede=False does NOT set valid_until on prior rows."""
        store.add("ivy", "speaks", "French", supersede=False)
        store.add("ivy", "speaks", "German", supersede=False)

        old = store.conn.execute(
            "SELECT * FROM triples WHERE subject = ? AND predicate = ? AND object = ?",
            ("ivy", "speaks", "French"),
        ).fetchone()
        assert old is not None
        assert old["valid_until"] is None  # Not invalidated

    def test_end_closes_without_replacement(self, store):
        """end() closes open triples without inserting a new one."""
        store.add("jack", "assigned_to", "task-x", valid_from="2026-01-01")
        store.end("jack", "assigned_to", valid_until="2026-06-01")

        # The triple should now be closed
        row = store.conn.execute(
            "SELECT * FROM triples WHERE subject = ? AND predicate = ?",
            ("jack", "assigned_to"),
        ).fetchone()
        assert row["valid_until"] == "2026-06-01"

        # query() should not return it (it's expired)
        results = store.query(subject="jack")
        assert len(results) == 0

    def test_end_specific_object(self, store):
        """end() with object param closes only that specific triple."""
        store.add("kate", "speaks", "English", supersede=False,
                  valid_from="2026-01-01")
        store.add("kate", "speaks", "Spanish", supersede=False,
                  valid_from="2026-01-01")

        store.end("kate", "speaks", object="English", valid_until="2026-03-01")

        english = store.conn.execute(
            "SELECT * FROM triples WHERE subject = ? AND predicate = ? AND object = ?",
            ("kate", "speaks", "English"),
        ).fetchone()
        assert english["valid_until"] == "2026-03-01"

        spanish = store.conn.execute(
            "SELECT * FROM triples WHERE subject = ? AND predicate = ? AND object = ?",
            ("kate", "speaks", "Spanish"),
        ).fetchone()
        assert spanish["valid_until"] is None  # Still open


# ---------------------------------------------------------------------------
# 3. get_facts_valid_at
# ---------------------------------------------------------------------------

class TestGetFactsValidAt:
    """Verify get_facts_valid_at returns correct facts for any timestamp."""

    def test_past_timestamp(self, store):
        """Facts valid at a past timestamp are returned."""
        store.add("liam", "assigned_to", "legacy", valid_from="2026-01-01")
        store.add("liam", "assigned_to", "current", valid_from="2026-03-01")

        results = store.get_facts_valid_at("2026-02-01")
        liam_rows = [r for r in results if r["subject"] == "liam"]
        assert len(liam_rows) == 1
        assert liam_rows[0]["object"] == "legacy"

    def test_present_timestamp(self, store):
        """Facts valid at present timestamp are returned."""
        store.add("mia", "role", "engineer", valid_from="2026-01-01")
        results = store.get_facts_valid_at("2026-06-01")
        mia_rows = [r for r in results if r["subject"] == "mia"]
        assert len(mia_rows) == 1
        assert mia_rows[0]["object"] == "engineer"

    def test_future_timestamp(self, store):
        """Facts with future valid_from are NOT returned for earlier timestamps."""
        store.add("noah", "role", "future-role", valid_from="2026-12-01")
        results = store.get_facts_valid_at("2026-06-01")
        noah_rows = [r for r in results if r["subject"] == "noah"]
        assert len(noah_rows) == 0

    def test_expired_fact_excluded(self, store):
        """Facts with valid_until in the past are excluded."""
        store.add("olivia", "role", "intern",
                  valid_from="2026-01-01", valid_until="2026-03-01")
        results = store.get_facts_valid_at("2026-06-01")
        olivia_rows = [r for r in results if r["subject"] == "olivia"]
        assert len(olivia_rows) == 0

    def test_expired_fact_included_at_correct_time(self, store):
        """Facts with valid_until are included when querying before expiry."""
        store.add("peter", "role", "intern",
                  valid_from="2026-01-01", valid_until="2026-03-01")
        results = store.get_facts_valid_at("2026-02-01")
        peter_rows = [r for r in results if r["subject"] == "peter"]
        assert len(peter_rows) == 1
        assert peter_rows[0]["object"] == "intern"

    def test_mixed_validity(self, store):
        """Multiple facts with different validity windows are correctly filtered."""
        store.add("quinn", "role", "junior",
                  valid_from="2026-01-01", valid_until="2026-06-01")
        store.add("quinn", "role", "senior",
                  valid_from="2026-06-01")

        # Before the promotion
        results = store.get_facts_valid_at("2026-03-01")
        quinn_rows = [r for r in results if r["subject"] == "quinn"]
        assert len(quinn_rows) == 1
        assert quinn_rows[0]["object"] == "junior"

        # At the promotion date (valid_until > timestamp is strict)
        results = store.get_facts_valid_at("2026-06-01")
        quinn_rows = [r for r in results if r["subject"] == "quinn"]
        assert len(quinn_rows) == 1
        assert quinn_rows[0]["object"] == "senior"

        # After the promotion
        results = store.get_facts_valid_at("2026-09-01")
        quinn_rows = [r for r in results if r["subject"] == "quinn"]
        assert len(quinn_rows) == 1
        assert quinn_rows[0]["object"] == "senior"

    def test_iso_timestamp_with_time(self, store):
        """get_facts_valid_at works with full ISO 8601 timestamps."""
        store.add("rose", "status", "active",
                  valid_from="2026-01-01T00:00:00")
        results = store.get_facts_valid_at("2026-06-15T12:30:00")
        rose_rows = [r for r in results if r["subject"] == "rose"]
        assert len(rose_rows) == 1

    def test_empty_result(self, store):
        """get_facts_valid_at returns empty list when no facts match."""
        results = store.get_facts_valid_at("2026-01-01")
        assert results == []

    def test_all_facts_returned(self, store):
        """get_facts_valid_at returns all valid facts across all subjects."""
        store.add("sam", "role", "dev", valid_from="2026-01-01")
        store.add("tina", "role", "qa", valid_from="2026-01-01")
        results = store.get_facts_valid_at("2026-06-01")
        assert len(results) == 2
        subjects = {r["subject"] for r in results}
        assert subjects == {"sam", "tina"}


# ---------------------------------------------------------------------------
# 4. Existing query functions with temporal filters
# ---------------------------------------------------------------------------

class TestQueryTemporalFilters:
    """Verify existing query functions respect temporal validity."""

    def test_query_by_predicate_as_of(self, store):
        """query_by_predicate with as_of filters correctly."""
        store.add("uma", "mentions", "project-x",
                  valid_from="2026-01-01", valid_until="2026-03-01")
        store.add("uma", "mentions", "project-y",
                  valid_from="2026-03-01")

        # Before the switch
        results = store.query_by_predicate(
            "mentions", subject="uma", as_of="2026-02-01"
        )
        assert len(results) == 1
        assert results[0]["object"] == "project-x"

        # After the switch
        results = store.query_by_predicate(
            "mentions", subject="uma", as_of="2026-06-01"
        )
        assert len(results) == 1
        assert results[0]["object"] == "project-y"

    def test_query_by_predicate_no_as_of(self, store):
        """query_by_predicate without as_of returns all (no temporal filter)."""
        store.add("victor", "mentions", "topic-a",
                  valid_from="2026-01-01", valid_until="2026-03-01")
        store.add("victor", "mentions", "topic-b",
                  valid_from="2026-03-01")

        results = store.query_by_predicate("mentions", subject="victor")
        # Without as_of, no temporal filter is applied
        assert len(results) == 2

    def test_get_distinct_objects(self, store):
        """get_distinct_objects returns all distinct values regardless of validity."""
        store.add("wendy", "role", "dev", valid_from="2026-01-01")
        store.add("xander", "role", "dev", valid_from="2026-01-01")
        store.add("yara", "role", "qa", valid_from="2026-01-01")
        objects = store.get_distinct_objects("role")
        assert set(objects) == {"dev", "qa"}

    def test_export_all_includes_temporal_fields(self, store):
        """export_all includes valid_from and valid_until."""
        store.add("zoe", "role", "lead", valid_from="2026-01-01",
                  valid_until="2026-06-01")
        exported = store.export_all()
        assert len(exported) == 1
        assert "valid_from" in exported[0]
        assert "valid_until" in exported[0]
        assert exported[0]["valid_from"] == "2026-01-01"
        assert exported[0]["valid_until"] == "2026-06-01"


# ---------------------------------------------------------------------------
# 5. MCP tool schema registration
# ---------------------------------------------------------------------------

class TestMCPToolSchema:
    """Verify mnemosyne_triple_facts_valid_at is registered as an MCP tool."""

    def test_schema_defined(self):
        """TRIPLE_FACTS_VALID_AT_SCHEMA has the correct structure."""
        assert TRIPLE_FACTS_VALID_AT_SCHEMA["name"] == "mnemosyne_triple_facts_valid_at"
        assert "timestamp" in TRIPLE_FACTS_VALID_AT_SCHEMA["parameters"]["required"]
        assert TRIPLE_FACTS_VALID_AT_SCHEMA["parameters"]["properties"]["timestamp"]["type"] == "string"

    def test_schema_in_all_tools(self):
        """TRIPLE_FACTS_VALID_AT_SCHEMA is registered in ALL_TOOL_SCHEMAS."""
        names = [s["name"] for s in ALL_TOOL_SCHEMAS]
        assert "mnemosyne_triple_facts_valid_at" in names

    def test_schema_description(self):
        """Schema has a meaningful description."""
        desc = TRIPLE_FACTS_VALID_AT_SCHEMA["description"]
        assert len(desc) > 20
        assert "valid" in desc.lower()

    def test_handler_registered(self):
        """The handler is registered in mcp_tools dispatch table."""
        from mnemosyne.mcp_tools import _TOOL_HANDLERS
        assert "mnemosyne_triple_facts_valid_at" in _TOOL_HANDLERS


# ---------------------------------------------------------------------------
# 6. Integration: end-to-end through MCP handler
# ---------------------------------------------------------------------------

class TestMCPHandlerIntegration:
    """End-to-end test through the MCP handler function."""

    def test_handler_returns_valid_facts(self, db_path):
        """_handle_triple_facts_valid_at returns correct facts."""
        from mnemosyne.mcp_tools import _handle_triple_facts_valid_at

        # Set up env so _create_instance uses our temp DB via a test bank
        os.environ["MNEMOSYNE_DATA_DIR"] = str(db_path.parent)
        os.environ["MNEMOSYNE_HOME"] = str(db_path.parent)
        os.environ["MNEMOSYNE_MCP_BANK"] = "test_temporal_bank"

        # Create the bank DB path that _create_instance will resolve to
        bank_dir = db_path.parent / "banks" / "test_temporal_bank"
        bank_dir.mkdir(parents=True, exist_ok=True)
        bank_db = bank_dir / "mnemosyne.db"

        # Add triples to the bank DB directly
        store = TripleStore(db_path=bank_db)
        store.add("integration_user", "role", "tester",
                  valid_from="2026-01-01")
        store.add("integration_user", "role", "lead",
                  valid_from="2026-06-01")

        # Verify triples were written
        rows = store.conn.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
        assert rows == 2, f"Expected 2 triples, got {rows}"

        # Call the handler — it will resolve to the bank DB
        result = _handle_triple_facts_valid_at({"timestamp": "2026-03-01"})
        assert result["status"] == "ok"
        assert result["timestamp"] == "2026-03-01"
        assert result["count"] >= 1, f"Expected >=1 results, got {result}"
        integration_rows = [
            r for r in result["results"]
            if r["subject"] == "integration_user"
        ]
        assert len(integration_rows) == 1
        assert integration_rows[0]["object"] == "tester"

        # Cleanup env
        del os.environ["MNEMOSYNE_MCP_BANK"]

    def test_handler_requires_timestamp(self, db_path):
        """_handle_triple_facts_valid_at errors without timestamp."""
        from mnemosyne.mcp_tools import _handle_triple_facts_valid_at
        result = _handle_triple_facts_valid_at({})
        assert "error" in result
        assert "timestamp" in result["error"].lower()

    def test_handler_empty_result(self, db_path):
        """_handle_triple_facts_valid_at returns empty for no matches."""
        from mnemosyne.mcp_tools import _handle_triple_facts_valid_at
        os.environ["MNEMOSYNE_DATA_DIR"] = str(db_path.parent)
        os.environ["MNEMOSYNE_HOME"] = str(db_path.parent)
        result = _handle_triple_facts_valid_at({"timestamp": "2025-01-01"})
        assert result["status"] == "ok"
        assert result["count"] == 0
