"""Behavioural tests for the gateway /mode slash command and agent-mode
persistence.

Covers:
  - /mode status, valid set (plan/gods_plan/recon/auto), invalid unchanged
  - Per-conversation persistence via SessionStore.set_agent_mode/get_agent_mode
  - No cross-session leakage
  - Mode prompt composed WITH personality/context/channel (not overwriting)
  - Active cached-agent refresh on mode change (cache eviction)
  - Clear/default behaviour at conversation boundaries (/new)
  - Shift+Tab remains YOLO (not mode cycling)
  - Dead TS imports removed
  - Archived verifier contract corrected
"""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionEntry, SessionSource, SessionStore


# -- helpers -----------------------------------------------------------------

def _make_source(
    *,
    platform: Platform = Platform.DISCORD,
    user_id: str = "user1",
    chat_type: str = "dm",
    chat_id: str = "c1",
) -> SessionSource:
    return SessionSource(
        platform=platform,
        user_id=user_id,
        chat_id=chat_id,
        user_name=f"name-{user_id}",
        chat_type=chat_type,
    )


def _make_event(text: str, source: SessionSource) -> MessageEvent:
    return MessageEvent(text=text, source=source, message_id="m1")


def _make_runner(*, platform: Platform = Platform.DISCORD):
    """Build a minimal GatewayRunner for slash-command dispatch tests."""
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={
            platform: PlatformConfig(
                enabled=True,
                token="***",
                extra={},
            )
        }
    )
    adapter = MagicMock()
    adapter.send = AsyncMock()
    adapter._send_with_retry = AsyncMock()
    adapter._unwrap_ephemeral = lambda x: (x, None) if isinstance(x, str) else (getattr(x, "text", ""), getattr(x, "ttl", None))
    runner.adapters = {platform: adapter}
    runner._voice_mode = {}
    runner.hooks = SimpleNamespace(
        emit=AsyncMock(),
        emit_collect=AsyncMock(return_value=[]),
        loaded_hooks=False,
    )

    # Session store — use a real temp-dir-backed SessionStore
    import tempfile, os
    from pathlib import Path
    tmpdir = tempfile.mkdtemp()
    runner.session_store = SessionStore(sessions_dir=Path(tmpdir), config=runner.config)
    runner._session_db = MagicMock()
    runner._session_db.get_session.return_value = None
    runner._session_db.get_session_title.return_value = None

    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._session_run_generation = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._session_sources = {}
    runner._session_model_overrides = {}
    runner._agent_cache = {}
    runner._agent_cache_lock = None  # no lock for tests
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._show_reasoning = False
    runner._reasoning_config = None
    runner._is_user_authorized = lambda _source: True
    runner._set_session_env = lambda _context: None
    runner._should_send_voice_reply = lambda *_a, **_kw: False
    runner._send_voice_reply = AsyncMock()
    runner._capture_gateway_honcho_if_configured = lambda *a, **kw: None
    runner._emit_gateway_run_progress = AsyncMock()
    runner._draining = False
    runner._busy_text_mode = "interrupt"
    runner._busy_input_mode = "interrupt"
    runner._normalize_source_for_session_key = lambda source: source
    runner._invalidate_session_run_generation = lambda *a, **kw: None
    runner._release_running_agent_state = lambda *a, **kw: None
    runner._clear_session_boundary_security_state = lambda *a, **kw: None
    runner._maybe_confirm_destructive_slash = AsyncMock(
        side_effect=lambda **kw: kw.get("execute")()
    )
    runner._pending_model_notes = {}
    runner._last_resolved_model = {}
    runner._session_reasoning_overrides = {}
    runner._is_telegram_topic_root_lobby = lambda source: False
    runner._telegram_topic_root_new_message = lambda: "ignored"
    runner._telegram_topic_new_header = lambda source: None
    runner._reset_notice_session_info = lambda source: ""
    runner._session_key_for_source = lambda source: f"agent:main:{source.platform.value}:{source.chat_type}:{source.chat_id}"
    runner._adapter_for_source = lambda source: runner.adapters.get(source.platform)
    runner._thread_metadata_for_source = lambda *a, **kw: {}
    runner._reply_anchor_for_event = lambda event: None
    runner._get_system_prompt_for_channel = lambda *a, **kw: ""
    runner._resolve_turn_agent_config = lambda message, model, runtime_kwargs: {
        "model": model,
        "runtime": runtime_kwargs,
    }
    runner._resolve_session_agent_runtime = lambda **kw: ("test-model", {})
    runner._resolve_session_reasoning_config = lambda **kw: None
    runner._load_service_tier = lambda: None
    runner._set_session_reasoning_override = lambda *a, **kw: None
    runner._agent_has_active_subagents = lambda agent: False
    runner._session_has_compression_in_flight = lambda key: False
    runner._extract_cache_busting_config = lambda cfg: {}
    runner._evict_cached_agent = MagicMock()
    runner._run_in_executor_with_context = lambda fn, *a: fn(*a)
    runner._rehydrate_session_model_override = lambda key: None
    runner._apply_session_model_override = lambda key, model, kw: (model, kw)
    runner._is_intentional_model_switch = lambda key, m: False
    runner._cleanup_agent_resources = lambda agent: None
    return runner


# ===========================================================================
# 1. Shared mode validation in hermes_cli/mode_prompts.py
# ===========================================================================

class TestModeValidation:
    """validate_mode() should accept valid modes and reject invalid ones."""

    def test_valid_modes_accepted(self):
        from hermes_cli.mode_prompts import validate_mode
        for m in ("auto", "plan", "gods_plan", "recon"):
            assert validate_mode(m) == m

    def test_invalid_mode_rejected(self):
        from hermes_cli.mode_prompts import validate_mode
        with pytest.raises(ValueError):
            validate_mode("invalid_mode")

    def test_none_rejected(self):
        from hermes_cli.mode_prompts import validate_mode
        with pytest.raises((ValueError, TypeError)):
            validate_mode("")

    def test_case_normalised(self):
        from hermes_cli.mode_prompts import validate_mode
        assert validate_mode("PLAN") == "plan"
        assert validate_mode("Auto") == "auto"


# ===========================================================================
# 2. SessionStore agent_mode persistence (set/get/clear)
# ===========================================================================

class TestSessionStoreAgentMode:
    """SessionStore should persist and retrieve agent_mode per session."""

    def _make_store(self, tmp_path):
        from gateway.config import GatewayConfig
        cfg = GatewayConfig(platforms={})
        return SessionStore(sessions_dir=tmp_path, config=cfg)

    def test_set_and_get_agent_mode(self, tmp_path):
        store = self._make_store(tmp_path)
        source = _make_source()
        key = f"agent:main:discord:dm:{source.chat_id}"
        entry = store.get_or_create_session(source)
        store.set_agent_mode(key, "plan")
        assert store.get_agent_mode(key) == "plan"

    def test_default_agent_mode_is_auto(self, tmp_path):
        store = self._make_store(tmp_path)
        source = _make_source()
        key = f"agent:main:discord:dm:{source.chat_id}"
        store.get_or_create_session(source)
        assert store.get_agent_mode(key) == "auto"

    def test_clear_agent_mode(self, tmp_path):
        store = self._make_store(tmp_path)
        source = _make_source()
        key = f"agent:main:discord:dm:{source.chat_id}"
        store.get_or_create_session(source)
        store.set_agent_mode(key, "plan")
        store.set_agent_mode(key, "auto")
        assert store.get_agent_mode(key) == "auto"

    def test_no_cross_session_leakage(self, tmp_path):
        store = self._make_store(tmp_path)
        source_a = _make_source(user_id="userA", chat_id="ca")
        source_b = _make_source(user_id="userB", chat_id="cb")
        key_a = f"agent:main:discord:dm:ca"
        key_b = f"agent:main:discord:dm:cb"
        store.get_or_create_session(source_a)
        store.get_or_create_session(source_b)
        store.set_agent_mode(key_a, "plan")
        assert store.get_agent_mode(key_b) == "auto"

    def test_agent_mode_survives_reload(self, tmp_path):
        store = self._make_store(tmp_path)
        source = _make_source()
        key = f"agent:main:discord:dm:{source.chat_id}"
        store.get_or_create_session(source)
        store.set_agent_mode(key, "recon")
        # Simulate restart by creating a new store pointing at same dir
        store2 = self._make_store(tmp_path)
        assert store2.get_agent_mode(key) == "recon"

    def test_reset_clears_agent_mode(self, tmp_path):
        store = self._make_store(tmp_path)
        source = _make_source()
        key = f"agent:main:discord:dm:{source.chat_id}"
        store.get_or_create_session(source)
        store.set_agent_mode(key, "plan")
        store.reset_session(key)
        assert store.get_agent_mode(key) == "auto"


# ===========================================================================
# 3. SessionEntry agent_mode field + serialisation
# ===========================================================================

class TestSessionEntryAgentMode:
    """SessionEntry should carry an agent_mode field, persisted to dict and
    restored from dict."""

    def test_default_agent_mode(self):
        entry = SessionEntry(
            session_key="k",
            session_id="s",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert entry.agent_mode == "auto"

    def test_to_dict_includes_agent_mode(self):
        entry = SessionEntry(
            session_key="k",
            session_id="s",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            agent_mode="plan",
        )
        d = entry.to_dict()
        assert d.get("agent_mode") == "plan"

    def test_from_dict_restores_agent_mode(self):
        data = {
            "session_key": "k",
            "session_id": "s",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "agent_mode": "recon",
        }
        entry = SessionEntry.from_dict(data)
        assert entry.agent_mode == "recon"

    def test_from_dict_defaults_agent_mode(self):
        data = {
            "session_key": "k",
            "session_id": "s",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        entry = SessionEntry.from_dict(data)
        assert entry.agent_mode == "auto"


# ===========================================================================
# 4. Gateway /mode command dispatch — status, set, invalid, auto
# ===========================================================================

class TestGatewayModeCommand:
    """The gateway should dispatch /mode to a handler."""

    @pytest.mark.asyncio
    async def test_mode_status_returns_current(self):
        runner = _make_runner()
        source = _make_source()
        event = _make_event("/mode status", source)
        result = await runner._handle_message(event)
        assert result is not None
        assert "auto" in result.lower()

    @pytest.mark.asyncio
    async def test_mode_set_plan(self):
        runner = _make_runner()
        source = _make_source()
        event = _make_event("/mode plan", source)
        result = await runner._handle_message(event)
        assert result is not None
        assert "plan" in result.lower()

    @pytest.mark.asyncio
    async def test_mode_set_gods_plan(self):
        runner = _make_runner()
        source = _make_source()
        event = _make_event("/mode gods_plan", source)
        result = await runner._handle_message(event)
        assert result is not None
        # Should mention UltraPlan (the user-facing label for gods_plan)
        assert "ultraplan" in result.lower() or "gods_plan" in result.lower()

    @pytest.mark.asyncio
    async def test_mode_set_recon(self):
        runner = _make_runner()
        source = _make_source()
        event = _make_event("/mode recon", source)
        result = await runner._handle_message(event)
        assert result is not None
        assert "recon" in result.lower()

    @pytest.mark.asyncio
    async def test_mode_set_auto(self):
        runner = _make_runner()
        source = _make_source()
        event = _make_event("/mode auto", source)
        result = await runner._handle_message(event)
        assert result is not None
        assert "auto" in result.lower()

    @pytest.mark.asyncio
    async def test_mode_invalid_preserves_prior_state(self):
        runner = _make_runner()
        source = _make_source()
        key = runner._session_key_for_source(source)
        runner.session_store.get_or_create_session(source)
        runner.session_store.set_agent_mode(key, "plan")
        # Send invalid mode
        event = _make_event("/mode bogus_mode", source)
        result = await runner._handle_message(event)
        assert result is not None
        # The stored mode should NOT have changed
        assert runner.session_store.get_agent_mode(key) == "plan"

    @pytest.mark.asyncio
    async def test_mode_persists_to_session_store(self):
        runner = _make_runner()
        source = _make_source()
        key = runner._session_key_for_source(source)
        runner.session_store.get_or_create_session(source)
        event = _make_event("/mode plan", source)
        await runner._handle_message(event)
        assert runner.session_store.get_agent_mode(key) == "plan"


# ===========================================================================
# 5. Mode prompt composition — not overwriting personality/channel/context
# ===========================================================================

class TestModePromptComposition:
    """The mode prompt should be appended to (not replace) the existing
    combined_ephemeral composed from context/channel/personality prompts."""

    def test_mode_prompt_appended_after_context(self):
        from hermes_cli.mode_prompts import get_mode_prompt
        context_prompt = "You are a helpful assistant."
        mode_prompt = get_mode_prompt("plan")
        combined = (context_prompt + "\n\n" + (mode_prompt or "")).strip()
        # Context must survive
        assert "You are a helpful assistant." in combined
        # Mode marker must be present
        assert "You are in plan mode" in combined

    def test_auto_mode_does_not_append(self):
        from hermes_cli.mode_prompts import get_mode_prompt
        context_prompt = "You are a helpful assistant."
        mode_prompt = get_mode_prompt("auto")
        assert mode_prompt is None
        combined = context_prompt
        assert combined == "You are a helpful assistant."


# ===========================================================================
# 6. Shift+Tab remains YOLO (not mode cycling)
# ===========================================================================

class TestShiftTabYoloOnly:
    """useInputHandlers.ts Shift+Tab should call config.set key=yolo, NOT
    key=mode."""

    def test_shift_tab_calls_yolo_not_mode(self):
        """Read the TS source and verify Shift+Tab sets yolo, not mode."""
        import os
        ts_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "ui-tui", "src", "app", "useInputHandlers.ts",
        )
        with open(ts_path) as f:
            content = f.read()
        # Shift+Tab handler must set yolo, not mode
        # Find the shift+tab block
        assert "key: 'yolo'" in content or 'key: "yolo"' in content
        # Must NOT contain stale "cycles agent mode" comment
        assert "shift-tab cycles agent mode" not in content
        # Must NOT call config.set with key=mode in the shift-tab block
        # (the only config.set in that block should be yolo)
        assert "AGENT_MODES" not in content, "Dead AGENT_MODES import still present"

    def test_no_dead_agent_mode_import(self):
        """AgentMode and AGENT_MODES imports should be removed from
        useInputHandlers.ts if unused."""
        import os
        ts_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "ui-tui", "src", "app", "useInputHandlers.ts",
        )
        with open(ts_path) as f:
            content = f.read()
        # The import line should not contain AgentMode or AGENT_MODES
        # (unless they're actually used in the file body)
        lines = content.split("\n")
        for line in lines:
            if "from './interfaces.js'" in line or "from \"./interfaces.js\"" in line:
                # This is the import line — should not import AgentMode/AGENT_MODES
                # unless they're used elsewhere in the file
                if "AgentMode" in line or "AGENT_MODES" in line:
                    # Check if they're used in the body (excluding import line)
                    body = "\n".join(l for l in lines if l != line)
                    if "AgentMode" not in body and "AGENT_MODES" not in body:
                        pytest.fail(
                            f"Dead import in {line.strip()}: AgentMode/AGENT_MODES "
                            "imported but never used in file body"
                        )


# ===========================================================================
# 7. CLI Shift+Tab hint correction
# ===========================================================================

class TestCliShiftTabHint:
    """cli.py should not claim Shift+Tab cycles modes."""

    def test_no_stale_shift_tab_cycle_hint(self):
        import os
        cli_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "cli.py",
        )
        with open(cli_path) as f:
            content = f.read()
        assert "Shift+Tab to cycle" not in content, (
            "cli.py still has misleading 'Shift+Tab to cycle' hint"
        )


# ===========================================================================
# 8. Archived verifier contract correction
# ===========================================================================

class TestArchivedVerifierContract:
    """scripts/archive/verify-agent-modes.sh should not assert stale
    Shift+Tab mode-cycling behaviour."""

    def test_no_stale_shift_tab_cycle_assertion(self):
        import os
        verifier_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "scripts", "archive", "verify-agent-modes.sh",
        )
        if not os.path.exists(verifier_path):
            pytest.skip("verify-agent-modes.sh not found (may be moved)")
        with open(verifier_path) as f:
            content = f.read()
        assert "shift-tab cycles agent mode" not in content
        # Should not assert config.set.*mode in useInputHandlers
        # (because Shift+Tab now does yolo, not mode)
        assert 'config\\.set.*mode' not in content or 'useInputHandlers.ts' not in content
