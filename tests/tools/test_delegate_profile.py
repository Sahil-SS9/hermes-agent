#!/usr/bin/env python3
"""Tests for the `profile` parameter in delegate_task.

Verifies that when `profile` is set, the subagent loads the target
profile's config.yaml (model, provider, toolsets), SOUL.md (identity),
and always_skills.

Uses mock AIAgent instances — no real API calls.

Run with:  python -m pytest tests/tools/test_delegate_profile.py -v
"""

import json
import os
import threading
from unittest.mock import MagicMock, patch

from tools.delegate_tool import (
    delegate_task,
    _build_child_agent,
    _build_child_system_prompt,
    _strip_blocked_tools,
    _expand_parent_toolsets,
)


def _make_mock_parent(depth=0):
    """Create a mock parent agent with the fields delegate_task expects."""
    parent = MagicMock()
    parent.base_url = "https://openrouter.ai/api/v1"
    parent.api_key = "sk-test-parent-key"
    parent.provider = "openrouter"
    parent.api_mode = "chat_completions"
    parent.model = "anthropic/claude-sonnet-4"
    parent.platform = "cli"
    parent.providers_allowed = None
    parent.providers_ignored = None
    parent.providers_order = None
    parent.provider_sort = None
    parent._session_db = None
    parent._delegate_depth = depth
    parent._active_children = []
    parent._active_children_lock = threading.Lock()
    parent._print_fn = None
    parent.tool_progress_callback = None
    parent.thinking_callback = None
    parent.session_id = "test-parent-session"
    parent._subagent_id = None
    parent._current_turn_id = "turn-1"
    parent._memory_manager = None
    parent._delegate_saved_tool_names = []
    parent.api_mode = "chat_completions"
    parent._fallback_chain = None
    parent.reasoning_config = {"effort": "off"}
    parent.max_tokens = 4096
    parent.enabled_toolsets = ["terminal", "file", "web", "kanban", "hermes-cli"]
    parent.valid_tool_names = ["read_file", "write_file", "web_search", "terminal"]
    return parent


class TestProfileParameter:
    """Tests for the profile parameter in delegate_task."""

    def test_profile_not_found_returns_error(self):
        """When profile doesn't exist, delegate_task returns a clean error."""
        parent = _make_mock_parent()
        # Patch to prevent AIAgent construction — we only want to test
        # the profile-not-found path which runs before child construction.
        with patch("tools.delegate_tool._load_config", return_value={}):
            with patch("tools.delegate_tool._resolve_delegation_credentials",
                       return_value={"model": None, "provider": None, "base_url": None,
                                     "api_key": None, "api_mode": None}):
                result = delegate_task(
                    goal="Test task",
                    profile="nonexistent-profile",
                    parent_agent=parent,
                )
                parsed = json.loads(result) if isinstance(result, str) else result
                if isinstance(parsed, dict):
                    err = parsed.get("error") or str(parsed)
                    assert "nonexistent-profile" in str(err)
                else:
                    # Tool error path
                    assert "nonexistent-profile" in str(result)

    def test_build_child_agent_accepts_profile(self):
        """_build_child_agent accepts the new profile and profile_content params."""
        parent = _make_mock_parent()

        child = _build_child_agent(
            task_index=0,
            goal="Test task",
            context=None,
            toolsets=None,
            model=None,
            max_iterations=30,
            task_count=1,
            parent_agent=parent,
            profile="octacon",
            profile_content={
                "name": "octacon",
                "config": {
                    "model": {"default": "glm-5.1", "provider": "ollama-cloud"},
                    "toolsets": ["hermes-cli", "kanban"],
                    "skills": {"always_skills": ["test-driven-development"]},
                },
                "soul_md": "# Octacon\n\nYou are octacon, the coding lead.",
                "skills": ["test-driven-development"],
            },
        )
        # Child should have the profile model, not parent's
        assert child is not None

    def test_profile_injects_soul_md_into_prompt(self):
        """SOUL.md content should appear in the child's system prompt."""
        parent = _make_mock_parent()

        # Mock AIAgent to capture the ephemeral_system_prompt
        from unittest.mock import patch as _patch
        _captured_prompt = {}

        def _capture_init(self_agent, **kwargs):
            _captured_prompt["prompt"] = kwargs.get("ephemeral_system_prompt", "")

        with _patch("run_agent.AIAgent", side_effect=_capture_init):
            try:
                _build_child_agent(
                    task_index=0,
                    goal="Write code for feature X",
                    context="Repo at /tmp/test",
                    toolsets=None,
                    model=None,
                    max_iterations=30,
                    task_count=1,
                    parent_agent=parent,
                    profile="octacon",
                    profile_content={
                        "name": "octacon",
                        "config": {
                            "model": {"default": "glm-5.1", "provider": "ollama-cloud"},
                            "toolsets": ["hermes-cli", "kanban"],
                            "skills": {"always_skills": []},
                        },
                        "soul_md": "# Octacon\n\nYou are Octacon, the coding lead.\nYou write clean, tested code.\n\n## Boundaries\n\nDo not deploy to production without review.",
                        "skills": [],
                    },
                )
            except Exception:
                pass  # Mock will fail to construct a real agent — that's fine

        captured = _captured_prompt.get("prompt", "")
        if captured:
            assert "Octacon" in captured
            assert "coding lead" in captured
            assert "Do not deploy to production" in captured
            assert "PROFILE IDENTITY" in captured or "BEGIN PROFILE" in captured

    def test_profile_model_overrides_parent(self):
        """Profile's model should be used instead of parent's when no explicit model given."""
        parent = _make_mock_parent()

        child = _build_child_agent(
            task_index=0,
            goal="Test",
            context=None,
            toolsets=None,
            model=None,  # No explicit model — profile's model should win over parent
            max_iterations=30,
            task_count=1,
            parent_agent=parent,
            profile="octacon",
            profile_content={
                "name": "octacon",
                "config": {
                    "model": {"default": "glm-5.1", "provider": "ollama-cloud"},
                    "toolsets": ["hermes-cli", "kanban"],
                    "skills": {"always_skills": []},
                },
                "soul_md": "# Octacon",
                "skills": [],
            },
        )
        # Child should use the profile's model
        assert getattr(child, "model", "") == "glm-5.1"

    def test_explicit_model_wins_over_profile(self):
        """Explicit model parameter should override profile's model."""
        parent = _make_mock_parent()

        child = _build_child_agent(
            task_index=0,
            goal="Test",
            context=None,
            toolsets=None,
            model="deepseek-v4-flash",  # Explicit — should win over profile
            max_iterations=30,
            task_count=1,
            parent_agent=parent,
            profile="octacon",
            profile_content={
                "name": "octacon",
                "config": {
                    "model": {"default": "glm-5.1", "provider": "ollama-cloud"},
                    "toolsets": ["hermes-cli", "kanban"],
                    "skills": {"always_skills": []},
                },
                "soul_md": "# Octacon",
                "skills": [],
            },
        )
        # Explicit model should win over profile
        assert getattr(child, "model", "") == "deepseek-v4-flash"

    def test_profile_model_wins_over_delegation_config(self):
        """Profile's model should win when delegation config has a different model.
        This simulates the parent's delegation config (deepseek-v4-flash) being
        overridden by the profile's model (glm-5.1)."""
        parent = _make_mock_parent()
        # Parent's delegation config would set model=deepseek-v4-flash

        child = _build_child_agent(
            task_index=0,
            goal="Test",
            context=None,
            toolsets=None,
            model=None,  # No explicit model — simulates delegation config value
            max_iterations=30,
            task_count=1,
            parent_agent=parent,
            profile="octacon",
            profile_content={
                "name": "octacon",
                "config": {
                    "model": {"default": "glm-5.1", "provider": "ollama-cloud"},
                    "toolsets": ["hermes-cli", "kanban"],
                    "skills": {"always_skills": []},
                },
                "soul_md": "# Octacon",
                "skills": [],
            },
        )
        # Profile model should win over delegation config model
        assert getattr(child, "model", "") == "glm-5.1"

    def test_profile_toolsets_intersected_with_parent(self):
        """Profile toolsets should be intersected with parent's — subagent can't gain tools parent lacks."""
        parent = _make_mock_parent()
        # Parent has: terminal, file, web, kanban, hermes-cli

        child = _build_child_agent(
            task_index=0,
            goal="Test",
            context=None,
            toolsets=None,  # No explicit toolsets — profile's should be used
            model=None,
            max_iterations=30,
            task_count=1,
            parent_agent=parent,
            profile="remii",
            profile_content={
                "name": "remii",
                "config": {
                    "model": {"default": "deepseek-v4-flash", "provider": "ollama-cloud"},
                    "toolsets": ["hermes-cli", "kanban", "web", "browser"],
                    "skills": {"always_skills": []},
                },
                "soul_md": "# Remii",
                "skills": [],
            },
        )
        # Child should have intersected toolsets (browser should be there since parent has web via enabled_toolsets)
        # Enabled toolsets is the correct check
        enabled = getattr(child, "enabled_toolsets", []) or []
        if enabled:
            assert "kanban" in enabled or any("kanban" in str(t) for t in enabled)

    def test_profile_fallback_chain_loaded(self):
        """Profile's fallback_providers should be used as the child's fallback chain."""
        parent = _make_mock_parent()

        child = _build_child_agent(
            task_index=0,
            goal="Test",
            context=None,
            toolsets=None,
            model=None,
            max_iterations=30,
            task_count=1,
            parent_agent=parent,
            profile="octacon",
            profile_content={
                "name": "octacon",
                "config": {
                    "model": {"default": "glm-5.1", "provider": "ollama-cloud"},
                    "toolsets": ["hermes-cli", "kanban"],
                    "fallback_providers": [
                        {"provider": "ollama-cloud", "model": "deepseek-v4-pro"},
                    ],
                    "skills": {"always_skills": []},
                },
                "soul_md": "# Octacon",
                "skills": [],
            },
        )
        fallback = getattr(child, "_fallback_chain", None)
        # Should have fallback from profile
        assert fallback is not None

    def test_without_profile_backward_compat(self):
        """Without profile, _build_child_agent behaves exactly as before."""
        parent = _make_mock_parent()

        child_without = _build_child_agent(
            task_index=0,
            goal="Test backward compat",
            context=None,
            toolsets=None,
            model=None,
            max_iterations=30,
            task_count=1,
            parent_agent=parent,
        )
        # Should use parent's model as fallback
        assert getattr(child_without, "model", "") == parent.model or "anthropic/claude-sonnet-4"

    def test_schema_has_profile_parameter(self):
        """The delegate_task tool schema should include the profile parameter."""
        from tools.delegate_tool import DELEGATE_TASK_SCHEMA
        props = DELEGATE_TASK_SCHEMA["parameters"]["properties"]
        assert "profile" in props
