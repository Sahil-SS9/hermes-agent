from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from scripts.mailbox_cleaner.cli import main
from scripts.mailbox_cleaner.mcp_connector import (
    ControlledMcpConfigError,
    McpReadOnlyAdapter,
    McpReadOnlyError,
    load_controlled_stdio_config,
)
from scripts.mailbox_cleaner.policy import AccountPolicy


class RecordingSession:
    def __init__(self, response: Mapping[str, object]) -> None:
        self.response = response
        self.envelopes: list[dict[str, object]] = []
        self.closed = False

    def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        self.envelopes.append(dict(envelope))
        return self.response

    def close(self) -> None:
        self.closed = True


def test_adapter_sends_explicit_account_in_allowlisted_stdio_tools_call_and_normalises_content():
    session = RecordingSession(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "value": [
                                    {
                                        "id": "message-1",
                                        "from": {"emailAddress": {"address": "recruiter@example.test"}},
                                        "subject": "Interview",
                                        "receivedDateTime": "2026-07-18T09:00:00Z",
                                        "bodyPreview": "Choose a time",
                                    }
                                ]
                            }
                        ),
                    }
                ]
            },
        }
    )
    adapter = McpReadOnlyAdapter(session)

    rows = adapter("list_metadata", "jobs@example.test", provider="outlook")

    assert session.envelopes == [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "list_mail_messages",
                "arguments": {"account": "jobs@example.test"},
            },
        }
    ]
    assert rows == [
        {
            "id": "message-1",
            "from": "recruiter@example.test",
            "subject": "Interview",
            "received_at": "2026-07-18T09:00:00Z",
            "preview": "Choose a time",
        }
    ]
    adapter.close()
    assert session.closed


@pytest.mark.parametrize("operation", ["archive", "delete_message", "send_mail", "mark_read"])
def test_adapter_rejects_mutations_before_any_transport_request(operation: str):
    session = RecordingSession({"result": {"content": []}})
    adapter = McpReadOnlyAdapter(session)

    with pytest.raises(McpReadOnlyError, match="allowlisted"):
        adapter(operation, "jobs@example.test", provider="outlook")

    assert session.envelopes == []


def test_adapter_requires_nonempty_account_and_rejects_unknown_provider():
    adapter = McpReadOnlyAdapter(RecordingSession({"result": {"content": []}}))

    with pytest.raises(McpReadOnlyError, match="explicit account"):
        adapter("list_metadata", "", provider="outlook")
    with pytest.raises(McpReadOnlyError, match="provider"):
        adapter("list_metadata", "jobs@example.test", provider="graph")


def test_adapter_rejects_mcp_error_and_non_text_or_malformed_response():
    error_adapter = McpReadOnlyAdapter(
        RecordingSession({"jsonrpc": "2.0", "id": 1, "error": {"message": "not authorised"}})
    )
    with pytest.raises(McpReadOnlyError, match="not authorised"):
        error_adapter("list_metadata", "jobs@example.test", provider="outlook")

    malformed_adapter = McpReadOnlyAdapter(
        RecordingSession({"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "nope"}]}})
    )
    with pytest.raises(McpReadOnlyError, match="JSON"):
        malformed_adapter("list_metadata", "jobs@example.test", provider="outlook")


def test_controlled_stdio_config_is_strict_and_contains_explicit_accounts(tmp_path: Path):
    config = tmp_path / "mailbox-mcp.json"
    config.write_text(
        json.dumps(
            {
                "command": "/opt/mcp/read-only-mail",
                "args": ["--read-only"],
                "accounts": [{"account": "jobs@example.test", "provider": "outlook"}],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_controlled_stdio_config(config)

    assert loaded.command == ("/opt/mcp/read-only-mail", "--read-only")
    assert loaded.policies == (AccountPolicy(account="jobs@example.test", provider="outlook"),)

    for unsafe in (
        {"command": "mail", "accounts": []},
        {"command": "mail", "accounts": [{"account": "jobs@example.test", "provider": "outlook"}], "env": {}},
        {"command": "mail", "accounts": [{"account": "", "provider": "outlook"}]},
    ):
        config.write_text(json.dumps(unsafe), encoding="utf-8")
        with pytest.raises(ControlledMcpConfigError):
            load_controlled_stdio_config(config)


def test_cli_refuses_live_transport_without_both_operator_controls(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    config = tmp_path / "mailbox-mcp.json"
    config.write_text(
        json.dumps(
            {
                "command": "/opt/mcp/read-only-mail",
                "accounts": [{"account": "jobs@example.test", "provider": "outlook"}],
            }
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state.json"

    with pytest.raises(SystemExit) as missing_flag:
        main(["--mcp-stdio-config", str(config), "--state", str(state)])
    assert missing_flag.value.code == 2
    assert "--allow-controlled-read" in capsys.readouterr().err

    with pytest.raises(SystemExit) as missing_config:
        main(["--allow-controlled-read", "--state", str(state)])
    assert missing_config.value.code == 2
    assert "--mcp-stdio-config" in capsys.readouterr().err


def test_connector_source_has_no_direct_provider_oauth_or_cache_imports():
    source = Path(__file__).resolve().parents[3] / "scripts" / "mailbox_cleaner" / "mcp_connector.py"
    text = source.read_text(encoding="utf-8")

    forbidden = ("requests", "httpx", "urllib", "oauth", "msgraph", "googleapiclient", "token_cache")
    assert not any(token in text.lower() for token in forbidden)
