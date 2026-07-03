#!/usr/bin/env bash
# Wrapper to launch gbrain MCP server via bun (bypasses STDIO allowlist)
exec /home/kensei/.local/bin/bun /home/kensei/.bun/install/global/node_modules/gbrain/src/cli.ts serve
