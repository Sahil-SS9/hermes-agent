"""
``hermes validate-config`` — run all config validations and exit non-zero on
warnings.

Scans the user's config.yaml for common misconfigurations:

- auxiliary.<task> entries where base_url is empty but provider is "auto"
  (the task silently falls through the full auto-detection chain).
- pipeline.<setting> invalid types or values.
"""

import os
import sys
import yaml
from pathlib import Path


def _get_user_config_raw() -> dict:
    """Load the user's config.yaml without merging DEFAULT_CONFIG defaults."""
    hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    config_path = Path(hermes_home) / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def run_validate_config(args) -> int:
    """Run all config validators, print findings, return exit code."""
    user_config = _get_user_config_raw()
    warnings: list[str] = []

    # Validate auxiliary task configs — only check tasks the user explicitly
    # configured in their config.yaml (not built-in DEFAULT_CONFIG defaults).
    user_auxiliary = user_config.get("auxiliary", {})
    if isinstance(user_auxiliary, dict):
        for task_name, task_cfg in user_auxiliary.items():
            if not isinstance(task_cfg, dict):
                continue
            provider = str(task_cfg.get("provider", "")).strip()
            base_url = str(task_cfg.get("base_url", "")).strip()
            if not base_url and provider == "auto":
                warnings.append(
                    f"  WARNING: auxiliary.{task_name}: base_url is empty with "
                    f"provider 'auto'. May fall back unexpectedly."
                )

    # Validate pipeline config — check for common misconfigurations.
    user_pipeline = user_config.get("pipeline", {})
    if isinstance(user_pipeline, dict):
        # Validate max_revise_loops is positive int
        max_revise = user_pipeline.get("max_revise_loops")
        if max_revise is not None:
            if not isinstance(max_revise, int) or max_revise < 1:
                warnings.append(
                    f"  WARNING: pipeline.max_revise_loops must be a positive "
                    f"integer, got {max_revise!r}."
                )
        # Validate token_cap is None or positive int
        token_cap = user_pipeline.get("token_cap")
        if token_cap is not None:
            if not isinstance(token_cap, int) or token_cap < 1:
                warnings.append(
                    f"  WARNING: pipeline.token_cap must be null or a positive "
                    f"integer, got {token_cap!r}."
                )
        # Validate stage_owners is a dict
        stage_owners = user_pipeline.get("stage_owners")
        if stage_owners is not None and not isinstance(stage_owners, dict):
            warnings.append(
                f"  WARNING: pipeline.stage_owners must be a dict, "
                f"got {type(stage_owners).__name__}."
            )

    if warnings:
        for w in warnings:
            print(w)
        return 1

    print("Config validation passed — no warnings found.")
    return 0
