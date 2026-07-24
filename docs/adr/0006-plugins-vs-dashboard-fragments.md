# ADR 0006 — Plugins vs dashboard fragments: where each "kensei-*" lives

**Date:** 2026-07-24
**Status:** Proposed
**Deciders:** Kensei (recommendation), Sahil (final)

## Context

The repo-reorg audit (2026-07-23 handoff, Step 1) found 10 plugin-shaped
directories that do not actually follow the spec's plugin contract
(`plugin.yaml` + `__init__.py` with `register(ctx)`):

| Path | Contents | Real nature |
|---|---|---|
| `plugins/kanban/` | `dashboard/dist/`, `dashboard/plugin_api.py`, `dashboard/manifest.json`, `systemd/hermes-kanban-dispatcher.service` | Kanban UI + dispatcher backend |
| `plugins/hermes-achievements/` | `dashboard/`, `docs/`, `tests/`, `LICENSE`, `README.md` | Achievements system + tests |
| `plugins/kensei-brand/` | `dashboard/dist/`, `dashboard/manifest.json` | Dashboard brand skin |
| `plugins/kensei-console/` | `dashboard/dist/`, `dashboard/manifest.json` | Dashboard console view |
| `plugins/kensei-overview/` | `dashboard/dist/`, `dashboard/manifest.json` | Dashboard overview view |
| `plugins/kensei-postiz/` | `dashboard/dist/`, `dashboard/manifest.json` | Postiz widget |
| `plugins/kensei-pulse/` | `dashboard/dist/`, `dashboard/manifest.json` | Pulse widget |
| `plugins/kensei-settings/` | `dashboard/dist/`, `dashboard/manifest.json` | Settings view |
| `plugins/kensei-theme-assets/` | `dashboard/dist/`, `dashboard/manifest.json` | Theme assets |
| `plugins/kensei-triage/` | `dashboard/dist/`, `dashboard/manifest.json` | Triage widget |

None of them have a `plugin.yaml` or a top-level `__init__.py` with a
`register(ctx)`. They are **dashboard fragments** — TypeScript/JS bundles
served by the Hermes dashboard backend, registered through
`dashboard/manifest.json`, with a Python `plugin_api.py` exposing API
endpoints to the React UI.

The spec's target structure is:

```
dashboard/{src/, package.json}
```

…and the spec's hard rule #1 is **"Plugins never modify core Hermes files.
If a capability is missing, flag it as needing a new hook/ctx method —
do not hardcode around it."** Forcing these fragments to fit the plugin
shape would mean either fabricating a `register(ctx)` that only registers
dashboard assets, or stuffing `dashboard/manifest.json` into a plugin
that does no actual plugin work.

## Recommendation

Move all 10 directories to `dashboard/src/<name>/`. Treat them as
dashboard sub-applications, not plugins. The `manifest.json` becomes the
registration mechanism (it already is one). The Python `plugin_api.py`
stays where it is — the dashboard backend has a known place for
per-fragment API hooks.

After the move, the spec's `dashboard/{src/, package.json}` is the
authoritative home for all dashboard work. The `plugins/` tree contains
only true plugin-shaped code: memory providers, image-gen backends, web
providers, browser providers, model providers, observability, platforms,
cron providers, security-guidance, disk-cleanup, prompt-optimizer, spotify,
google_meet, teams_pipeline, tts.

**Proposed commit:** commit 8 of the repo-reorg plan ("Move dashboard
fragments to `dashboard/src/`"). This ADR is filed first so the
reclassification is captured as a structural decision, not a one-off
move.

## Alternative considered

**Keep them as plugins and add a `plugin.yaml` that does nothing.** Rejected.
That violates "Plugins never modify core Hermes files" by making plugins
that exist only to ship dashboard assets — the plugin shape is wrong for
this content.

## Decision

Pending. Kensei will hold the dashboard move until Sahil confirms.
