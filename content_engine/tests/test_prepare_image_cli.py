"""Provider-free CLI consumption of prepared ad-hoc image requests."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_engine_script(monkeypatch) -> ModuleType:
    """Load the executable module, never the similarly named package."""
    engine_path = Path(__file__).resolve().parents[1] / "content_engine.py"
    monkeypatch.syspath_prepend(str(engine_path.parent))
    spec = importlib.util.spec_from_file_location("_content_engine_script", engine_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_prepare_image_cli_returns_a_plan_without_opening_the_content_database(
    monkeypatch, capsys
) -> None:
    engine = _load_engine_script(monkeypatch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "content_engine.py",
            "prepare-image",
            "--prompt",
            "A high-density map of the agent runtime.",
            "--style",
            "Data Atlas",
            "--reference",
            "https://example.com/brief.pdf",
        ],
    )

    def _database_must_not_open() -> None:
        raise AssertionError("provider-free prepare-image must not open the content database")

    monkeypatch.setattr(engine, "init_db", _database_must_not_open)

    assert engine.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["backend"] == "codex"
    assert payload["style_id"] == "data-atlas"
    assert payload["references"] == ["https://example.com/brief.pdf"]
