from hermes_state import AsyncSessionDB
"""Tests for gateway /usage command — agent cache lookup and output fields."""

import threading
from unittest.mock import MagicMock, patch

import pytest


def _make_mock_agent(**overrides):
    """Create a mock AIAgent with realistic session counters."""
    agent = MagicMock()
    defaults = {
        "model": "anthropic/claude-sonnet-4.6",
        "provider": "openrouter",
        "base_url": None,
        "session_total_tokens": 50_000,
        "session_api_calls": 5,
        "session_prompt_tokens": 40_000,
        "session_completion_tokens": 10_000,
        "session_input_tokens": 35_000,
        "session_output_tokens": 10_000,
        "session_cache_read_tokens": 5_000,
        "session_cache_write_tokens": 2_000,
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(agent, k, v)

    # Rate limit state
    rl = MagicMock()
    rl.has_data = True
    agent.get_rate_limit_state.return_value = rl

    # Context compressor
    ctx = MagicMock()
    ctx.last_prompt_tokens = 30_000
    ctx.context_length = 200_000
    ctx.compression_count = 1
    agent.context_compressor = ctx

    return agent


def _make_runner(session_key, agent=None, cached_agent=None):
    """Build a bare GatewayRunner with just the fields _handle_usage_command needs."""
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._agent_cache = {}
    runner._agent_cache_lock = threading.Lock()
    runner.session_store = MagicMock()

    if agent is not None:
        runner._running_agents[session_key] = agent

    if cached_agent is not None:
        runner._agent_cache[session_key] = (cached_agent, "sig")

    # Wire helper
    runner._session_key_for_source = MagicMock(return_value=session_key)

    return runner


SK = "agent:main:telegram:private:12345"


class TestUsageCachedAgent:
    """The main fix: /usage should find agents in _agent_cache between turns."""

    @pytest.mark.asyncio
    async def test_cached_agent_shows_detailed_usage(self):
        agent = _make_mock_agent()
        runner = _make_runner(SK, cached_agent=agent)
        event = MagicMock()

        with patch("agent.rate_limit_tracker.format_rate_limit_compact", return_value="RPM: 50/60"):
            result = await runner._handle_usage_command(event)

        assert "claude-sonnet-4.6" in result
        assert "35,000" in result  # input tokens
        assert "10,000" in result  # output tokens
        assert "50,000" in result  # total
        assert "30,000" in result  # context
        assert "Compressions: 1" in result
        # Cost and cache-hit reporting is removed everywhere.
        assert "$" not in result
        assert "Cache read" not in result
        assert "Cache write" not in result
        assert "Cost" not in result

    @pytest.mark.asyncio
    async def test_running_agent_preferred_over_cache(self):
        """When agent is in both dicts, the running one wins."""
        running = _make_mock_agent(session_api_calls=10, session_total_tokens=80_000)
        cached = _make_mock_agent(session_api_calls=5, session_total_tokens=50_000)
        runner = _make_runner(SK, agent=running, cached_agent=cached)
        event = MagicMock()

        with patch("agent.rate_limit_tracker.format_rate_limit_compact", return_value="RPM: 50/60"), \
             patch("agent.usage_pricing.estimate_usage_cost") as mock_cost:
            mock_cost.return_value = MagicMock(amount_usd=None, status="unknown")
            result = await runner._handle_usage_command(event)

        assert "80,000" in result   # running agent's total
        assert "API calls: 10" in result

    @pytest.mark.asyncio
    async def test_sentinel_skipped_uses_cache(self):
        """PENDING sentinel in _running_agents should fall through to cache."""
        from gateway.run import _AGENT_PENDING_SENTINEL

        cached = _make_mock_agent()
        runner = _make_runner(SK, cached_agent=cached)
        runner._running_agents[SK] = _AGENT_PENDING_SENTINEL
        event = MagicMock()

        with patch("agent.rate_limit_tracker.format_rate_limit_compact", return_value="RPM: 50/60"), \
             patch("agent.usage_pricing.estimate_usage_cost") as mock_cost:
            mock_cost.return_value = MagicMock(amount_usd=None, status="unknown")
            result = await runner._handle_usage_command(event)

        assert "claude-sonnet-4.6" in result
        assert "Session Token Usage" in result

    @pytest.mark.asyncio
    async def test_no_agent_anywhere_falls_to_history(self):
        """No running or cached agent → rough estimate from transcript."""
        runner = _make_runner(SK)
        event = MagicMock()

        session_entry = MagicMock()
        session_entry.session_id = "sess123"
        runner.session_store.get_or_create_session.return_value = session_entry
        runner.session_store.load_transcript.return_value = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]

        with patch("agent.model_metadata.estimate_messages_tokens_rough", return_value=500):
            result = await runner._handle_usage_command(event)

        assert "Session Info" in result
        assert "Messages: 2" in result
        assert "~500" in result

    @pytest.mark.asyncio
    async def test_cache_read_write_hidden_when_zero(self):
        """Cache token lines should be omitted when zero."""
        agent = _make_mock_agent(session_cache_read_tokens=0, session_cache_write_tokens=0)
        runner = _make_runner(SK, cached_agent=agent)
        event = MagicMock()

        with patch("agent.rate_limit_tracker.format_rate_limit_compact", return_value="RPM: 50/60"), \
             patch("agent.usage_pricing.estimate_usage_cost") as mock_cost:
            mock_cost.return_value = MagicMock(amount_usd=None, status="unknown")
            result = await runner._handle_usage_command(event)

        assert "Cache read" not in result
        assert "Cache write" not in result


class TestUsageAccountSection:
    """Account-limits section appended to /usage output (PR #2486)."""

    @pytest.mark.asyncio
    async def test_usage_command_includes_account_section(self, monkeypatch):
        agent = _make_mock_agent(provider="openai-codex")
        agent.base_url = "https://chatgpt.com/backend-api/codex"
        agent.api_key = "unused"
        runner = _make_runner(SK, cached_agent=agent)
        event = MagicMock()

        monkeypatch.setattr(
            "gateway.slash_commands.fetch_account_usage",
            lambda provider, base_url=None, api_key=None: object(),
        )
        monkeypatch.setattr(
            "gateway.slash_commands.render_account_usage_lines",
            lambda snapshot, markdown=False: [
                "📈 **Account limits**",
                "Provider: openai-codex (Pro)",
                "Session: 85% remaining (15% used)",
            ],
        )
        with patch("agent.rate_limit_tracker.format_rate_limit_compact", return_value="RPM: 50/60"), \
             patch("agent.usage_pricing.estimate_usage_cost") as mock_cost:
            mock_cost.return_value = MagicMock(amount_usd=None, status="included")
            result = await runner._handle_usage_command(event)

        assert "📊 **Session Token Usage**" in result
        assert "📈 **Account limits**" in result
        assert "Provider: openai-codex (Pro)" in result

    @pytest.mark.asyncio
    async def test_usage_command_uses_persisted_provider_when_agent_not_running(self, monkeypatch):
        runner = _make_runner(SK)
        runner._session_db = AsyncSessionDB(MagicMock())
        runner._session_db._db.get_session.return_value = {
            "billing_provider": "openai-codex",
            "billing_base_url": "https://chatgpt.com/backend-api/codex",
        }
        session_entry = MagicMock()
        session_entry.session_id = "sess-1"
        runner.session_store.get_or_create_session.return_value = session_entry
        runner.session_store.load_transcript.return_value = [
            {"role": "user", "content": "earlier"},
        ]

        calls = []

        async def _fake_to_thread(fn, *args, **kwargs):
            # /usage dispatches BOTH the account fetch (fetch_account_usage, called
            # with the provider positionally) and the Nous credits fetch
            # (nous_credits_lines, markdown-only) through to_thread — record every
            # call rather than last-wins so we can pick out the account fetch.
            calls.append({"args": args, "kwargs": kwargs})
            return fn(*args, **kwargs)

        monkeypatch.setattr("gateway.run.asyncio.to_thread", _fake_to_thread)
        monkeypatch.setattr(
            "gateway.slash_commands.fetch_account_usage",
            lambda provider, base_url=None, api_key=None: object(),
        )
        monkeypatch.setattr(
            "gateway.slash_commands.render_account_usage_lines",
            lambda snapshot, markdown=False: [
                "📈 **Account limits**",
                "Provider: openai-codex (Pro)",
            ],
        )
        # The credits block routes through the shared nous_credits_lines() helper;
        # stub it so this account-section test stays hermetic (no portal/auth lookup).
        monkeypatch.setattr("agent.account_usage.nous_credits_lines", lambda markdown=False: [])

        event = MagicMock()
        result = await runner._handle_usage_command(event)

        account_call = next(c for c in calls if c["args"] == ("openai-codex",))
        assert account_call["kwargs"]["base_url"] == "https://chatgpt.com/backend-api/codex"
        assert "📊 **Session Info**" in result
        assert "📈 **Account limits**" in result


class TestUsageReset:
    """`/usage reset [--force]` — banked Codex reset redemption via the gateway."""

    def _event(self, args):
        event = MagicMock()
        event.get_command_args.return_value = args
        return event

    @pytest.mark.asyncio
    async def test_reset_dispatches_redeem_for_codex_agent(self, monkeypatch):
        agent = _make_mock_agent(provider="openai-codex",
                                 base_url="https://chatgpt.com/backend-api/codex",
                                 api_key="tok")
        runner = _make_runner(SK, cached_agent=agent)

        seen = {}

        def fake_redeem(*, base_url=None, api_key=None, force=False):
            seen.update(base_url=base_url, api_key=api_key, force=force)
            from agent.account_usage import CodexResetRedeemResult
            return CodexResetRedeemResult(status="reset", message="✅ redeemed", available_count=1)

        monkeypatch.setattr("agent.account_usage.redeem_codex_reset_credit", fake_redeem)

        result = await runner._handle_usage_command(self._event("reset"))

        assert result == "✅ redeemed"
        assert seen["force"] is False
        assert seen["api_key"] == "tok"

    @pytest.mark.asyncio
    async def test_reset_force_flag_propagates(self, monkeypatch):
        agent = _make_mock_agent(provider="openai-codex", api_key="tok")
        runner = _make_runner(SK, cached_agent=agent)

        seen = {}

        def fake_redeem(*, base_url=None, api_key=None, force=False):
            seen["force"] = force
            from agent.account_usage import CodexResetRedeemResult
            return CodexResetRedeemResult(status="reset", message="ok")

        monkeypatch.setattr("agent.account_usage.redeem_codex_reset_credit", fake_redeem)

        await runner._handle_usage_command(self._event("reset --force"))

        assert seen["force"] is True

    @pytest.mark.asyncio
    async def test_reset_rejected_on_non_codex_provider(self, monkeypatch):
        agent = _make_mock_agent(provider="openrouter")
        runner = _make_runner(SK, cached_agent=agent)
        monkeypatch.setattr(
            "agent.account_usage.redeem_codex_reset_credit",
            lambda **kw: (_ for _ in ()).throw(AssertionError("must not redeem")),
        )

        result = await runner._handle_usage_command(self._event("reset"))

        assert "openai-codex" in result

    @pytest.mark.asyncio
    async def test_unknown_subcommand_rejected(self):
        agent = _make_mock_agent(provider="openai-codex")
        runner = _make_runner(SK, cached_agent=agent)

        result = await runner._handle_usage_command(self._event("bogus"))

        assert "Unknown /usage subcommand" in result


class TestUsageContextBreakdown:
    """The /usage output includes the per-category context breakdown."""

    @pytest.mark.asyncio
    async def test_breakdown_lines_rendered_for_live_agent(self):
        agent = _make_mock_agent()
        runner = _make_runner(SK, cached_agent=agent)
        session_entry = MagicMock()
        session_entry.session_id = "sess-bd"
        runner.session_store.get_or_create_session.return_value = session_entry
        runner.session_store.load_transcript.return_value = [
            {"role": "user", "content": "hi"},
        ]
        event = MagicMock()

        fake_payload = {
            "categories": [
                {"id": "system_prompt", "label": "System prompt", "tokens": 4000, "color": "x"},
                {"id": "tool_definitions", "label": "Tool definitions", "tokens": 6000, "color": "x"},
                {"id": "conversation", "label": "Conversation", "tokens": 0, "color": "x"},
            ],
            "estimated_total": 10000,
            "context_max": 200000,
            "context_percent": 5,
            "context_used": 30000,
            "model": "anthropic/claude-sonnet-4.6",
        }

        with patch("agent.rate_limit_tracker.format_rate_limit_compact", return_value="RPM: 50/60"), \
             patch("agent.context_breakdown.compute_session_context_breakdown", return_value=fake_payload):
            result = await runner._handle_usage_command(event)

        # Localized header + at least the two non-zero category labels appear,
        # each labelled as a percentage of the estimated total.
        assert "Context breakdown" in result
        assert "System prompt" in result
        assert "Tool definitions" in result
        assert "4,000" in result   # system prompt tokens, comma-formatted
        assert "40%" in result     # 4000 / 10000
        assert "60%" in result     # 6000 / 10000
        # Zero-token category is dropped, not rendered.
        assert "Conversation" not in result

    @pytest.mark.asyncio
    async def test_breakdown_failure_is_non_fatal(self):
        """A breakdown engine error must not break the rest of /usage."""
        agent = _make_mock_agent()
        runner = _make_runner(SK, cached_agent=agent)
        runner.session_store.get_or_create_session.side_effect = RuntimeError("boom")
        event = MagicMock()

        with patch("agent.rate_limit_tracker.format_rate_limit_compact", return_value="RPM: 50/60"), \
             patch("agent.context_breakdown.compute_session_context_breakdown",
                   side_effect=RuntimeError("engine down")):
            result = await runner._handle_usage_command(event)

        # Core usage lines still render; no breakdown header.
        assert "📊 **Session Token Usage**" in result
        assert "50,000" in result  # total tokens
        assert "Context breakdown" not in result


# ── Account-binding guard: gateway /usage reset must be session-bound ──────

class TestUsageResetAccountBinding:
    """The destructive /usage reset must only proceed when an active/cached
    agent's exact api_key is available — NOT when provider/base_url come only
    from persisted billing state (which carries no credential). Without a
    session-bound credential the helper would silently resolve singleton/pool
    state and spend a reset belonging to an account the gateway session never
    authenticated as."""

    def _event(self, args):
        event = MagicMock()
        event.get_command_args.return_value = args
        return event

    @pytest.mark.asyncio
    async def test_reset_refuses_when_only_persisted_billing(self, monkeypatch):
        """provider/base_url from persisted billing, no active/cached agent
        credential (api_key=None) → fail-closed before calling the helper."""
        runner = _make_runner(SK)
        runner._session_db = AsyncSessionDB(MagicMock())
        runner._session_db._db.get_session.return_value = {
            "billing_provider": "openai-codex",
            "billing_base_url": "https://chatgpt.com/backend-api/codex",
        }
        session_entry = MagicMock()
        session_entry.session_id = "sess-1"
        runner.session_store.get_or_create_session.return_value = session_entry

        def _must_not_redeem(**kw):
            raise AssertionError("redeem must not run without session-bound credential")

        monkeypatch.setattr("agent.account_usage.redeem_codex_reset_credit", _must_not_redeem)

        result = await runner._handle_usage_command(self._event("reset"))

        assert "send a message" in result.lower() or "authenticate" in result.lower()

    @pytest.mark.asyncio
    async def test_reset_forwards_active_agent_credential(self, monkeypatch):
        """Active/cached agent with exact api_key and base_url → those are
        forwarded to the helper, not resolved from singleton/pool."""
        agent = _make_mock_agent(provider="openai-codex",
                                 base_url="https://chatgpt.com/backend-api/codex",
                                 api_key="session-bound-token")
        runner = _make_runner(SK, cached_agent=agent)

        seen = {}

        def fake_redeem(*, base_url=None, api_key=None, force=False):
            seen.update(base_url=base_url, api_key=api_key, force=force)
            from agent.account_usage import CodexResetRedeemResult
            return CodexResetRedeemResult(status="reset", message="✅ redeemed", available_count=1)

        monkeypatch.setattr("agent.account_usage.redeem_codex_reset_credit", fake_redeem)

        result = await runner._handle_usage_command(self._event("reset"))

        assert result == "✅ redeemed"
        assert seen["api_key"] == "session-bound-token"
        assert seen["base_url"] == "https://chatgpt.com/backend-api/codex"

    @pytest.mark.asyncio
    async def test_reset_cannot_borrow_other_session_credential(self, monkeypatch):
        """Session A has a cached codex agent; session B has none. B's
        /usage reset must NOT use A's cached credential."""
        agent_a = _make_mock_agent(provider="openai-codex",
                                   base_url="https://chatgpt.com/backend-api/codex",
                                   api_key="session-a-token")
        SK_B = "agent:main:telegram:private:99999"
        runner = _make_runner(SK, cached_agent=agent_a)
        # Session B has no running agent and no cached agent.
        runner._session_key_for_source = MagicMock(side_effect=lambda source: SK_B)
        runner._session_db = AsyncSessionDB(MagicMock())
        runner._session_db._db.get_session.return_value = {
            "billing_provider": "openai-codex",
            "billing_base_url": "https://chatgpt.com/backend-api/codex",
        }
        session_entry = MagicMock()
        session_entry.session_id = "sess-b"
        runner.session_store.get_or_create_session.return_value = session_entry

        def _must_not_redeem(**kw):
            raise AssertionError("must not borrow session A's credential")

        monkeypatch.setattr("agent.account_usage.redeem_codex_reset_credit", _must_not_redeem)

        result = await runner._handle_usage_command(self._event("reset"))

        assert "send a message" in result.lower() or "authenticate" in result.lower()

    @pytest.mark.asyncio
    async def test_reset_force_does_not_bypass_credential_guard(self, monkeypatch):
        """--force bypasses the exhaustion guard but NOT the account-binding
        guard: no credential → still refused."""
        runner = _make_runner(SK)
        runner._session_db = AsyncSessionDB(MagicMock())
        runner._session_db._db.get_session.return_value = {
            "billing_provider": "openai-codex",
            "billing_base_url": "https://chatgpt.com/backend-api/codex",
        }
        session_entry = MagicMock()
        session_entry.session_id = "sess-1"
        runner.session_store.get_or_create_session.return_value = session_entry

        def _must_not_redeem(**kw):
            raise AssertionError("force must not bypass credential guard")

        monkeypatch.setattr("agent.account_usage.redeem_codex_reset_credit", _must_not_redeem)

        result = await runner._handle_usage_command(self._event("reset --force"))

        assert "send a message" in result.lower() or "authenticate" in result.lower()

    @pytest.mark.asyncio
    async def test_bare_usage_display_unchanged_with_persisted_billing(self, monkeypatch):
        """Bare /usage (display) must still work with persisted billing state —
        the credential guard is scoped to the destructive reset path only."""
        runner = _make_runner(SK)
        runner._session_db = AsyncSessionDB(MagicMock())
        runner._session_db._db.get_session.return_value = {
            "billing_provider": "openai-codex",
            "billing_base_url": "https://chatgpt.com/backend-api/codex",
        }
        session_entry = MagicMock()
        session_entry.session_id = "sess-1"
        runner.session_store.get_or_create_session.return_value = session_entry
        runner.session_store.load_transcript.return_value = [
            {"role": "user", "content": "earlier"},
        ]

        monkeypatch.setattr("gateway.slash_commands.fetch_account_usage",
                            lambda provider, base_url=None, api_key=None: object())
        monkeypatch.setattr("gateway.slash_commands.render_account_usage_lines",
                            lambda snapshot, markdown=False: ["📈 **Account limits**"])
        monkeypatch.setattr("agent.account_usage.nous_credits_lines", lambda markdown=False: [])

        event = MagicMock()
        result = await runner._handle_usage_command(event)

        # Display path still works — account lines present.
        assert "📈 **Account limits**" in result


class TestUsageResetArgParsing:
    """Unknown extra args on /usage reset must NOT silently trigger the
    destructive action. Only `reset` and `reset --force` are valid."""

    def _event(self, args):
        event = MagicMock()
        event.get_command_args.return_value = args
        return event

    @pytest.mark.asyncio
    async def test_reset_with_unknown_extra_arg_refused(self, monkeypatch):
        agent = _make_mock_agent(provider="openai-codex", api_key="tok")
        runner = _make_runner(SK, cached_agent=agent)

        def _must_not_redeem(**kw):
            raise AssertionError("unknown extra arg must not trigger redeem")

        monkeypatch.setattr("agent.account_usage.redeem_codex_reset_credit", _must_not_redeem)

        result = await runner._handle_usage_command(self._event("reset bogus"))

        assert "unknown" in result.lower() or "unrecognized" in result.lower() or "try" in result.lower()

    @pytest.mark.asyncio
    async def test_reset_force_with_extra_arg_refused(self, monkeypatch):
        agent = _make_mock_agent(provider="openai-codex", api_key="tok")
        runner = _make_runner(SK, cached_agent=agent)

        def _must_not_redeem(**kw):
            raise AssertionError("extra arg after --force must not trigger redeem")

        monkeypatch.setattr("agent.account_usage.redeem_codex_reset_credit", _must_not_redeem)

        result = await runner._handle_usage_command(self._event("reset --force bogus"))

        assert "unknown" in result.lower() or "unrecognized" in result.lower() or "try" in result.lower()
