#!/usr/bin/env python3
"""Run inbox-fetch workflow: fetch items, create drafts, gen images, deliver."""
import json
import os
import subprocess
import sys
import tempfile

WORKDIR = "/home/kensei/repos/KenseiAgent/content_engine"
ENV_FILE = "/home/kensei/.hermes/.env"
PYTHON = "python3"
SCRIPT = os.path.join(WORKDIR, "content_engine.py")

def load_env():
    """Load env vars from the .env file."""
    env = os.environ.copy()
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    env[key] = val
    env["PYTHONPATH"] = WORKDIR
    return env

def run_python(args, env=None, timeout=120):
    """Run a python script command directly (no shell wrapping)."""
    if env is None:
        env = load_env()
    cmd = [PYTHON, SCRIPT] + args
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=WORKDIR)
    return proc.returncode, proc.stdout, proc.stderr

def run_python_with_stdin(args, stdin_text, env=None, timeout=120):
    """Run a python script command with stdin."""
    if env is None:
        env = load_env()
    cmd = [PYTHON, SCRIPT] + args
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=WORKDIR, input=stdin_text)
    return proc.returncode, proc.stdout, proc.stderr

def main():
    env = load_env()

    # Step 1: inbox-fetch
    print("=== STEP 1: inbox-fetch ===", flush=True)
    rc, stdout, stderr = run_python(["inbox-fetch"], env=env)
    if rc != 0:
        print(f"ERROR: inbox-fetch failed (rc={rc})")
        if stderr:
            print(f"stderr: {stderr[:500]}")
        sys.exit(1)

    print(f"stdout:\n{stdout[:1000]}", flush=True)
    if stderr:
        print(f"stderr: {stderr[:500]}", flush=True)

    items = []
    for line in stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            print(f"Comment: {line}")
            continue
        try:
            item = json.loads(line)
            if isinstance(item, dict) and "msg_id" in item:
                items.append(item)
        except json.JSONDecodeError:
            pass

    if not items:
        print("[SILENT]")
        print("=== No items to process. Skipping deliver-discord. ===")
        return 0

    print(f"Found {len(items)} item(s)", flush=True)

    draft_results = []

    # Step 2-4: Process each item
    for idx, item in enumerate(items):
        print(f"\n=== Processing item {idx+1}/{len(items)} ===", flush=True)
        print(f"Item: msg_id={item.get('msg_id')} caption={item.get('caption','')[:150]}")

        caption = item.get("caption", "")
        images = item.get("images", [])
        links = item.get("links", [])
        videos = item.get("videos", [])

        # Determine brand from caption
        caption_lower = caption.lower()
        if any(kw in caption_lower for kw in ["plenish", "cook", "kitchen", "recipe", "meal", "food", "dish", "ingredient"]):
            brand = "plenishd"
        elif any(kw in caption_lower for kw in ["coach", "coaching", "client", "training", "fitness", "session", "framework"]):
            brand = "coachos"
        elif any(kw in caption_lower for kw in ["matchday", "maestro", "football", "soccer", "gameweek", "fantasy", "predict", "stadium", "pitch"]):
            brand = "matchdaymaestro"
        elif any(kw in caption_lower for kw in ["linkedin", "product", "pm ", "leadership", "strategy", "team", "vision", "roadmap", "stakeholder"]):
            brand = "sahil_linkedin"
        else:
            brand = "sahil_twitter"

        platform_map = {
            "sahil_twitter": "x",
            "sahil_linkedin": "linkedin",
            "plenishd": "instagram",
            "coachos": "instagram",
            "matchdaymaestro": "x",
        }
        platform = platform_map.get(brand, "x")

        print(f"Brand: {brand}, Platform: {platform}", flush=True)

        # Generate title from caption
        title_words = caption.strip().split()[:7]
        short_title = " ".join(title_words) if title_words else "inspired post"
        if len(short_title) > 60:
            short_title = short_title[:60]

        # Generate on-brand copy
        copy = generate_onbrand_copy(brand, caption, images, links, videos)
        print(f"Copy: {copy[:200]}...", flush=True)

        # Step 3c: Create draft - use stdin to avoid shell quoting issues
        import uuid
        draft_id = f"{brand[:4]}_{uuid.uuid4().hex[:8]}"

        # Direct approach: write the draft via a quick sub-script that calls the API directly
        # to avoid shell quoting entirely
        direct_script = f"""
import sys
sys.path.insert(0, {repr(WORKDIR)})
from database import init_db, insert_draft
init_db()
draft_id = {repr(draft_id)}
insert_draft(
    draft_id=draft_id,
    brand={repr(brand)},
    platform={repr(platform)},
    pillar="repurpose",
    topic="repurpose",
    title={repr(short_title)},
    body_text={repr(copy)},
    content_type="text+image",
)
print(draft_id)
"""
        proc = subprocess.run(
            [PYTHON, "-c", direct_script],
            capture_output=True, text=True, timeout=30,
            env=env, cwd=WORKDIR
        )
        if proc.returncode != 0:
            print(f"ERROR: add-draft failed: {proc.stderr[:300]}")
            continue
        draft_id = proc.stdout.strip()
        print(f"Draft ID: {draft_id}", flush=True)

        # Step 3d: Generate image
        image_prompt = generate_image_prompt(brand, caption, images)
        print(f"Image prompt: {image_prompt[:200]}...", flush=True)

        img_script = f"""
import sys
sys.path.insert(0, {repr(WORKDIR)})
from database import get_draft
from draft_media import generate_post_image
d = get_draft({repr(draft_id)})
if d:
    path = generate_post_image(d, scene_prompt={repr(image_prompt)})
    if path:
        from database import update_draft_ai_image_path
        update_draft_ai_image_path({repr(draft_id)}, path)
        print(f"Image: {{path}}")
    else:
        print("Image generation failed")
else:
    print("Draft not found")
"""
        proc = subprocess.run(
            [PYTHON, "-c", img_script],
            capture_output=True, text=True, timeout=120,
            env=env, cwd=WORKDIR
        )
        print(f"gen-image result: {proc.stdout.strip()}", flush=True)
        if proc.returncode != 0 or proc.stderr:
            print(f"gen-image stderr: {proc.stderr[:300]}", flush=True)

        draft_results.append((brand, draft_id, short_title))

    # Step 5: deliver-discord
    print("\n=== STEP 5: deliver-discord ===", flush=True)
    rc, stdout4, stderr4 = run_python(["deliver-discord", "--since-minutes", "90"], env=env)
    print(f"Deliver result: {stdout4[:500]}", flush=True)
    if stderr4:
        print(f"Deliver stderr: {stderr4[:500]}", flush=True)

    # Step 6: Summary
    print("\n=== SUMMARY ===", flush=True)
    for brand, did, title in draft_results:
        print(f"{brand} {did} {title}")


def generate_onbrand_copy(brand, caption, images, links, videos):
    """Generate on-brand copy. British English, no em-dashes, no AI filler."""
    intro = caption.strip()
    # Keep it concise - repurposed from the reference caption intent

    copies = {
        "sahil_twitter": (
            f"{intro}\n\n"
            f"shipped it, no hype. just numbers and lessons learned."
        ),
        "sahil_linkedin": (
            f"{intro}\n\n"
            f"product thinking is about asking better questions, not having better answers. "
            f"here is what that looks like in practice."
        ),
        "plenishd": (
            f"{intro}\n\n"
            f"sunday prep sorted. a full week of flavour with half the effort. "
            f"this is how we do it in my kitchen."
        ),
        "coachos": (
            f"{intro}\n\n"
            f"your clients already know what to do. the gap is execution, not education. "
            f"here is the system that closes it."
        ),
        "matchdaymaestro": (
            f"{intro}\n\n"
            f"place your predictions, stake your coins, and watch the table shift. "
            f"no betting talk here, just pure football banter and smart picks."
        ),
    }
    return copies.get(brand, f"{intro}\n\nBuilding in public, raw and real.")


def generate_image_prompt(brand, caption, reference_images):
    """Generate a vivid, original image prompt. NEVER copy the reference."""
    ref_hint = "original composition inspired by a reference but completely redesigned"

    prompts = {
        "sahil_twitter": (
            f"A minimalist desk setup with a laptop displaying real-time analytics and a notebook with handwritten notes, "
            f"morning light casting long shadows, indie maker aesthetic, photorealistic. {ref_hint}"
        ),
        "sahil_linkedin": (
            f"A bright whiteboard covered in product roadmap sketches and sticky notes, a coffee cup on the side, "
            f"professional editorial style, natural window lighting, clean composition. {ref_hint}"
        ),
        "plenishd": (
            f"A rustic wooden kitchen table with fresh herbs, olive oil bottle, and a steaming bowl of pasta, "
            f"warm afternoon sunlight, British food photography style, cosy and inviting. {ref_hint}"
        ),
        "coachos": (
            f"A leather notebook open to a hand-drawn coaching framework, a smartphone showing a client session timer, "
            f"soft natural light, professional documentary photography style, clean and focused. {ref_hint}"
        ),
        "matchdaymaestro": (
            f"A smartphone held up against a stadium backdrop showing a prediction leaderboard interface, "
            f"evening floodlights, vibrant team colours, dynamic sports photo style. {ref_hint}"
        ),
    }
    return prompts.get(brand, prompts["sahil_twitter"])


if __name__ == "__main__":
    sys.exit(main())