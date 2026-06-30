"""Blog illustrator — hero + per-section images via creative-skill rotation + Codex CLI.

Generates images using the universal illustration style skills (Mythic Tech Codex,
Cosmic Postcard Atelier, Saga Noir Studio, Ink & Ember Studio, The Ninth Observatory,
Chromatic Institute) rotating based on content heuristics.

Generation backend: Codex CLI (ChatGPT subscription OAuth, £0 cost).
No FAL, no Pollinations, no Baoyu content-engine pipeline.

Each creative skill provides a full prompt template in its SKILL.md. This module
extracts the template, fills in the {CONCEPT} variable from the blog post content,
and generates via Codex CLI.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

import config
from blog.blog_slug import slugify
from blog.blog_streams import STREAMS


# ── Skill definitions ──

# Active illustration candidates. The rotation supports two mode families:
# - direct_prompt: load ## Prompt Template directly from SKILL.md
# - codex_adapter: convert a workflow skill (Baoyu / Pixel Art) into a
#   text-to-image prompt for Codex CLI. This deliberately avoids those skills'
#   image_generate/FAL/Pollinations execution paths for SahilBlog.

CREATIVE_SKILLS_DIR = Path.home() / ".hermes" / "skills" / "creative"
ROTATION_STATE_PATH = Path(__file__).parent.parent / "blog_topics" / "skill_rotation.json"
ROTATION_HISTORY_LIMIT = 6
ROTATION_PENALTIES = [-5.0, -3.0, -1.0]

SKILL_STYLES = [
    {
        "name": "mythic-tech-codex-illustration",
        "label": "Mythic Tech Codex",
        "mode": "direct_prompt",
        "description": "editorial, scholarly, timeless — Edwardian/Victorian scientific illustration",
        "streams": ["ai", "builder"],
        "cue_patterns": [r"\bframework\b", r"\btheory\b", r"\bconcept\b", r"\banalysis\b",
                         r"\btoken\b", r"\befficiency\b", r"\bmodel\b", r"\barchitecture\b",
                         r"\beval\b", r"\bevaluation\b", r"\bbenchmark\b"],
    },
    {
        "name": "cosmic-postcard-atelier",
        "label": "Cosmic Postcard Atelier",
        "mode": "direct_prompt",
        "description": "optimistic, retro-futurist, cinematic — mid-century Space Age",
        "streams": ["pm", "ai"],
        "cue_patterns": [r"\bjourney\b", r"\bfuture\b", r"\bvision\b", r"\bhorizon\b",
                         r"\bscale\b", r"\bgrowth\b", r"\bopportunity\b", r"\bdiscovery\b"],
    },
    {
        "name": "saga-noir-studio",
        "label": "Saga Noir Studio",
        "mode": "direct_prompt",
        "description": "mythic, graphic, powerful — Nordic mythology graphic novel",
        "streams": ["pm", "builder"],
        "cue_patterns": [r"\bcompetitive?\b", r"\btransform\b", r"\bhigh.?stakes\b",
                         r"\bbattle\b", r"\bdecisive?\b", r"\bpower\b", r"\bepic\b",
                         r"\bcrucial\b", r"\bwar\b", r"\bconflict\b"],
    },
    {
        "name": "ink-ember-studio",
        "label": "Ink & Ember Studio",
        "mode": "direct_prompt",
        "description": "emotional, painterly, human-centred — contemporary fine art",
        "streams": ["pm", "builder"],
        "cue_patterns": [r"\bleadership\b", r"\bculture\b", r"\bpeople\b", r"\bhuman\b",
                         r"\bteam\b", r"\btrust\b", r"\bemotion\b", r"\bconnection\b",
                         r"\bstory\b", r"\bexperience\b"],
    },
    {
        "name": "ninth-observatory",
        "label": "The Ninth Observatory",
        "mode": "direct_prompt",
        "description": "architectural, spatial, systems-as-places",
        "streams": ["builder", "ai"],
        "cue_patterns": [r"\barchitecture\b", r"\binfra\b", r"\bsystem\b", r"\bstack\b",
                         r"\bMCP\b", r"\bagent\b", r"\bnetwork\b", r"\bAPI\b",
                         r"\bmemory\b", r"\brouting\b", r"\bpipeline\b"],
    },
    {
        "name": "chromatic-institute",
        "label": "Chromatic Institute",
        "mode": "direct_prompt",
        "description": "colourful, networked, research abstraction",
        "streams": ["ai", "pm"],
        "cue_patterns": [r"\bresearch\b", r"\bpaper\b", r"\bmodel\b", r"\bnetwork\b",
                         r"\bneural\b", r"\bgpu\b", r"\bfine.?tune\b", r"\btraining\b",
                         r"\bAI\b", r"\bLLM\b", r"\btransformer\b"],
    },
    {
        "name": "dark-cyberpunk-hud",
        "label": "Dark Cyberpunk HUD",
        "mode": "direct_prompt",
        "description": "technical, nocturnal, diagnostic — neon-on-dark HUD systems interface",
        "streams": ["ai", "builder"],
        "cue_patterns": [r"\bdebug\b", r"\bterminal\b", r"\bCLI\b", r"\bAPI\b", r"\brouting\b",
                         r"\binference\b", r"\bmemory\b", r"\bagent\b", r"\bobservability\b",
                         r"\bsecurity\b", r"\brisk\b", r"\bdiagnostic\b"],
    },
    {
        "name": "baoyu-article-illustrator",
        "label": "Baoyu Article Illustrator",
        "mode": "codex_adapter",
        "description": "article illustration — type × style × palette visual essay image",
        "streams": ["pm", "ai", "builder"],
        "cue_patterns": [r"\bessay\b", r"\barticle\b", r"\bexplainer\b", r"\bguide\b", r"\bsummary\b"],
    },
    {
        "name": "baoyu-infographic",
        "label": "Baoyu Infographic",
        "mode": "codex_adapter",
        "description": "infographic — structured visual summary, bento grids, dashboards, dense modules",
        "streams": ["ai", "pm"],
        "cue_patterns": [r"\bmetrics?\b", r"\bcompare\b", r"\bmatrix\b", r"\bdashboard\b",
                         r"\bfunnel\b", r"\btimeline\b", r"\bprocess\b", r"\bdata\b",
                         r"\bnumbers?\b", r"\bcost\b", r"\bbenchmark\b"],
    },
    {
        "name": "baoyu-comic",
        "label": "Baoyu Comic",
        "mode": "codex_adapter",
        "description": "single-card knowledge comic — educational panel composition adapted for blog heroes",
        "streams": ["pm", "builder"],
        "cue_patterns": [r"\btutorial\b", r"\bexplain\b", r"\blesson\b", r"\bstep\b",
                         r"\bmistake\b", r"\bbefore\b", r"\bafter\b", r"\bstory\b"],
    },
    {
        "name": "pixel-art",
        "label": "Pixel Art",
        "mode": "codex_adapter",
        "description": "retro pixel-art prompt mode — arcade, SNES, PICO-8, terminal nostalgia",
        "streams": ["builder", "ai"],
        "cue_patterns": [r"\bretro\b", r"\barcade\b", r"\bpixel\b", r"\bCLI\b", r"\bterminal\b",
                         r"\btool\b", r"\bgame\b", r"\bsmall\b", r"\bindie\b"],
    },
]


def _workflow_prompt_template(skill_name: str) -> Optional[str]:
    """Return a Codex-compatible prompt template for workflow-style skills.

    This keeps Baoyu/Pixel candidates in the blog rotation without invoking
    their original image_generate/FAL/Pollinations workflows.
    """
    templates = {
        "baoyu-article-illustrator": """
Create a premium blog hero illustration adapted from Baoyu Article Illustrator.

Concept:
{CONCEPT}

Use an article-illustration approach: one clear editorial metaphor, strong visual hierarchy, high-end magazine composition, disciplined palette, rich detail, and no literal UI screenshot. Combine a clear subject, supporting symbolic objects, and a background that reinforces the thesis.

Style rules: polished editorial illustration, tasteful modern composition, textured but clean, visually distinctive, not generic AI art. 16:9 landscape. No text, no captions, no watermarks, no logos.
""".strip(),
        "baoyu-infographic": """
Create a premium blog hero image adapted from Baoyu Infographic.

Concept:
{CONCEPT}

Use a single-image infographic composition suitable for a blog hero: bento-grid or dashboard layout, 4-6 visual modules, abstract labels represented as illegible glyphs or simple marks, visual hierarchy, comparison blocks, data paths, and symbolic metrics. Preserve the factual structure of the concept without rendering readable text.

Style rules: high-density but controlled, modern information design, strong composition at thumbnail size, 16:9 landscape. No readable text, no captions, no watermarks, no logos.
""".strip(),
        "baoyu-comic": """
Create a single-card knowledge-comic blog hero adapted from Baoyu Comic.

Concept:
{CONCEPT}

Use a contained comic-panel composition: 2-4 panels inside one 16:9 hero image, clear educational visual progression, expressive but professional characters or symbolic agents, visual cause-and-effect, and a strong final takeaway represented visually. This is NOT a multi-page comic. It is one hero image with comic-strip energy.

Style rules: clean panel rhythm, bold silhouettes, minimal speech bubbles with no readable text, editorial quality, no childish clutter. 16:9 landscape. No readable text, no captions, no watermarks, no logos.
""".strip(),
        "pixel-art": """
Create a premium retro pixel-art blog hero.

Concept:
{CONCEPT}

Use pixel-art aesthetics directly in the generated image: visible square pixel blocks, disciplined limited palette, arcade/SNES/PICO-8 energy, strong silhouette, crisp composition, and modern editorial polish. The image should feel intentionally designed, not like a low-resolution accident.

Style rules: retro technical atmosphere, high-contrast focal point, optional CRT glow or scanline ambience, 16:9 landscape. No readable text, no captions, no watermarks, no logos.
""".strip(),
    }
    return templates.get(skill_name)


def _load_rotation_state() -> list[str]:
    try:
        data = json.loads(ROTATION_STATE_PATH.read_text())
    except Exception:
        return []
    if isinstance(data, dict):
        history = data.get("history", [])
    else:
        history = data
    if not isinstance(history, list):
        return []
    valid = {s["name"] for s in SKILL_STYLES}
    return [x for x in history if isinstance(x, str) and x in valid][-ROTATION_HISTORY_LIMIT:]


def _save_rotation_state(history: list[str]) -> None:
    ROTATION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"history": history[-ROTATION_HISTORY_LIMIT:], "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    ROTATION_STATE_PATH.write_text(json.dumps(payload, indent=2) + "\n")

# ── Skill prompt loader ─────────────────────────────────────────

def _load_prompt_template(skill_name: str) -> Optional[str]:
    """Extract or adapt a prompt template for a creative skill.

    Direct creative styles expose a fenced code block under '## Prompt Template'.
    Workflow-style skills (Baoyu / Pixel Art) do not, so they are converted to
    Codex-compatible templates via _workflow_prompt_template().
    """
    adapted = _workflow_prompt_template(skill_name)
    if adapted:
        return adapted

    skill_md = CREATIVE_SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_md.exists():
        print(f"[blog_illustrator] skill not found: {skill_name}")
        return None
    text = skill_md.read_text(encoding="utf-8", errors="replace")

    # Find '## Prompt Template' heading, then the next code block
    m = re.search(
        r"## Prompt Template\s*\n(?:```\w*\n(.*?)```)",
        text, re.DOTALL,
    )
    if m:
        return m.group(1).strip()
    # Fallback: find any code block after a heading containing "Prompt"
    m = re.search(
        r"##\s+.*Prompt.*\n(?:```\w*\n(.*?)```)",
        text, re.DOTALL,
    )
    if m:
        return m.group(1).strip()
    print(f"[blog_illustrator] no prompt template found in {skill_name}")
    return None


# ── Skill selection ─────────────────────────────────────────────

def _score_style(style: dict, title: str, stream: str) -> float:
    """Score a style's relevance to the given content.

    Factors: stream match, keyword cue match, recency penalty.
    """
    title_lower = title.lower()
    score = 0.0

    # Stream match: primary (+3), secondary (+1), none (-1)
    if stream in style["streams"]:
        score += 3.0
    else:
        score -= 1.0

    # Cue matches: +1 per hit
    for pattern in style["cue_patterns"]:
        if re.search(pattern, title_lower):
            score += 1.0

    # Default fallback: if no cues matched and stream is primary, base of 2.0
    return score


def _select_skill(title: str, stream: str) -> str:
    """Select and persist the best creative skill for this post.

    Uses stream + keyword cues, then applies a weighted penalty across the
    persisted last-N history so rotation survives cron process restarts.
    """
    history = _load_rotation_state()
    scored = []
    for style in SKILL_STYLES:
        score = _score_style(style, title, stream)

        # Weighted recency penalty across the last few selections.
        recent = list(reversed(history))
        for idx, used in enumerate(recent[:len(ROTATION_PENALTIES)]):
            if style["name"] == used:
                score += ROTATION_PENALTIES[idx]

        scored.append((score, style["name"], style["label"]))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    best_name = scored[0][1]
    best_label = scored[0][2]
    best_score = scored[0][0]

    print(f"[blog_illustrator] skill scores for '{title}' "
          f"(stream={stream}): {', '.join(f'{s}:{n}={lbl}' for s,n,lbl in scored)}")
    print(f"[blog_illustrator] selected: {best_label} (score={best_score})")

    history.append(best_name)
    _save_rotation_state(history[-ROTATION_HISTORY_LIMIT:])
    return best_name


# ── Concept builder ─────────────────────────────────────────────

def _build_concept(title: str, description: str, skill_name: str) -> str:
    """Build the {CONCEPT} variable from the blog post's title and description.

    Follows each skill's Concept Extraction Guide:
    - Blog post -> read title + first 2-3 paragraphs -> core metaphor
    """
    # For most skills, combine title and description as the concept
    concept = f"{title}. {description}" if description else title
    # Truncate to reasonable length for the prompt
    if len(concept) > 400:
        concept = concept[:397] + "..."
    return concept


# ── Codex CLI generation ────────────────────────────────────────

CODEX_IMAGES_DIR = Path.home() / ".codex" / "generated_images"


def _generate_codex_image(full_prompt: str, out_path: str,
                          timeout: int = 300,
                          retry_timeout: int = 360) -> Optional[str]:
    """Generate an image via Codex CLI and copy it to out_path.

    Handles the bwrap sandbox limitation: Codex generates the image internally
    but can't always write outside its sandbox. After the run, we find the
    newest image in ~/.codex/generated_images/ and copy it.

    Retries once with a longer timeout if the first attempt fails or times out
    (migrated from the now-deleted codex_image_gen.py).

    Returns out_path on success, None on failure.
    """
    for attempt, current_timeout in enumerate([timeout, retry_timeout], 1):
        before_ts = time.time()

        try:
            result = subprocess.run(
                ["codex", "exec", "--disable", "use_linux_sandbox_bwrap",
                 full_prompt],
                capture_output=True, text=True, timeout=current_timeout,
                cwd=str(config.SAHILBLOG_REPO),
            )
            print(f"[blog_illustrator] codex exec exit={result.returncode} (attempt {attempt})")
            if result.stdout:
                for line in result.stdout.strip().splitlines():
                    print(f"  [codex] {line}")
        except subprocess.TimeoutExpired:
            print(f"[blog_illustrator] codex timed out after {current_timeout}s (attempt {attempt})")
            if attempt == 1:
                print(f"[blog_illustrator] retrying with {retry_timeout}s timeout")
            continue
        except Exception as exc:
            print(f"[blog_illustrator] codex execution error: {exc}")
            continue

        # Find the newest image generated during the run
        img = _find_latest_codex_image(after_ts=before_ts)
        if not img:
            print(f"[blog_illustrator] no image found after codex run (attempt {attempt})")
            if attempt == 1:
                print(f"[blog_illustrator] retrying with {retry_timeout}s timeout")
            continue

        # Verify the image exists
        img_path = Path(img)
        if not img_path.exists():
            print(f"[blog_illustrator] image path doesn't exist: {img}")
            continue

        size_kb = img_path.stat().st_size // 1024
        print(f"[blog_illustrator] generated {size_kb}KB -> {img}")

        # Copy to target
        try:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(img, out_path)
            print(f"[blog_illustrator] copied to {out_path}")
        except Exception as exc:
            print(f"[blog_illustrator] copy failed (attempt {attempt}): {exc}")
            continue

        # Verify the copy
        if Path(out_path).exists():
            print(f"[blog_illustrator] verified: {Path(out_path).stat().st_size} bytes")
            return out_path

    print(f"[blog_illustrator] all Codex attempts failed for {out_path}")
    return None


def _find_latest_codex_image(
    after_ts: Optional[float] = None,
    images_dir: Path = CODEX_IMAGES_DIR,
) -> Optional[str]:
    """Find the newest Codex-generated image after a timestamp.

    Codex versions have used both exec-*.png and ig_*.png, so scan image
    extensions by file mtime rather than relying on a filename prefix.
    """
    if not images_dir.exists():
        return None

    candidates: list[tuple[float, str]] = []
    for session_dir in images_dir.iterdir():
        if not session_dir.is_dir():
            continue
        for img in session_dir.glob("*"):
            if img.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                continue
            try:
                mtime = img.stat().st_mtime
            except OSError:
                continue
            if after_ts is None or mtime >= after_ts:
                candidates.append((mtime, str(img)))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _generate_webp(png_path: str) -> Optional[str]:
    """Generate a WebP copy alongside the PNG for the Astro <picture> tag."""
    webp_path = Path(png_path).with_suffix(".webp")
    if webp_path.exists():
        return str(webp_path)
    try:
        result = subprocess.run(
            [
                "node", "-e",
                f"const s=require('sharp');"
                f" s('{png_path}').webp({{quality:90,effort:6}}).toFile('{webp_path}')"
                f" .then(()=>console.log('ok'))",
            ],
            capture_output=True, timeout=60,
            cwd=str(config.SAHILBLOG_REPO),
        )
        if result.returncode == 0 and webp_path.exists():
            sz = webp_path.stat().st_size
            print(f"[blog_illustrator] webp generated: {webp_path} ({sz} bytes)")
            return str(webp_path)
    except Exception as exc:
        print(f"[blog_illustrator] webp generation skipped: {exc}")
    return None


# ── Section text extraction (kept for test compat) ──────────────

def _extract_h2_headings(body_md: str) -> list[str]:
    """Extract H2 heading texts from markdown body."""
    out = []
    for line in body_md.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            out.append(m.group(1).strip())
    return out


def _extract_diagram_spec(draft: dict) -> str | None:
    """Extract Mermaid diagram code from a blueprint-format draft."""
    body = draft.get("body_md", "") or ""
    m = re.search(r"```mermaid\n(.*?)```", body, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


def _extract_section_text(body_lines: list[str], heading: str) -> str:
    """Return the body text under a given H2 heading."""
    found = False
    lines: list[str] = []
    for line in body_lines:
        if re.match(r"^##\s+" + re.escape(heading) + r"\s*$", line):
            found = True
            continue
        if found:
            if line.startswith("## "):
                break
            lines.append(line)
    return " ".join(l.strip() for l in lines if l.strip())[:400]


# ── Blog illustration ───────────────────────────────────────────

def _select_and_generate(
    title: str,
    description: str,
    stream: str,
    out_path: str,
    is_section: bool = False,
    heading: Optional[str] = None,
    skill_name: Optional[str] = None,
) -> Optional[str]:
    """Select a creative skill, build the prompt, and generate via Codex CLI.

    When skill_name is provided, uses that skill directly (no re-selection).
    When omitted, selects a fresh skill based on content heuristics.

    Flow:
      1. (Optionally) select skill based on content heuristics
      2. Load the full prompt template from the skill's SKILL.md
      3. Build the {CONCEPT} from title/description
      4. Fill the template with the concept
      5. Generate via Codex CLI
      6. Copy result to out_path

    Returns out_path on success, None on failure.
    """
    if skill_name is None:
        skill_name = _select_skill(title, stream)
    template = _load_prompt_template(skill_name)

    if not template:
        print(f"[blog_illustrator] no template for {skill_name}, "
              f"falling back to generic prompt")
        # Generic fallback prompt
        concept = _build_concept(title, description, skill_name)
        prompt = (
            f"Create an editorial illustration for a blog post. "
            f"Title: {title}. Concept: {concept}. "
            f"No text in the image. 16:9 landscape, high detail."
        )
    else:
        # Build the concept and fill the template
        concept = _build_concept(title, description, skill_name)
        prompt = template.replace("{CONCEPT}", concept)

        # Remove optional variables that aren't used for blog heroes
        prompt = re.sub(r"\{REFERENCE\}", "N/A", prompt)
        prompt = re.sub(r"\{MOOD\}", "", prompt)
        prompt = re.sub(r"\{EMOTIONAL_TONE\}", "", prompt)
        prompt = re.sub(r"\{EDITORIAL_TONE\}", "", prompt)

        # Add blog-specific output instruction
        prompt += (
            "\n\n---\n\n"
            f"Generate this illustration. No text in the image. "
            f"16:9 landscape format, high detail."
        )

    # Generate via Codex CLI
    return _generate_codex_image(prompt, out_path)


def illustrate(
    draft: dict,
    out_dir: Optional[Path] = None,
    max_sections: Optional[int] = None,
    workdir: Optional[str] = None,
) -> dict:
    """Generate hero + per-section images via creative-skill rotation + Codex CLI.

    Uses the 6 universal illustration style skills (Mythic Tech Codex, Cosmic
    Postcard Atelier, Saga Noir Studio, Ink & Ember Studio, The Ninth Observatory,
    Chromatic Institute), selecting the best fit for each post and rotating
    for visual variety.

    Generation: Codex CLI (ChatGPT subscription OAuth, £0 cost).
    No FAL, no Pollinations, no Baoyu pipeline.

    Returns {hero_path: str|None, section_paths: {h2_heading: path}}.

    Args:
        draft: Blog draft dict with title, description, body_md, stream.
        out_dir: Directory for generated images.
        max_sections: Maximum section images.
        workdir: Ignored (kept for backward compat).
    """
    stream = draft.get("stream", "ai")

    if max_sections is None:
        max_sections = config.BLOG_MAX_SECTION_IMAGES

    out_path = Path(out_dir) if out_dir else Path(config.OUTPUT_DIR) / "blog_images"
    out_path.mkdir(parents=True, exist_ok=True)

    result: dict = {"hero_path": None, "section_paths": {}}

    # Select ONE creative skill for this entire post (consistent style)
    title = draft.get("title", "")
    description = draft.get("description", "")
    post_skill = _select_skill(title, stream)

    # ── Hero image ──────────────────────────────────────────
    hero_out = str(out_path / "hero.png")
    gen = _select_and_generate(
        title, description, stream, hero_out, skill_name=post_skill,
    )

    if gen and Path(gen).exists():
        result["hero_path"] = gen
        print(f"[blog_illustrator] hero via {gen}")
        _generate_webp(gen)
    else:
        print(f"[blog_illustrator] hero generation failed for '{title}'")

    # ── Section images ──────────────────────────────────────
    if max_sections > 0:
        headings = _extract_h2_headings(draft.get("body_md", ""))
        body_lines = draft.get("body_md", "").splitlines()
        for idx, heading in enumerate(headings[:max_sections], 1):
            section_text = _extract_section_text(body_lines, heading)
            section_out = str(out_path / f"section_{idx:02d}.png")

            # Use heading as the title for concept extraction
            gen_sec = _select_and_generate(
                heading, section_text or heading, stream,
                section_out, is_section=True, heading=heading,
                skill_name=post_skill,
            )
            if gen_sec and Path(gen_sec).exists():
                result["section_paths"][heading] = gen_sec
                print(f"[blog_illustrator] section {idx} via {gen_sec}")
            else:
                print(f"[blog_illustrator] section '{heading}' generation failed")

    return result
