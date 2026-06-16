"""Blog generator — stream-aware long-form draft generation.

Reuses article_generator building blocks (the LLM call chain, title extraction,
signal enrichment, KB retrieval) but injects the stream voice, word_target,
and section_target into the system prompt. Output is a draft dict with the
blog frontmatter fields (tier, tags, source, format) set from the stream config.
"""
from __future__ import annotations
import re
from typing import Optional

import context_enrich
import kb_retrieve
from llm_generate import _call_llm, _llm_configs, _load_voice_skill, gate_post
from blog.blog_streams import STREAMS, tags_for


def enrich_signal(sig: dict) -> str:
    """Per-signal rich context blob via context_enrich."""
    return context_enrich.enrich(sig) or ""


def retrieve_kb(topic: str, limit: int = 3) -> list[str]:
    """Author's prior takes from kb_retrieve."""
    return kb_retrieve.retrieve(topic, limit=limit) or []


def _call_llm_first(system: str, user: str) -> Optional[str]:
    """Try the LLM chain once; return first non-empty body or None."""
    for cfg in _llm_configs():
        body = _call_llm(system, user, cfg, timeout=180, max_tokens=8000)
        if body:
            return body
    return None


def _extract_title(body: str) -> Optional[str]:
    """First `# Title` line if present, else None."""
    for line in body.splitlines():
        m = re.match(r"^#\s+(.+?)\s*$", line)
        if m:
            return m.group(1).strip()
    return None


def _slugify(title: str) -> str:
    """Kebab-case slug, ASCII-only, for blog post filenames."""
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    if not words:
        return "post"
    return "-".join(words[:6])


def _lede_to_description(body_md: str, max_len: int = 180) -> str:
    """Extract a one-line description (deck) from the first non-heading paragraph."""
    for line in body_md.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # Clean markdown emphasis for a plain-text deck.
        clean = re.sub(r"[*_`#]", "", s).strip()
        if clean:
            return clean[:max_len]
    return ""


_DEPTH_CONTRACT = (
    "## What makes this worth reading (depth and value contract)\n"
    "Write something a busy builder finishes and immediately uses. Every "
    "section must repay the reader's time with at least one of: a mechanism "
    "explained from first principles, a concrete worked example with real "
    "specifics, an honest trade-off and the reasoning behind it, a decision "
    "rule they can reuse, a pitfall and how to avoid it, or an alternative you "
    "considered and rejected and why. No padding: every paragraph must advance "
    "understanding."
)


def build_blog_prompt(stream: str, plan: dict, context_blob: str,
                      kb_snippets: list[str],
                      retry_feedback: Optional[str] = None) -> dict:
    """System + user prompt for the blog LLM call, stream-aware."""
    s = STREAMS[stream]
    voice = s["voice"]
    word_target = s["word_target"]
    section_target = s["section_target"]
    title_hint = (plan.get("title_hint") or "").strip()
    signal_lines = "\n".join(
        f"- {sig.get('summary', '')}"
        for sig in plan.get("signals", [])
    ) or "(no signals)"
    takes = "\n".join(f"- {t}" for t in (kb_snippets or [])) or "(none on file)"

    rules = [
        f"- Length: ~{word_target} words. Full article, not a long post. "
        "Do not stop short.",
        "- British English. No em-dashes.",
        "- No AI-isms. No 'Let's dive in' / 'In today's world' / 'Great question'.",
        "- No invented statistics. Cite only numbers and terms that appear in the context.",
        "- Prefer concrete specifics over abstraction every time.",
        f"- Structure: {section_target}+ `## H2` sections in prose. The illustrator "
        "keys off these headings, so every H2 must be a real section title.",
        "- One `# Title` (specific, not clickbait).",
        "- One `## What I'd try next` or `## Takeaway` section at the end.",
    ]
    if retry_feedback:
        rules.append(f"- Previous attempt rejected: {retry_feedback}")

    system = "\n".join([
        f"You are writing a long-form blog essay for SahilBlog, stream '{stream}'.",
        "",
        "## Brand voice (use exactly)", voice,
        "",
        _DEPTH_CONTRACT,
        "",
        "## Structure (mandatory)",
        f"- One `# Title` (specific, not clickbait).",
        f"- 2-3 sentence lede / hook paragraph immediately after the title.",
        f"- {section_target}+ `## H2` sections moving from problem to mechanism to "
        "worked example to trade-offs.",
        "- One `## How to apply this` section with concrete steps.",
        "- One final `## What I'd try next` section.",
        "",
        "## Rules", *rules,
    ])

    user = "\n".join([
        f"Title hint: {title_hint}" if title_hint else "",
        "## Chosen signals", signal_lines,
        "",
        "## Real context (ground the article in this; quote numbers and "
        "tool names verbatim where they help)", context_blob or "(none)",
        "",
        "## Author's prior takes (reflect this thinking, do not repeat)", takes,
        "",
        "Write the article now.",
    ])
    user = "\n".join(line for line in user.splitlines() if line is not None)

    return {"system": system, "user": user}


def write(plan: dict, stream: str = "ai",
         max_retries: int = 1) -> Optional[dict]:
    """Generate one blog draft. Returns None when the LLM chain is dead."""
    if not plan or not plan.get("signals"):
        return None
    s = STREAMS[stream]

    context_blob = "\n\n---\n\n".join(
        enrich_signal(sig) for sig in plan["signals"][:3]
    ) or ""
    kb = retrieve_kb(plan.get("title_hint", "") or plan["signals"][0].get("summary", ""))
    kb = (kb or [])[:3]

    last_body: Optional[str] = None
    for attempt in range(max_retries + 1):
        prompts = build_blog_prompt(stream, plan, context_blob, kb)
        body = _call_llm_first(prompts["system"], prompts["user"])
        if body:
            last_body = body
            break
    if not last_body:
        return None

    title = _extract_title(last_body) or plan.get("title_hint", "Post")
    description = _lede_to_description(last_body)
    if not description:
        # Fall back to the title hint if the body has no lede paragraph.
        description = (plan.get("title_hint") or title)[:180]

    # Tags: merge the stream base_tags with the plan's topic tags (the router
    # already merges them, but re-merge here so write() is safe standalone).
    topic_tags = [t for t in (plan.get("tags") or []) if t not in s["base_tags"]]
    final_tags = tags_for(stream, topic_tags)

    return {
        "title": title,
        "description": description,
        "body_md": last_body.strip(),
        "slug": _slugify(title),
        "tier": s["tier"],
        "tags": final_tags,
        "format": s["format"],
        "source": plan.get("source") or s["source"],
        "stream": stream,
        "signals": plan["signals"],
        "context": context_blob,
        "kb_snippets": kb,
    }


def gate_check(draft: dict) -> tuple[str, list[str]]:
    """Run article_gates.check on a blog draft; return (status, issues).

    status in 'ok' | 'fail'. Reuses the article gate so the same slop /
    em-dash / length / data-integrity / secret-scan rules apply.
    """
    import article_gates as ag
    res = ag.check(draft)
    return ("ok" if res.passed else "fail"), res.issues


def write_with_gate(plan: dict, stream: str = "ai",
                    max_retries: int = 1) -> Optional[dict]:
    """Generate a draft, gate it, retry once with feedback on gate failure.

    Returns the draft (with redacted body from the gate) on pass, or None.
    """
    draft = write(plan, stream=stream, max_retries=max_retries)
    if not draft:
        return None
    status, issues = gate_check(draft)
    if status == "ok":
        # Carry the redacted body so no secret leaks downstream.
        import article_gates as ag
        gate_res = ag.check(draft)
        draft["body_md"] = gate_res.redacted_body
        return draft
    # Retry once with feedback.
    plan2 = {**plan}
    s = STREAMS[stream]
    context_blob = draft.get("context", "")
    kb = draft.get("kb_snippets", [])
    feedback = "; ".join(issues) or "rejected by quality gate"
    prompts = build_blog_prompt(stream, plan2, context_blob, kb, retry_feedback=feedback)
    body = _call_llm_first(prompts["system"], prompts["user"])
    if not body:
        return None
    draft2 = write({**plan, "title_hint": _extract_title(body) or plan.get("title_hint", "")},
                   stream=stream, max_retries=0)
    if not draft2:
        return None
    status2, issues2 = gate_check(draft2)
    if status2 == "ok":
        import article_gates as ag
        gate_res = ag.check(draft2)
        draft2["body_md"] = gate_res.redacted_body
        return draft2
    return None