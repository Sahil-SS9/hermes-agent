"""
``hermes validate-config`` — run all config validations and exit non-zero on
warnings.

Scans the user's config.yaml for common misconfigurations:

- auxiliary.<task> entries where base_url is empty but provider is "auto"
  (the task silently falls through the full auto-detection chain).
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

    if warnings:
        for w in warnings:
            print(w)
        return 1

    print("Config validation passed — no warnings found.")
    return 0
