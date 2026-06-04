#!/usr/bin/env python3
"""Shared mode prompts for the agent mode system.

Per spec (2026-06-04): Plan mirrors Claude Code (0-3 ad-hoc Qs), UltraPlan
expands to 10-15 Qs in batches plus Mermaid/HTML diagrams, Recon asks 4
upfront Qs and dispatches to specialised agent profiles sequentially.

The internal mode value ``gods_plan`` is preserved for backward
compatibility — the user-facing label is "UltraPlan".  See skill
`agent-modes` for the full spec.  Must survive upstream merges.

This module is the single source of truth.  cli.py (HermesCLI /mode
command) and tui_gateway/server.py (gateway ephemeral_system_prompt)
both import from here.  Adding or changing a mode prompt means editing
exactly one file.
"""
from __future__ import annotations

from typing import Optional


# Internal mode value → user-facing label.  Kept in one place so the
# slash command, the badge, and the status command all agree.
MODE_LABELS = {
    "auto":      "auto",
    "plan":      "plan",
    "gods_plan": "UltraPlan",   # user-facing label is UltraPlan, internal value is gods_plan
    "recon":     "recon",
}


# Sentinel sub-strings used to detect which mode the agent is currently
# in by inspecting ephemeral_system_prompt.  Each must appear exactly
# once at the start of its prompt so the substring match is unambiguous.
_MODE_PROMPT_MARKERS = {
    "plan":      "You are in plan mode",
    "gods_plan": "You are in UltraPlan mode",
    "recon":     "You are in Recon mode",
}


# ── plan ─────────────────────────────────────────────────────────────
#
# Mirrors Claude Code's plan mode: 0-3 ad-hoc questions, write a spec,
# A/B/C exit.  Question count and batching are deliberately loose — the
# model decides what's needed for the specific request.
PLAN_PROMPT = """\
You are in plan mode — design-first, no execution.

Workflow:
1. Analyse the user's request.
2. Use the `ask_user_questions` tool to ask 0-3 focused questions for
   the most ambiguous decisions. For each question, set
   `recommended: true` on exactly one option — the UI will render a
   "(Recommended)" label automatically, do NOT add it to the label
   text. You may batch multiple questions in a single
   `ask_user_questions` call (max 4 per batch). Skip this step
   entirely if the request is unambiguous.
3. Once requirements are clear, write a detailed implementation plan
   to `.hermes/plans/YYYY-MM-DD_HHMMSS-<slug>.md` and display the
   full plan in your response. Include steps, file paths, architecture
   decisions, and ordering.
4. Do NOT execute any tool calls that modify files or run code.
5. Present an A/B/C exit choice:
   A) Save Only (Recommended) — plan is saved
   B) Compress and Execute — switch to /mode auto to execute
   C) Continue in plan mode and iterate"""


# ── UltraPlan (gods_plan) ────────────────────────────────────────────
#
# 10-15 questions in batches of 3-4, plus Mermaid + HTML/SVG diagrams,
# plus UI mockups.  This is the exhaustive design-first path.
ULTRAPLAN_PROMPT = """\
You are in UltraPlan mode — exhaustive spec design with diagrams.

Workflow:
1. Analyse the user's request comprehensively.
2. Use the `ask_user_questions` tool to ask 10-15 questions across
   these dimensions, presented in batches of 3-4:
   - Scope, goals, success criteria, constraints
   - Technical approach, architecture, data flow
   - UI/UX mock-ups: which screens, design constraints
   - Edge cases, risks, validation, testing strategy
   For each question, set `recommended: true` on exactly one option —
   the UI renders a "(Recommended)" label automatically, do NOT add it
   to the label text. You may batch multiple questions in a single
   `ask_user_questions` call (max 4 per batch).
3. After all clarifications, generate architectural diagrams:
   - Mermaid code blocks inline in the spec for system architecture
   - HTML/SVG sidecar files in `.hermes/plans/diagrams/` for
     high-fidelity views (use the `architecture-diagram` skill)
4. Generate UI mock-ups (if the spec covers UI work):
   - Use the `sketch`, `claude-design`, or `mobile-screen-spec` skill
   - Save to `.hermes/plans/diagrams/`
5. Incorporate diagrams and mockups into the spec by reference.
6. Save the comprehensive spec to
   `.hermes/plans/YYYY-MM-DD_HHMMSS-<slug>.md` and display the
   full spec in your response.
7. Do NOT execute any tool calls that modify files or run code,
   EXCEPT writing the spec, diagrams, and mockup files.
8. Present the A/B/C exit choice:
   A) Save Only (Recommended) — spec is saved
   B) Compress and Execute — switch to /mode auto to execute
   C) Continue in UltraPlan mode and iterate"""


# ── recon ────────────────────────────────────────────────────────────
#
# 4 upfront Qs, then sequential dispatch to specialised profiles.
# Output goes to .hermes/recon/ (NOT .hermes/plans/ or .hermes/audits/).
RECON_PROMPT = """\
You are in Recon mode — deep analysis, audit, and research.

Workflow:
1. Use the `ask_user_questions` tool to ask exactly 4 upfront
   clarification questions. For each question, set
   `recommended: true` on exactly one option — the UI renders a
   "(Recommended)" label automatically, do NOT add it to the label
   text. Cover:
   - Target: what is being analysed (codebase, system, document, project)
   - Lens: which analysis lens (deep analysis, audit, research)
   - Scope/depth: how deep, what boundaries
   - Output format: what the audit document should include
2. Based on the lens answer, dispatch to specialised agent profiles
   sequentially via `delegate_task` (role='leaf'). Read-only tools only.
   Do NOT modify any source files except the recon output document.
   - Research  → Remii profile (research lead)
   - Audit/QA  → Quan profile (QA lead)
   - Independent review → KENSEI Review
   - Governance/process → Denji profile
3. Run analysis. Lead profile runs first; Quan's QA pass reviews the
   lead's output; KENSEI Review signs off on the final document.
4. Produce the final audit/research document with findings, evidence,
   recommendations, and risks.
5. Save to `.hermes/recon/YYYY-MM-DD_HHMMSS-<slug>.md`.
6. Do NOT modify any files except the recon output document."""


# Internal-value → prompt.  ``auto`` returns None (no overlay prompt).
_MODE_PROMPTS = {
    "plan":      PLAN_PROMPT,
    "gods_plan": ULTRAPLAN_PROMPT,
    "recon":     RECON_PROMPT,
}


def get_mode_prompt(mode: str) -> Optional[str]:
    """Return the ephemeral_system_prompt for a mode, or None for auto.

    This is the single source of truth.  Both the CLI ``/mode`` command
    and the gateway's ``config.set`` handler call this — no duplicated
    prompt text anywhere.
    """
    if mode == "auto":
        return None
    return _MODE_PROMPTS.get(mode)


def detect_mode(ephemeral_system_prompt: str) -> str:
    """Reverse-map an ephemeral_system_prompt back to its mode value.

    Returns "auto" if no known mode marker is found.  Used by
    ``/mode status`` to report the current mode without needing a
    separate state attribute that could drift.
    """
    text = ephemeral_system_prompt or ""
    for mode, marker in _MODE_PROMPT_MARKERS.items():
        if marker in text:
            return mode
    return "auto"


def mode_label(mode: str) -> str:
    """User-facing label for a mode (gods_plan → UltraPlan, etc.)."""
    return MODE_LABELS.get(mode, mode)
