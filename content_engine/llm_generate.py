"""LLM draft generator for personal brands — cheap-first via agent-cron mechanism.

Mirrors the successful pattern from the research digest and CeeCee review crons:
agent-based (no_agent: false), model+provider set, fallback_providers from
config.yaml applied by cron/scheduler.py. Each post is a small bounded generation.

Returns the identical draft dict shape as llm_drafts.generate_drafts for drop-in use.

ARCHITECTURE NOTE:
    The actual LLM call does NOT happen inside this Python module. Instead:
    - The cron prompt IS the generation step (the cron agent writes the posts)
    - build_generation_prompt() produces the system+user prompt that the cron agent follows
    - For --self-call testing from this session, the calling agent (me) generates output
    - For cron execution, the cron agent's own model produces the output

    This avoids subprocess calls, nested agent loops, and hermes -z timeouts.
"""

import json
import os
import random
import re
import sys
import uuid
from datetime import datetime
from typing import Optional

# ── Voice skill paths ──────────────────────────────────────────────────

SKILL_DIR = os.path.expanduser("~/.hermes/skills/social-media")

VOICE_SKILL_PATHS = {
    "sahil_twitter": os.path.join(SKILL_DIR, "sahil-twitter-voice", "SKILL.md"),
    "sahil_linkedin": os.path.join(SKILL_DIR, "sahil-linkedin-voice", "SKILL.md"),
}


def _load_voice_skill(brand: str) -> str:
    """Read brand voice SKILL.md verbatim for context injection."""
    path = VOICE_SKILL_PATHS.get(brand)
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            # Strip YAML frontmatter
            if content.startswith("---"):
                end = content.find("---", 3)
                if end != -1:
                    content = content[end + 3:].strip()
            return content
    return ""


def _load_exemplars(brand: str, pillar: str, platform: str, max_exemplars: int = 3) -> list[str]:
    """Load exemplar templates from llm_drafts.BRAND_TEMPLATES.

    We import here to avoid circular dependency. Uses the narrative template
    lists as few-shot exemplars (style reference, not content source).
    """
    from llm_drafts import BRAND_TEMPLATES
    pillar_templates = BRAND_TEMPLATES.get(brand, {}).get(pillar, [])
    if not pillar_templates:
        # Fall back to any pillar for this brand
        for p, ts in BRAND_TEMPLATES.get(brand, {}).items():
            pillar_templates.extend(ts)
    if not pillar_templates:
        return ["Write a short, specific, story-driven social post."]
    random.shuffle(pillar_templates)
    return pillar_templates[:max_exemplars]


def _load_live_variables(brand: str, topic: dict) -> dict:
    """Inject live signal variables using the existing mechanism."""
    from llm_drafts import _build_topic_variables, _is_future_fixture
    if not _is_future_fixture(topic):
        return {}
    return _build_topic_variables(brand, topic)


# ── Platform length norms ──────────────────────────────────────────────

PLATFORM_LENGTH = {
    "twitter": {"max": 280, "min": 180},
    "linkedin": {"max": 3000, "min": 600, "story_floor": 400},
    # First ~125 chars show before "more" on IG; the hook must land there.
    "instagram": {"max": 1500, "min": 120},
    "tiktok": {"max": 300, "min": 60},
}

# Positioning fallback for product brands that have no voice SKILL.md.
BRAND_VOICE_FALLBACK = {
    "plenishd": (
        "Plenishd: UK voice-first kitchen inventory app. 'Snap it. Say it. Stock it.' "
        "Voice of a real busy UK parent: warm, wry, practical, zero corporate polish. "
        "Talk about real kitchen chaos, food waste guilt, takeaway-money regret. "
        "Never invent statistics or user numbers."
    ),
    "coachos": (
        "CoachSense (formerly CoachOS): grassroots football coaching platform. "
        "Voice of a thoughtful grassroots coach: calm, craft-obsessed, generous with "
        "knowledge. Editorial restraint, no hype. Beta opens August 2026; never claim it is live."
    ),
    "matchdaymaestro": (
        "MatchdayMaestro: football prediction and trivia companion. Voice of the "
        "sharpest mate in the group chat: quick, confident, banter without cruelty. "
        "Predictions and bragging rights, never betting or odds talk."
    ),
    "kicktionary": (
        "Kick-tionary: football tactics education for ages 6-18. Voice of an "
        "encouraging junior coach: clear, playful, jargon explained simply. Safe for kids."
    ),
}


# ── Prompt builder ─────────────────────────────────────────────────────

def build_generation_prompt(
    brand: str,
    topic: dict,
    platform: str,
    retry_feedback: Optional[str] = None,
) -> dict:
    """Build system + user prompt for LLM generation.

    Args:
        brand: Brand key (sahil_twitter, sahil_linkedin)
        topic: Topic dict with pillar, topic text, optional activity_data
        platform: Platform name (twitter, linkedin)
        retry_feedback: If regenerating, feedback from the gate to fix

    Returns:
        {"system": str, "user": str}
    """
    pillar = topic.get("pillar", "general")
    topic_text = topic.get("topic", "")

    # Load brand voice
    voice_skill = _load_voice_skill(brand)
    if not voice_skill:
        voice_skill = BRAND_VOICE_FALLBACK.get(brand, f"Write as {brand}, direct and specific.")

    # Load exemplars for pillar
    exemplars = _load_exemplars(brand, pillar, platform)
    exemplar_text = "\n\n---\n".join(exemplars)

    # Load live variables
    variables = _load_live_variables(brand, topic)

    # Build variable hint
    var_hint = ""
    if variables:
        var_items = "; ".join(f"{k}={v}" for k, v in variables.items() if v and len(str(v)) < 80)
        if var_items:
            var_hint = f"\n\nContext variables available: {var_items}"

    # Platform-specific instructions
    plat_info = PLATFORM_LENGTH.get(platform, {})
    max_chars = plat_info.get("max", 280)
    min_chars = plat_info.get("min", 100)

    if platform == "twitter":
        length_rule = f"Write a SINGLE tweet ({min_chars}-{max_chars} characters). One focused idea. No thread markers."
    elif platform == "linkedin":
        story_floor = plat_info.get("story_floor", 300)
        length_rule = f"Write a LinkedIn post ({min_chars}-{max_chars} characters, at least {story_floor} chars for proper storytelling). Setup-Evidence-Frame structure. Hashtags at the end."
    elif platform == "instagram":
        length_rule = (f"Write an Instagram caption ({min_chars}-{max_chars} characters). "
                       "The first 125 characters must work as a standalone hook (shown before 'more'). "
                       "Short paragraphs, line breaks between them, 3-5 niche hashtags at the end.")
    elif platform == "tiktok":
        length_rule = (f"Write a TikTok caption ({min_chars}-{max_chars} characters). "
                       "Punchy hook, conversational, 2-4 hashtags. The video carries the story; "
                       "the caption sets up curiosity.")
    else:
        length_rule = f"Write a social post ({min_chars}-{max_chars} characters)."

    # Platform-specific formatting
    if platform == "twitter":
        format_rules = "\n- No thread markers (1/3, 2/3, etc.)\n- Max 2 hashtags at end\n- Line breaks for readable flow (short lines work well on X)"
    elif platform == "linkedin":
        format_rules = "\n- 3-5 hashtags at end, Title Case\n- Paragraphs with line breaks\n- No emoji chains or engagement bait"
    else:
        format_rules = ""

    # Build system prompt
    segments = [
        f"You are writing a social media post for the brand '{brand}' on {platform}.",
        "",
        "## Brand Voice (use this EXACTLY — do not smooth it out)",
        voice_skill,
        "",
        "## Style Reference (pattern-match, DO NOT copy content)",
        "Here are approved example posts in this brand's voice for this topic pillar:",
        exemplar_text,
        var_hint,
        "",
        "## Content Requirements",
        length_rule,
        "- Storytelling: specific, concrete details. Real numbers, real tools, real moments.",
        "- British English spelling (organise, colour, behaviour, centre).",
        "- No em-dashes (use commas or line breaks instead).",
        "- No AI-isms: no 'Let's dive in', 'In today's world', 'Great question'.",
        "- No boilerplate mantras or template-itis.",
        format_rules,
    ]

    if retry_feedback:
        segments.append("")
        segments.append("## THIS IS A RETRY — the previous draft was rejected for:")
        segments.append(retry_feedback)
        segments.append("Fix ALL of these issues in your new draft.")

    system_prompt = "\n".join(segments)

    # Build user prompt
    user_parts = [
        f"Write a {platform} post for brand '{brand}' on pillar '{pillar}'.",
    ]
    if topic_text:
        user_parts.append(f"Topic: {topic_text}")
    if variables:
        for k, v in variables.items():
            if v and len(str(v)) < 80:
                user_parts.append(f"{k}: {v}")

    user_prompt = "\n".join(user_parts)

    return {"system": system_prompt, "user": user_prompt}


# ── Quality gate ───────────────────────────────────────────────────────

def _check_em_dashes(body: str) -> tuple[bool, str]:
    """Check for em-dashes (—) which are banned."""
    if "—" in body:
        count = body.count("—")
        return False, f"Contains {count} em-dash(es) — replace with commas or line breaks"
    return True, ""


def _check_length(body: str, platform: str) -> tuple[bool, str]:
    """Check post length against platform limits."""
    plat_info = PLATFORM_LENGTH.get(platform, {})
    max_chars = plat_info.get("max", 280)
    min_chars = plat_info.get("min", 100)
    char_count = len(body)

    if char_count > max_chars:
        return False, f"Too long: {char_count} chars (max {max_chars})"
    if platform == "linkedin":
        story_floor = plat_info.get("story_floor", 300)
        if char_count < story_floor:
            return False, f"Too short for LinkedIn storytelling: {char_count} chars (min recommended {story_floor})"
    elif char_count < min_chars:
        return False, f"Too short: {char_count} chars (min {min_chars})"
    return True, ""


def gate_post(body_text: str, platform: str) -> dict:
    """Quality gate: slop audit + stale tech + unfilled placeholders + em-dashes + length.

    Returns the same contract as llm_drafts._audit_slop for compatibility.
    """
    from llm_drafts import _audit_slop, _reject_stale_tech, _has_unfilled_placeholders

    issues = []
    slop_score = 0

    # 1. Slop audit
    audit = _audit_slop(body_text)
    slop_score = max(slop_score, audit["slop_score"])
    issues.extend(audit["issues"])

    # 2. Stale tech check
    passed_tech, stale_match = _reject_stale_tech(body_text)
    if not passed_tech:
        issues.append(f"Stale tech reference: {stale_match}")
        slop_score += 3

    # 3. Unfilled placeholders
    if _has_unfilled_placeholders(body_text):
        issues.append("Unfilled placeholder patterns detected")
        slop_score += 4

    # 4. Em-dash check
    dash_ok, dash_msg = _check_em_dashes(body_text)
    if not dash_ok:
        issues.append(dash_msg)
        slop_score += 2

    # 5. Length check
    len_ok, len_msg = _check_length(body_text, platform)
    if not len_ok:
        issues.append(len_msg)
        slop_score += 1

    return {
        "slop_score": min(slop_score, 10),
        "issues": issues,
        "passed": slop_score < 6,
    }


# ── Model call ─────────────────────────────────────────────────────────

_SELF_CALL = False
"""Set to True when the calling agent will generate text directly.
When False (cron mode), the cron agent handles generation via its own prompt."""


def _llm_config() -> Optional[dict]:
    """Direct HTTP generation config (OpenAI-compatible chat completions).

    Configured via env so the model can be repointed without a code change:
      CONTENT_LLM_BASE_URL  e.g. https://opencode.ai/zen/v1
      CONTENT_LLM_MODEL     e.g. mimo-v2.5-free
      CONTENT_LLM_API_KEY   bearer key (optional for keyless endpoints)
    Returns None when not configured, in which case the old cron-agent
    mechanism (build_generation_prompt read by the cron agent) still applies.
    """
    base = os.getenv("CONTENT_LLM_BASE_URL", "").strip().rstrip("/")
    model = os.getenv("CONTENT_LLM_MODEL", "").strip()
    if not base or not model:
        return None
    return {"base": base, "model": model, "key": os.getenv("CONTENT_LLM_API_KEY", "").strip()}


def _call_llm(system: str, user: str, cfg: dict, timeout: int = 90) -> Optional[str]:
    """One chat-completions call. Returns the text or None on any failure."""
    try:
        import requests
    except ImportError:
        return None
    headers = {"Content-Type": "application/json"}
    if cfg.get("key"):
        headers["Authorization"] = f"Bearer {cfg['key']}"
    try:
        r = requests.post(
            f"{cfg['base']}/chat/completions",
            json={
                "model": cfg["model"],
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.8,
                "max_tokens": 1200,
            },
            headers=headers, timeout=timeout,
        )
        if r.status_code != 200:
            print(f"[llm_generate] LLM HTTP {r.status_code}: {r.text[:160]}", file=sys.stderr)
            return None
        text = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
        return text.strip() or None
    except Exception as exc:  # noqa: BLE001 (generation must degrade, not crash the cron)
        print(f"[llm_generate] LLM call failed: {exc}", file=sys.stderr)
        return None


def generate_one(
    brand: str,
    topic: dict,
    platform: str,
    max_retries: int = 2,
) -> Optional[dict]:
    """Generate one draft: build prompt → call model → gate; retry on fail.

    With CONTENT_LLM_BASE_URL/MODEL set, generation happens here directly via
    an OpenAI-compatible endpoint, gated by gate_post with one retry carrying
    the gate's feedback. Without that config, behaviour is unchanged: cron
    mode returns None and the cron agent generates from
    build_generation_prompt().

    Returns a draft dict (same shape as llm_drafts.generate_drafts items)
    or None.
    """
    cfg = _llm_config()
    if cfg:
        feedback = None
        for _ in range(max_retries + 1):
            prompts = build_generation_prompt(brand, topic, platform, retry_feedback=feedback)
            body = _call_llm(prompts["system"], prompts["user"], cfg)
            if not body:
                return None
            draft = generate_with_text(brand, topic, platform, body)
            if draft:
                return draft
            gate = gate_post(body, platform)
            feedback = "; ".join(gate.get("issues", [])) or "rejected by quality gate"
        print(f"[llm_generate] {brand}/{platform}: all retries failed the gate", file=sys.stderr)
        return None

    if not _SELF_CALL:
        # Cron mode — return None; the cron agent generates text from the prompt
        return None

    # Self-call mode — the caller provides body_text via generate_one(body_text=...)
    raise ValueError(
        "Self-call not supported via this path. "
        "Use generate_with_text(brand, topic, platform, body_text) instead."
    )


def generate_with_text(
    brand: str,
    topic: dict,
    platform: str,
    body_text: str,
) -> Optional[dict]:
    """Validate and wrap externally-generated text into a draft dict.

    Used by --self-call: the calling agent generates text, then passes it here
    for gating and wrapping into the standard draft shape.
    """
    pillar = topic.get("pillar", "general")
    topic_text = topic.get("topic", "")

    # Gate check
    gate_result = gate_post(body_text, platform)
    if not gate_result["passed"]:
        return None

    # Determine content type
    from llm_drafts import _choose_content_type
    content_type = _choose_content_type(brand, pillar, platform)

    visual_descs = {
        "sahil_twitter": "Dark terminal aesthetic. Code overlay, monospace font, build-in-public style.",
        "sahil_linkedin": "Professional graphic with clean typography. Quote-style layout, grey tones with red accent.",
    }

    draft_id = f"{brand[:4]}_{str(uuid.uuid4())[:8]}"

    return {
        "id": draft_id,
        "brand": brand,
        "platform": platform,
        "pillar": pillar,
        "topic": topic_text,
        "title": topic_text,
        "body_text": body_text,
        "content_type": content_type,
        "visual_description": visual_descs.get(brand, ""),
        "slop_audit": gate_result,
    }


# ── Batch generation ───────────────────────────────────────────────────

def generate_drafts_llm(
    brand: str,
    topics: list,
    platform: Optional[str] = None,
    self_call_body_texts: Optional[list[str]] = None,
) -> list[dict]:
    """Batch generate LLM drafts for personal brands.

    Drop-in replacement for llm_drafts.generate_drafts.
    Mirrors the same calling convention and return shape.

    In cron mode: returns [] because the cron agent generates text from
    build_generation_prompt() output. Each topic's prompt is available
    via build_generation_prompt(brand, topic, platform).

    In self-call mode: self_call_body_texts provides the LLM-generated text.
    Each entry is gated via generate_with_text() before being accepted.
    """
    from config import BRANDS

    # Derive platform from brand config when not specified
    if platform:
        platforms = [platform]
    else:
        brand_config = BRANDS.get(brand, {})
        brand_platforms = brand_config.get("platforms", [])
        platforms = [brand_platforms[0]] if brand_platforms else ["twitter"]

    drafts = []
    text_idx = 0

    for topic in topics:
        for plat in platforms:
            if self_call_body_texts and text_idx < len(self_call_body_texts):
                body_text = self_call_body_texts[text_idx]
                text_idx += 1
                draft = generate_with_text(brand, topic, plat, body_text)
            else:
                draft = generate_one(brand, topic, plat)

            if draft:
                draft["brand"] = brand
                draft["pillar"] = topic.get("pillar", "")
                draft["topic"] = topic.get("topic", "")
                drafts.append(draft)
            else:
                # Fall back to static template if LLM path fails
                from llm_drafts import generate_drafts as fallback_gen
                fallbacks = fallback_gen(brand, [topic], platform=plat)
                if fallbacks:
                    fb = fallbacks[0]
                    fb["id"] = f"{brand[:4]}_{str(uuid.uuid4())[:8]}"
                    fb["brand"] = brand
                    drafts.append(fb)

    return drafts
