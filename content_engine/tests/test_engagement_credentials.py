"""Tests for engagement credential configuration."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ce_dir = Path(__file__).resolve().parent.parent
if str(ce_dir) not in sys.path:
    sys.path.insert(0, str(ce_dir))

XURL_ENV = {
    "XURL_CLIENT_ID": "client-id-test",
    "XURL_CLIENT_SECRET": "client-secret-test",
    "XURL_CONSUMER_KEY": "consumer-key-test",
    "XURL_CONSUMER_SECRET": "consumer-secret-test",
}


def _set_xurl_env(monkeypatch):
    for name, value in XURL_ENV.items():
        monkeypatch.setenv(name, value)


def test_configure_xurl_success(monkeypatch, tmp_path):
    """Writes config only from the four required environment variables."""
    _set_xurl_env(monkeypatch)
    xurl_path = tmp_path / ".xurl"

    import subprocess

    mock_result = MagicMock(returncode=0, stderr="")
    mock_result.stdout = "1|test-name|access-token:access-secret|rtok|Sahil_Saghir\n"
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_result)
    monkeypatch.setattr("os.path.expanduser", lambda path: str(xurl_path))

    from engagement_suggester import configure_xurl_from_postiz

    assert configure_xurl_from_postiz() is True
    config_text = xurl_path.read_text()
    for name, value in XURL_ENV.items():
        yaml_key = name.removeprefix("XURL_").lower()
        assert f"{yaml_key}: {value}" in config_text


@pytest.mark.parametrize("missing", tuple(XURL_ENV))
def test_configure_xurl_fails_when_any_required_credential_is_missing(monkeypatch, missing):
    """A missing credential must stop the config write cleanly."""
    _set_xurl_env(monkeypatch)
    monkeypatch.delenv(missing)

    from engagement_suggester import configure_xurl_from_postiz

    assert configure_xurl_from_postiz() is False


def test_no_committed_xurl_credential_literals():
    """The xurl configuration path must not assign credential literals in source."""
    import engagement_suggester as module

    source = Path(module.__file__).read_text()
    assignment_literal = re.compile(
        r'(?m)^(?!\s*#).*\b(?:client_id|client_secret|consumer_key|consumer_secret)'
        r'\s*=\s*["\'][^"\']{6,}["\']'
    )
    rendered_config_literal = re.compile(
        r'(?m)^\s*(?:client_id|client_secret|consumer_key|consumer_secret):'
        r'\s*[A-Za-z0-9_-]{6,}\s*$'
    )
    assert assignment_literal.search(source) is None
    assert rendered_config_literal.search(source) is None
