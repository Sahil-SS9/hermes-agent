from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "discord-bot-health.py"


def _module():
    spec = importlib.util.spec_from_file_location("discord_bot_health", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_discovers_all_current_gateway_service_units(monkeypatch) -> None:
    module = _module()

    def fake_run(command, **kwargs):
        assert command == [
            "systemctl",
            "list-unit-files",
            "--type=service",
            "--no-legend",
            "hermes-gateway*.service",
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "hermes-gateway.service disabled enabled\n"
                "hermes-gateway-quan.service disabled enabled\n"
                "hermes-gateway-kensei-review.service disabled enabled\n"
                "unrelated.service enabled enabled\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.discover_services() == [
        ("kensei", "hermes-gateway.service"),
        ("kensei-review", "hermes-gateway-kensei-review.service"),
        ("quan", "hermes-gateway-quan.service"),
    ]
