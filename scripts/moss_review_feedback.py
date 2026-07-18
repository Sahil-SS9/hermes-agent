#!/usr/bin/env python3
"""Read-only Mossy PR-review feedback normalisation and prevention-loop helpers.

This module deliberately has no write-capable GitHub or git path.  It turns
already-fetched JSON into a locally persisted, auditable triage queue.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Sequence

SELF_AUTHORS = {"sahil-ss9", "sahil", "mossy"}
MAINTAINER_AUTHORS = {"teknium"}
PROMOTABLE = {"routine_patch", "sahil_escalation"}


def feedback_paths() -> dict[str, Path]:
    """Return distinct state surfaces below the sandboxable HERMES_HOME."""
    home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
    data = home / "data"
    return {
        "state": data / "moss-review-feedback-state.json",
        "queue": data / "moss-review-feedback-queue.json",
        "ledger": data / "moss-review-feedback-ledger.json",
        "rules": data / "moss-review-feedback-rules.json",
    }


def load_json(path: Path, default: Any) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def atomic_write_json(path: Path, value: Any) -> None:
    """Write one JSON document atomically without sharing a temp path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _author(item: dict[str, Any]) -> str:
    source = item.get("author") or item.get("user") or {}
    return str(source.get("login") or source.get("name") or item.get("author_login") or "")


def _excluded_author(author: str) -> bool:
    normal = author.strip().lower()
    return not normal or normal in SELF_AUTHORS or "bot" in normal or "[bot]" in normal


def normalise_feedback(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise formal reviews, inline comments, and PR conversations.

    Each source is namespaced so GitHub IDs from different API surfaces cannot
    suppress each other during deduplication.
    """
    repo = str(payload["repo"])
    pr = payload["pr"]
    number = int(pr["number"])
    rows: list[dict[str, Any]] = []
    for surface, source_name, key_prefix in (
        ("review", "reviews", "review"),
        ("inline", "review_comments", "inline"),
        ("conversation", "comments", "conversation"),
    ):
        for item in payload.get(source_name, []):
            author = _author(item)
            if _excluded_author(author):
                continue
            item_id = str(item.get("id") or item.get("node_id") or "")
            if not item_id:
                continue
            rows.append({
                "key": f"{key_prefix}:{repo}#{number}:{item_id}",
                "surface": surface,
                "repo": repo,
                "pr_number": number,
                "pr_title": str(pr.get("title", "")),
                "pr_url": str(pr.get("url", "")),
                "author": author,
                "priority": "maintainer" if author.strip().lower() in MAINTAINER_AUTHORS else "normal",
                "body": str(item.get("body") or ""),
                "path": item.get("path"),
                "line": item.get("line") or item.get("original_line"),
                "review_state": item.get("state"),
            })
    return rows


def dedupe_records(records: list[dict[str, Any]], state: dict[str, Any]) -> list[dict[str, Any]]:
    seen = set(state.get("seen", []))
    return [record for record in records if record["key"] not in seen]


def classify_feedback(record: dict[str, Any]) -> str:
    """Conservative four-way matrix applied to every human reviewer.

    Maintainer identity changes queue priority, never the safety decision.
    """
    body = str(record.get("body", "")).lower()
    if any(term in body for term in (
        "security", "data loss", "breaking change", "architecture", "production outage",
        "unsafe", "privacy", "credential", "regression risk",
    )):
        return "sahil_escalation"
    if any(term in body for term in ("clarify", "could you explain", "why is", "what happens if")):
        return "clarification"
    if not body.strip() or any(term in body for term in ("looks good", "thanks", "thank you", "lgtm", "approved")):
        return "reply_only"
    return "routine_patch"


def classify_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**record, "classification": classify_feedback(record)} for record in records]


def promote_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only implementation work and explicit Sahil decisions enter the queue."""
    return [record for record in records if record["classification"] in PROMOTABLE]


def build_pre_push_report(
    classified: list[dict[str, Any]], promoted: list[dict[str, Any]], rules: dict[str, str]
) -> dict[str, Any]:
    counts = Counter(record["classification"] for record in classified)
    return {
        "counts": dict(counts),
        "promoted_keys": [record["key"] for record in promoted],
        "rule_selection": {kind: rules[kind] for kind in sorted(counts) if kind in rules},
        # A Sahil decision must be resolved before any eventual push workflow.
        "blocked": any(record["classification"] == "sahil_escalation" for record in classified),
    }


def _is_mutating_command(command: Sequence[str]) -> bool:
    lowered = [str(part).lower() for part in command]
    if not lowered:
        return True
    tool = lowered[0]
    if tool == "git":
        return any(token in {"push", "commit", "merge", "rebase", "reset", "tag", "branch", "checkout", "switch", "cherry-pick"} for token in lowered[1:])
    if tool == "gh":
        mutating = {"comment", "close", "merge", "edit", "create", "delete", "reopen", "review"}
        return any(token in mutating for token in lowered[1:]) or any(token in {"post", "put", "patch", "delete"} for token in lowered)
    return True


def run_read_only(command: Sequence[str], *, runner: Callable[..., Any] | None = None, dry_run: bool = True) -> dict[str, Any]:
    """Deny mutation-shaped gh/git commands and never execute in dry-run mode."""
    command = [str(part) for part in command]
    if _is_mutating_command(command):
        return {"status": "denied", "command": command}
    if dry_run:
        return {"status": "dry_run", "command": command}
    if runner is None:
        raise RuntimeError("A runner must be injected; review feedback stays read-only")
    return {"status": "executed", "command": command, "result": runner(command)}
