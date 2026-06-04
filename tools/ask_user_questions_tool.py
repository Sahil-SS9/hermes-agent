#!/usr/bin/env python3
"""AskUserQuestionsTool — Batched multi-question clarification (Claude Code style).

Per spec (2026-06-04): the new mode system (plan / UltraPlan / recon) uses
this instead of the single-question `clarify` tool.  Supports:

  * Batch: pass a list of questions in one tool call (UltraPlan: 3-4 Qs
    per batch, Recon: 4 upfront Qs, Plan: 0-3 ad-hoc).
  * Recommended: each question can mark one option as recommended; the
    UI highlights it with a "(Recommended)" label.
  * Boxed UI: platform layer renders each question in a bordered panel,
    modelled after Claude Code's AskUserQuestion UX.
  * "Other" handoff: when a user picks the synthetic "Other" option, the
    TUI sends back the sentinel ``__other__``.  We translate that into
    a structured ``needs_followup`` signal so the model knows to call
    the legacy ``clarify`` tool (which has inline text capture) for
    those questions.

Behaviour mirrors ``clarify_tool`` but is structurally distinct — the
``clarify`` tool is preserved untouched (item 4A of the spec) for all
non-mode flows.

Must survive upstream merges — see skill `agent-modes`.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from tools.registry import registry, tool_error


# Hard caps.  These mirror Claude Code's documented limits and the
# recon/UltraPlan spec ranges:
#   - Plan mode: 0-3 ad-hoc
#   - UltraPlan: 10-15 total, in batches of 3-4
#   - Recon:     exactly 4 upfront
# Tool-level cap of 4 per batch keeps the TUI overlay readable.
MAX_QUESTIONS_PER_CALL = 4
MAX_OPTIONS_PER_QUESTION = 4

# Sentinel label the TUI sends for the synthetic "Other (free-form
# follow-up)" option.  Distinct from any real option label because real
# options are user-provided and this string is reserved.
OTHER_SENTINEL = "__other__"

# Sentinel label the TUI may send when a question is unanswered
# (e.g. user pressed Esc mid-batch, or the question timed out).
SKIPPED_SENTINEL = "__skipped__"


def _normalise_questions(raw_questions: Any) -> List[Dict[str, Any]]:
    """Validate, trim, and normalise the question list.

    Returns the cleaned list.  Raises ValueError on structural errors so
    the agent gets an actionable error message rather than silent loss.
    """
    if not isinstance(raw_questions, list) or not raw_questions:
        raise ValueError(
            "questions must be a non-empty list of question objects"
        )
    if len(raw_questions) > MAX_QUESTIONS_PER_CALL:
        raise ValueError(
            f"too many questions in a single batch: {len(raw_questions)} "
            f"(max {MAX_QUESTIONS_PER_CALL} per ask_user_questions call)"
        )

    cleaned = []
    for i, q in enumerate(raw_questions):
        if not isinstance(q, dict):
            raise ValueError(f"question[{i}] must be an object")
        text = str(q.get("question", "")).strip()
        if not text:
            raise ValueError(f"question[{i}].question is required")
        opts = q.get("options")
        if not isinstance(opts, list) or not opts:
            raise ValueError(
                f"question[{i}] needs at least one option in `options`"
            )
        if len(opts) > MAX_OPTIONS_PER_QUESTION:
            raise ValueError(
                f"question[{i}] has {len(opts)} options (max "
                f"{MAX_OPTIONS_PER_QUESTION})"
            )
        norm_opts = []
        recommended_count = 0
        for j, opt in enumerate(opts):
            if not isinstance(opt, dict):
                raise ValueError(
                    f"question[{i}].options[{j}] must be an object"
                )
            label = str(opt.get("label", "")).strip()
            if not label:
                raise ValueError(
                    f"question[{i}].options[{j}].label is required"
                )
            is_rec = bool(opt.get("recommended", False))
            if is_rec:
                recommended_count += 1
            norm_opts.append({
                "label": label,
                "description": str(opt.get("description", "")).strip() or None,
                "recommended": is_rec,
            })
        if recommended_count > 1:
            raise ValueError(
                f"question[{i}] has {recommended_count} recommended options "
                "(exactly one is allowed)"
            )
        cleaned.append({
            "question": text,
            "header": str(q.get("header", "")).strip()[:12] or None,
            "options": norm_opts,
            "multiSelect": bool(q.get("multiSelect", False)),
        })
    return cleaned


def _coerce_answer(cleaned_q: Dict[str, Any], raw: Any) -> Dict[str, Any]:
    """Translate the raw callback value for one question into a structured answer.

    Returns a dict with keys:
        ``answer``       — the chosen label, or "(skipped)" / "(awaiting text)"
        ``needs_text``   — True if user picked "Other" and model should
                           use the legacy ``clarify`` tool for free-form
        ``original``     — the raw value (for debugging)
    """
    label = str(raw or "").strip()
    if not label or label == SKIPPED_SENTINEL:
        return {"answer": "(skipped)", "needs_text": False, "original": raw}
    if label == OTHER_SENTINEL:
        return {"answer": "(awaiting text)", "needs_text": True, "original": raw}
    return {"answer": label, "needs_text": False, "original": raw}


def ask_user_questions_tool(
    questions: List[Dict[str, Any]],
    callback: Optional[Callable] = None,
) -> str:
    """Render a batch of boxed questions and return the user's answers.

    Args:
        questions: List of question objects, each with:
            - question (str, required)
            - options (list of {label, description?, recommended?}, required)
            - header (str, optional, max 12 chars)
            - multiSelect (bool, optional, default false)
        callback: Platform-provided function. Signature:
            callback(questions: list[dict]) -> dict[int, str]
            Returns a map of question_index → chosen label.
            Special values recognised:
              * empty / missing key  → "(skipped)"
              * "__other__"          → "(awaiting text)" + needs_text=True
            Injected by cli.py / gateway at runtime.

    Returns:
        JSON string with:
            questions_asked (int)
            answers (list of {index, question, answer, needs_text})
            needs_followup (list of question indices where user picked
                            "Other" and the model should re-ask via the
                            legacy `clarify` tool for free-form text)
    """
    try:
        cleaned = _normalise_questions(questions)
    except ValueError as exc:
        return tool_error(str(exc))

    if callback is None:
        return json.dumps(
            {"error": "ask_user_questions tool is not available in this execution context."},
            ensure_ascii=False,
        )

    try:
        raw_answers = callback(cleaned)
    except Exception as exc:
        return json.dumps(
            {"error": f"Failed to collect user answers: {exc}"},
            ensure_ascii=False,
        )

    if not isinstance(raw_answers, dict):
        return tool_error("callback must return a dict[int, str]")

    response_payload = []
    needs_followup: List[int] = []
    for i, q in enumerate(cleaned):
        coerced = _coerce_answer(q, raw_answers.get(i))
        if coerced["needs_text"]:
            needs_followup.append(i)
        response_payload.append({
            "index": i,
            "question": q["question"],
            "answer": coerced["answer"],
            "needs_text": coerced["needs_text"],
        })

    return json.dumps({
        "questions_asked": len(cleaned),
        "answers": response_payload,
        "needs_followup": needs_followup,  # empty list when no "Other" picks
    }, ensure_ascii=False)


def check_ask_user_questions_requirements() -> bool:
    """ask_user_questions has no external requirements -- always available."""
    return True


# =============================================================================
# OpenAI Function-Calling Schema
# =============================================================================

ASK_USER_QUESTIONS_SCHEMA = {
    "name": "ask_user_questions",
    "description": (
        "Ask the user one or more structured questions with selectable "
        "options, modelled after Claude Code's AskUserQuestion tool. Use "
        "this in plan / UltraPlan / recon modes to gather requirements "
        "before producing a spec, design, or audit. Supports BATCHED "
        "questions in a single call (up to 4 per batch). For each "
        "question, set `recommended: true` on exactly one option — the "
        "UI will highlight it with a '(Recommended)' label automatically "
        "(do NOT add '(Recommended)' to the label text). If the user "
        "selects the 'Other' option, the response includes those "
        "question indices in `needs_followup` — call the legacy "
        "`clarify` tool for those questions to collect free-form text."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_QUESTIONS_PER_CALL,
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The question to present to the user.",
                        },
                        "header": {
                            "type": "string",
                            "maxLength": 12,
                            "description": (
                                "Short label for the question (max 12 chars). "
                                "Renders as a chip at the top of the question panel."
                            ),
                        },
                        "options": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": MAX_OPTIONS_PER_QUESTION,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {
                                        "type": "string",
                                        "description": "The option text shown to the user.",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "Optional secondary line explaining the option.",
                                    },
                                    "recommended": {
                                        "type": "boolean",
                                        "default": False,
                                        "description": (
                                            "Mark this option as the recommended one. "
                                            "Exactly one option per question should be recommended."
                                        ),
                                    },
                                },
                                "required": ["label"],
                            },
                        },
                        "multiSelect": {
                            "type": "boolean",
                            "default": False,
                            "description": (
                                "Allow the user to select multiple options. "
                                "Defaults to single-select. Currently rendered "
                                "as single-select in the TUI/CLI."
                            ),
                        },
                    },
                    "required": ["question", "options"],
                },
                "description": (
                    "List of questions to ask in this batch (1-4). "
                    "Each question is rendered in its own boxed panel with "
                    "numbered, selectable options. Batching keeps the user "
                    "in one focused flow rather than re-prompting per question."
                ),
            },
        },
        "required": ["questions"],
    },
}


# --- Registry ---

registry.register(
    name="ask_user_questions",
    toolset="clarify",
    schema=ASK_USER_QUESTIONS_SCHEMA,
    handler=lambda args, **kw: ask_user_questions_tool(
        questions=args.get("questions", []),
        callback=kw.get("callback"),
    ),
    check_fn=check_ask_user_questions_requirements,
    emoji="❓",
)
