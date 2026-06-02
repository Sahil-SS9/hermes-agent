"""GBrain knowledge tools for Hermes Agent.

GBrain is Sahil's structured Markdown knowledge layer at ``~/brain``. These
built-in tools expose the local trusted GBrain CLI to KenseiAgent alongside
Mnemosyne's conversational memory provider.

# Upstream: HermesAgent | tools/gbrain.py | Last checked: 2026-05-31 | Policy: ~/brain/conventions/infrastructure.md ## Source Code Policy
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from tools.registry import registry, tool_error, tool_result


GBRAIN_BIN = Path(os.environ.get("GBRAIN_BIN", "~/.bun/bin/gbrain")).expanduser()
GBRAIN_REPO = Path(os.environ.get("GBRAIN_REPO", "~/brain")).expanduser()
GBRAIN_TIMEOUT_SECONDS = float(os.environ.get("GBRAIN_TOOL_TIMEOUT", "45"))


def _check_gbrain_available() -> bool:
    return GBRAIN_BIN.is_file() and os.access(GBRAIN_BIN, os.X_OK) and GBRAIN_REPO.is_dir()


def _run_gbrain(args: list[str], *, timeout: float = GBRAIN_TIMEOUT_SECONDS) -> tuple[str, str, int]:
    env = os.environ.copy()
    env["PATH"] = f"{GBRAIN_BIN.parent}{os.pathsep}{env.get('PATH', '')}"
    proc = subprocess.run(
        [str(GBRAIN_BIN), *args],
        cwd=str(GBRAIN_REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.stdout, proc.stderr, proc.returncode


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


GBRAIN_SEARCH_SCHEMA = {
    "name": "gbrain_search",
    "description": (
        "Search Sahil's GBrain structured knowledge base at ~/brain. "
        "Use this for durable facts, project knowledge, people, accounts, "
        "infrastructure conventions, and timeline context."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keyword or natural-language search query."},
            "limit": {"type": "integer", "description": "Maximum result lines to return.", "default": 5},
        },
        "required": ["query"],
    },
}

GBRAIN_GET_SCHEMA = {
    "name": "gbrain_get",
    "description": "Read a specific GBrain page by slug, e.g. people/sahil-saghir.",
    "parameters": {
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "Page slug without .md."},
        },
        "required": ["slug"],
    },
}

GBRAIN_PUT_SCHEMA = {
    "name": "gbrain_put",
    "description": (
        "Create or replace a GBrain Markdown page, then sync GBrain. "
        "Use only for durable structured knowledge; content should include YAML frontmatter."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "Target page slug without .md."},
            "content": {"type": "string", "description": "Full Markdown page content including frontmatter."},
        },
        "required": ["slug", "content"],
    },
}

GBRAIN_GRAPH_SCHEMA = {
    "name": "gbrain_graph",
    "description": "Explore graph links from a GBrain page slug.",
    "parameters": {
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "Starting page slug."},
            "depth": {"type": "integer", "description": "Traversal depth, 1-5.", "default": 2},
        },
        "required": ["slug"],
    },
}

GBRAIN_STATUS_SCHEMA = {
    "name": "gbrain_status",
    "description": "Return GBrain version, doctor summary, and local repo status.",
    "parameters": {"type": "object", "properties": {}},
}


def gbrain_search(args: dict, **_: Any) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return tool_error("query is required")
    limit = _bounded_int(args.get("limit"), default=5, minimum=1, maximum=25)
    stdout, stderr, rc = _run_gbrain(["search", query])
    if rc != 0:
        return tool_error(f"gbrain search failed: {(stderr or stdout).strip() or 'unknown error'}")
    lines = [line for line in stdout.splitlines() if line.strip()]
    return tool_result({"query": query, "results": lines[:limit], "total": len(lines), "limit": limit})


def gbrain_get(args: dict, **_: Any) -> str:
    slug = str(args.get("slug", "")).strip().removesuffix(".md")
    if not slug:
        return tool_error("slug is required")
    stdout, stderr, rc = _run_gbrain(["get", slug])
    if rc != 0:
        return tool_error(f"gbrain page not found: {slug} ({(stderr or stdout).strip() or 'no match'})")
    return tool_result({"slug": slug, "content": stdout})


def gbrain_put(args: dict, **_: Any) -> str:
    slug = str(args.get("slug", "")).strip().removesuffix(".md")
    content = str(args.get("content", ""))
    if not slug:
        return tool_error("slug is required")
    if not content.strip():
        return tool_error("content is required")
    target = (GBRAIN_REPO / f"{slug}.md").resolve()
    repo_root = GBRAIN_REPO.resolve()
    if repo_root not in target.parents:
        return tool_error("slug must resolve under the GBrain repo")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    stdout, stderr, rc = _run_gbrain(["sync"])
    if rc != 0:
        return tool_result({"status": "file_written", "slug": slug, "path": str(target), "sync_error": (stderr or stdout).strip()})
    return tool_result({"status": "ok", "slug": slug, "path": str(target), "sync": stdout.strip()})


def gbrain_graph(args: dict, **_: Any) -> str:
    slug = str(args.get("slug", "")).strip().removesuffix(".md")
    if not slug:
        return tool_error("slug is required")
    depth = _bounded_int(args.get("depth"), default=2, minimum=1, maximum=5)
    stdout, stderr, rc = _run_gbrain(["graph-query", slug, "--depth", str(depth)])
    if rc != 0:
        return tool_error(f"gbrain graph query failed: {(stderr or stdout).strip() or 'no results'}")
    return tool_result({"slug": slug, "depth": depth, "output": stdout.strip()})


def gbrain_status(args: dict, **_: Any) -> str:
    version_out, version_err, version_rc = _run_gbrain(["--version"], timeout=10)
    doctor_out, doctor_err, doctor_rc = _run_gbrain(["doctor", "--json"], timeout=90)
    return tool_result(
        {
            "available": _check_gbrain_available(),
            "bin": str(GBRAIN_BIN),
            "repo": str(GBRAIN_REPO),
            "version": (version_out or version_err).strip(),
            "version_exit_code": version_rc,
            "doctor_json": doctor_out.strip()[:12000],
            "doctor_stderr": doctor_err.strip()[:4000],
            "doctor_exit_code": doctor_rc,
        }
    )


registry.register(
    name="gbrain_search",
    toolset="gbrain",
    schema=GBRAIN_SEARCH_SCHEMA,
    handler=gbrain_search,
    check_fn=_check_gbrain_available,
    requires_env=[],
    is_async=False,
    description=GBRAIN_SEARCH_SCHEMA["description"],
    emoji="🧠",
)
registry.register(
    name="gbrain_get",
    toolset="gbrain",
    schema=GBRAIN_GET_SCHEMA,
    handler=gbrain_get,
    check_fn=_check_gbrain_available,
    requires_env=[],
    is_async=False,
    description=GBRAIN_GET_SCHEMA["description"],
    emoji="📄",
)
registry.register(
    name="gbrain_put",
    toolset="gbrain",
    schema=GBRAIN_PUT_SCHEMA,
    handler=gbrain_put,
    check_fn=_check_gbrain_available,
    requires_env=[],
    is_async=False,
    description=GBRAIN_PUT_SCHEMA["description"],
    emoji="✍️",
)
registry.register(
    name="gbrain_graph",
    toolset="gbrain",
    schema=GBRAIN_GRAPH_SCHEMA,
    handler=gbrain_graph,
    check_fn=_check_gbrain_available,
    requires_env=[],
    is_async=False,
    description=GBRAIN_GRAPH_SCHEMA["description"],
    emoji="🔗",
)
registry.register(
    name="gbrain_status",
    toolset="gbrain",
    schema=GBRAIN_STATUS_SCHEMA,
    handler=gbrain_status,
    check_fn=_check_gbrain_available,
    requires_env=[],
    is_async=False,
    description=GBRAIN_STATUS_SCHEMA["description"],
    emoji="📊",
)
