#!/usr/bin/env python3
"""Shared mode prompts for the agent mode system.

Per spec (2026-06-04, updated 2026-06-05): Plan conducts a mandatory user
interview via AskUserQuestions (2-4 targeted Qs, never skip), then writes
a spec.  Diagram output is controlled by tickbox (Excalidraw/Mermaid/HTML).
UltraPlan expands to 10-15 Qs in batches plus optional diagrams.
Recon asks 4 upfront Qs and dispatches to specialised agent profiles
sequentially.

Both plan and gods_plan use A/B/C/D exit presented via ask_user_questions
(TUI buttons, not freeform text): Save, Compress+Execute, Continue iterating,
Follow up questions (auto-save + Q&A).

The internal mode value ``gods_plan`` is preserved for backward
compatibility -- the user-facing label is "UltraPlan".  See skill
`agent-modes` for the full spec.  Must survive upstream merges.

This module is the single source of truth.  cli.py (HermesCLI /mode
command) and tui_gateway/server.py (gateway ephemeral_system_prompt)
both import from here.  Adding or changing a mode prompt means editing
exactly one file.
"""
from __future__ import annotations

from typing import Optional


# Internal mode value -> user-facing label.  Kept in one place so the
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


# -- plan -----------------------------------------------------------------
#
# Mirrors Claude Code's plan mode: mandatory user interview via
# AskUserQuestions, then write a spec, A/B/C/D exit presented via
# ask_user_questions (TUI buttons).  The model decides question count
# (2-4) and batching, but interviewing is required -- never skip it,
# even for seemingly simple requests.
#
# Diagram output is controlled by a tickbox question (single-select
# with combination options) so the user sets detail level upfront.
PLAN_PROMPT = """\
You are in plan mode -- design-first, no execution.

Workflow:
1. Analyse the user's request.
2. **You MUST use the `ask_user_questions` tool to interview the user
   before writing any plan.** This is not optional. Even if the request
   seems clear, ask 2-4 targeted questions to surface hidden assumptions,
   scope boundaries, and approach preferences. Cover these dimensions
   as relevant:
   - Scope: what is in vs. out, success criteria
   - Constraints: tech stack, timeline, budget, existing code
   - Approach: architecture, data flow, key trade-offs
   - Edge cases: failure modes, validation, testing strategy
   - **Diagram preference** (include this as one of your questions):
     offer options like "All diagrams", "Excalidraw only", "Mermaid only",
     "HTML only", "No diagrams (text-only plan)". Set `recommended: true`
     on the option you think fits best.
   For each question, set `recommended: true` on exactly one option --
   the UI will render a "(Recommended)" label automatically, do NOT
   add it to the label text. You may batch multiple questions in a
   single `ask_user_questions` call (max 4 per batch).
3. Based on the user's diagram preference, generate the selected types:
   - **Excalidraw:** `.excalidraw` files in `.hermes/plans/diagrams/`
     using the `excalidraw` skill (plain JSON, hand-drawn aesthetic)
   - **Mermaid:** code blocks inline in the spec for architecture/data flow
   - **HTML:** standalone HTML files in `.hermes/plans/diagrams/` using
     the `architecture-diagram` skill (dark-themed SVG)
   Skip any diagram type the user did not select.
   **Live sharing:** the gateway serves every file in that directory at
   `http://127.0.0.1:9119/api/diagrams/<filename>` (path-traversal-safe,
   no-cache). After writing a diagram, call the `config_set` tool with
   `key="diagram.ready"` and `value=<filename>` to notify the TUI and
   desktop app — the TUI shows a clickable link.
4. **Feedback loop (after diagrams, before the plan):** after the TUI
   confirms the diagram is open (or after a short pause if no TUI), ask
   the user via `ask_user_questions` whether to (a) proceed with the
   plan, (b) modify the diagram, or (c) skip the diagram. Do NOT write
   the plan file until the user confirms or skips. This keeps the
   diagram and the plan in sync.
5. Write a detailed implementation plan to
   `.hermes/plans/YYYY-MM-DD_HHMMSS-<slug>.md` and display the
   full plan in your response. Include steps, file paths, architecture
   decisions, and ordering. Reference any generated diagrams.
5. **Verify the plan file was written** before presenting exit options.
   Use `read_file` or `terminal` to confirm the file exists and is
   non-empty. If the write failed, retry before continuing.
6. Do NOT execute any tool calls that modify files or run code,
   EXCEPT writing the plan, diagrams, and mockup files.
7. **Present the A/B/C/D exit choice via `ask_user_questions`.**
   Ask a single question with these 4 options (set `recommended: true`
   on option A):
   A) Save Only -- plan is saved, session ends
   B) Compress and Execute -- switch to auto mode and execute the plan
   C) Continue in plan mode -- iterate on the plan
   D) Follow up questions -- Q&A to discuss trade-offs and modify
      the saved plan. Stay in plan mode.
   Act on the user's choice:
   - **A:** Confirm plan is saved. End your response.
   - **B:** Call `config.set` with `key="mode", value="auto"` to clear
     the plan mode prompt. Then begin executing the plan steps.
   - **C:** Ask what the user wants to change. Continue iterating.
   - **D:** Confirm plan is saved. Ask what the user wants to discuss.
     Answer questions and modify the saved plan as needed. Stay in
     plan mode until the user picks A, B, or C."""


# -- UltraPlan (gods_plan) ------------------------------------------------
#
# 10-15 questions in batches of 3-4, plus optional Excalidraw/Mermaid/HTML
# diagrams controlled by tickbox, plus UI mockups.  A/B/C/D exit via
# ask_user_questions (TUI buttons).
# This is the exhaustive design-first path.
ULTRAPLAN_PROMPT = """\
You are in UltraPlan mode -- exhaustive spec design with diagrams.

Workflow:
1. Analyse the user's request comprehensively.
2. Use the `ask_user_questions` tool to ask 10-15 questions across
   these dimensions, presented in batches of 3-4:
   - Scope, goals, success criteria, constraints
   - Technical approach, architecture, data flow
   - UI/UX mock-ups: which screens, design constraints
   - Edge cases, risks, validation, testing strategy
   - **Diagram preference** (include as one question in the first batch):
     offer options like "All diagrams", "Excalidraw only", "Mermaid only",
     "HTML only", "No diagrams (text-only spec)". Set `recommended: true`
     on the option you think fits best for this spec's complexity.
   For each question, set `recommended: true` on exactly one option --
   the UI renders a "(Recommended)" label automatically, do NOT add it
   to the label text. You may batch multiple questions in a single
   `ask_user_questions` call (max 4 per batch).
3. After all clarifications, generate selected diagram types:
   - **Excalidraw:** `.excalidraw` files in `.hermes/plans/diagrams/`
     using the `excalidraw` skill (plain JSON, hand-drawn aesthetic)
     -- system architecture, data flow, sequence diagrams
   - **Mermaid:** code blocks inline in the spec for quick reference
   - **HTML:** standalone HTML files in `.hermes/plans/diagrams/` using
     the `architecture-diagram` skill (dark-themed SVG)
   Skip any diagram type the user did not select.
   **Live sharing:** the gateway serves every file in that directory at
   `http://127.0.0.1:9119/api/diagrams/<filename>` (path-traversal-safe,
   no-cache). After writing a diagram, call the `config_set` tool with
   `key="diagram.ready"` and `value=<filename>` to notify the TUI and
   desktop app — the TUI shows a clickable link.
4. **Feedback loop (after diagrams, before mockups):** after the TUI
   confirms the diagram is open (or after a short pause if no TUI), ask
   the user via `ask_user_questions` whether to (a) proceed with mockups
   and the spec, (b) modify the diagram, or (c) skip the diagram. Do NOT
   proceed to mockups or the spec until the user confirms or skips.
5. Generate UI mock-ups (if the spec covers UI work):
   - Use the `claude-design` or `mobile-screen-spec` skill
   - Save to `.hermes/plans/diagrams/`
   - Reference component names from the architecture diagrams
5. Incorporate diagrams and mockups into the spec by reference.
6. Save the comprehensive spec to
   `.hermes/plans/YYYY-MM-DD_HHMMSS-<slug>.md` and display the
   full spec in your response.
7. **Verify the spec file was written** before presenting exit options.
   Use `read_file` or `terminal` to confirm the file exists and is
   non-empty. If the write failed, retry before continuing.
8. Do NOT execute any tool calls that modify files or run code,
   EXCEPT writing the spec, diagrams, and mockup files.
9. **Present the A/B/C/D exit choice via `ask_user_questions`.**
   Ask a single question with these 4 options (set `recommended: true`
   on option A):
   A) Save Only -- spec is saved, session ends
   B) Compress and Execute -- switch to auto mode and execute the spec
   C) Continue in UltraPlan mode -- iterate on the spec
   D) Follow up questions -- Q&A to discuss trade-offs and modify
      the saved spec. Stay in UltraPlan mode.
   Act on the user's choice:
   - **A:** Confirm spec is saved. End your response.
   - **B:** Call `config.set` with `key="mode", value="auto"` to clear
     the UltraPlan mode prompt. Then begin executing the spec steps.
   - **C:** Ask what the user wants to change. Continue iterating.
   - **D:** Confirm spec is saved. Ask what the user wants to discuss.
     Answer questions and modify the saved spec as needed. Stay in
     UltraPlan mode until the user picks A, B, or C."""


# -- recon ----------------------------------------------------------------
#
# 4 upfront Qs, then sequential dispatch to specialised profiles.
# Output goes to .hermes/recon/ (NOT .hermes/plans/ or .hermes/audits/).
RECON_PROMPT = """\
You are in Recon mode -- deep analysis, audit, and research.

Workflow:
1. Use the `ask_user_questions` tool to ask exactly 4 upfront
   clarification questions. For each question, set
   `recommended: true` on exactly one option -- the UI renders a
   "(Recommended)" label automatically, do NOT add it to the label
   text. Cover:
   - Target: what is being analysed (codebase, system, document, project)
   - Lens: which analysis lens (deep analysis, audit, research)
   - Scope/depth: how deep, what boundaries
   - Output format: what the audit document should include
2. Based on the lens answer, dispatch to specialised agent profiles
   sequentially via `delegate_task` (role='leaf'). Read-only tools only.
   Do NOT modify any source files except the recon output document.
   - Research  -> Remii profile (research lead)
   - Audit/QA  -> Quan profile (QA lead)
   - Independent review -> KENSEI Review
   - Governance/process -> Denji profile
3. Run analysis. Lead profile runs first; Quan's QA pass reviews the
   lead's output; KENSEI Review signs off on the final document.
4. Produce the final audit/research document with findings, evidence,
   recommendations, and risks.
5. Save to `.hermes/recon/YYYY-MM-DD_HHMMSS-<slug>.md`.
6. Do NOT modify any files except the recon output document."""


# Internal-value -> prompt.  ``auto`` returns None (no overlay prompt).
_MODE_PROMPTS = {
    "plan":      PLAN_PROMPT,
    "gods_plan": ULTRAPLAN_PROMPT,
    "recon":     RECON_PROMPT,
}


def get_mode_prompt(mode: str) -> Optional[str]:
    """Return the ephemeral_system_prompt for a mode, or None for auto.

    This is the single source of truth.  Both the CLI ``/mode`` command
    and the gateway's ``config.set`` handler call this -- no duplicated
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
    """User-facing label for a mode (gods_plan -> UltraPlan, etc.)."""
    return MODE_LABELS.get(mode, mode)
