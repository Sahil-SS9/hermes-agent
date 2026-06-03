#!/usr/bin/env python3
"""Content Engine v2 — Main orchestrator

Stage 1: LLM-generated drafts → review/approve
Stage 2: AI images/videos for approved drafts → publish
"""
import sqlite3
import json
import os
import argparse
from datetime import datetime
from typing import List, Optional

# Core imports
from config import BRANDS
from database import init_db, insert_draft, list_drafts, get_draft, update_draft_visual_path, list_recent_drafts
from database import approve_draft, reject_draft, mark_enriched
from database import list_approved_pending_enrichment, truncate_drafts, purge_stale_drafts, count_drafts_older_than
from database import update_draft_ai_image_path, update_draft_ai_video_path
from llm_drafts import generate_drafts
from telegram_digest import deliver_digest, send_message


def run_stage_1(
    brands: List[str],
    brand_topics: Optional[dict] = None,
    dry_run: bool = False,
    platform: Optional[str] = None,
    use_llm: bool = False,
) -> List[dict]:
    """Generate drafts using LLM with brand voice. Zero cost if fallback templates.

    Args:
        brands: List of brand keys to generate for
        brand_topics: Override topics: {brand: [{pillar, topic}, ...]}
        dry_run: If True, don't save to DB
        platform: Override platform (e.g., "twitter", "linkedin")
        use_llm: If True, use LLM generation for personal brands instead of static templates

    Returns:
        List of draft dicts
    """
    # Personal brands that get LLM generation
    LLM_BRANDS = {"sahil_twitter", "sahil_linkedin"}

    all_drafts = []

    for brand in brands:
        if brand not in BRANDS:
            print(f"Unknown brand: {brand}. Skipping.")
            continue

        print(f"[{brand}] Generating drafts...")

        # Load topics from config or override
        from topics import get_topics
        
        if brand_topics and brand in brand_topics:
            topics = brand_topics[brand]
        else:
            topics = get_topics(brand, count=6)

        if not topics:
            print(f"[{brand}] No topics found. Skipping.")
            continue

        print(f"[{brand}] {len(topics)} topics, generating drafts...")

        # Determine platform from brand config (fixes default-twitter bug)
        brand_config = BRANDS.get(brand, {})
        brand_platforms = brand_config.get("platforms", [])
        effective_platform = platform or (brand_platforms[0] if brand_platforms else "twitter")

        # Generate — branch personal brands to LLM path
        if use_llm and brand in LLM_BRANDS:
            from llm_generate import generate_drafts_llm
            drafts = generate_drafts_llm(brand, topics, platform=effective_platform)
        else:
            drafts = generate_drafts(brand, topics, platform=effective_platform)

        print(f"[{brand}] Generated {len(drafts)} draft(s)")

        for d in drafts:
            slop_info = ""
            audit = d.get("slop_audit")
            if audit:
                slop_mark = "✅" if audit["passed"] else "⚠️"
                issues_str = "; ".join(audit["issues"][:2])
                slop_info = f" slop={audit['slop_score']}/10 {slop_mark} {issues_str}"
            
            print(f"    {d['id']} [{d.get('pillar','')}]{slop_info}")
            
            if not dry_run:
                audit = d.get("slop_audit", {})
                insert_draft(
                    draft_id=d["id"],
                    brand=d["brand"],
                    platform=d["platform"],
                    pillar=d.get("pillar", ""),
                    topic=d.get("topic", ""),
                    title=d.get("title"),
                    body_text=d["body_text"],
                    content_type=d.get("content_type", "text"),
                    visual_description=d.get("visual_description"),
                    visual_path=d.get("visual_path"),
                    slop_score=audit.get("slop_score", 0),
                    slop_issues="; ".join(audit.get("issues", [])),
                )
            all_drafts.append(d)

    return all_drafts


def run_stage_2(dry_run: bool = False) -> List[dict]:
    """Generate AI media for approved drafts.

    Returns list of enriched drafts.
    """
    approved = list_approved_pending_enrichment()
    if not approved:
        print("No approved drafts pending Stage 2 enrichment.")
        return []

    if dry_run:
        for d in approved:
            print(f"  [DRY] {d['id']} brand={d['brand']} type={d.get('content_type', 'text')}")
        return approved

    print(f"Enriching {len(approved)} approved draft(s)...")

    # Unified media path: the same degrading FAL chain + free fallbacks used by
    # the review digest and the approve flow.
    from draft_media import generate_post_image, generate_draft_video

    enriched = []
    for d in approved:
        brand = d["brand"]
        draft_id = d["id"]
        body_text = d.get("body_text", "")
        content_type = d.get("content_type", "text")

        print(f"  [{draft_id}] brand={brand} type={content_type}")

        needs_media = "image" in content_type or "video" in content_type

        if needs_media and not d.get("ai_image_path"):
            img = generate_post_image(d)
            if img:
                update_draft_ai_image_path(draft_id, img)
                d["ai_image_path"] = img
                print(f"    Image: {img}")

        if "video" in content_type and not d.get("ai_video_path"):
            vid = generate_draft_video(d.get("ai_image_path"), body_text, brand, draft_id)
            if vid:
                update_draft_ai_video_path(draft_id, vid)
                d["ai_video_path"] = vid
                print(f"    Video: {vid}")

        # Mark enriched only when the required media exists, so a failed
        # generation is retried on the next Stage 2 pass. A video post needs its
        # video; an image post needs its image.
        video_ok = "video" not in content_type or d.get("ai_video_path")
        image_ok = "image" not in content_type or d.get("ai_image_path")
        if not needs_media or (video_ok and image_ok):
            mark_enriched(draft_id)
            enriched.append(d)
        else:
            print(f"    [skip] media incomplete, leaving for retry")

    return enriched


def attach_free_visual_previews(drafts: List[dict], dry_run: bool = False) -> List[dict]:
    """Generate free Pillow preview cards for the current approval batch only.

    Paid AI imagery remains behind explicit approval / Stage 2. This gives Sahil
    visual context up front without burning FAL/Replicate/Together credit.
    """
    if not drafts:
        return drafts

    from visuals import make_card

    for d in drafts:
        draft_id = d.get("id")
        if not draft_id:
            continue
        try:
            visual_path = make_card(
                d.get("brand", "sahil_twitter"),
                d.get("body_text", ""),
                title=d.get("title"),
                platform=d.get("platform", "twitter"),
                out_filename=f"{draft_id}.png",
                content_type=d.get("content_type", "text"),
                pillar=d.get("pillar", ""),
            )
            d["visual_path"] = visual_path
            if not dry_run:
                update_draft_visual_path(draft_id, visual_path)
            print(f"    preview={visual_path}")
        except Exception as e:
            print(f"    preview failed for {draft_id}: {e}")

    return drafts


def run_digest(dry_run: bool = False, drafts: Optional[List[dict]] = None) -> bool:
    """Deliver review digest.

    If drafts is supplied, deliver only that current generated batch. This avoids
    resurfacing every old pending draft each morning.
    """
    drafts = drafts if drafts is not None else list_drafts(status="draft")
    if not drafts:
        print("No pending drafts to deliver.")
        return False

    if dry_run:
        for d in drafts[:3]:
            print(f"  [DRY] {d['id']} [{d['brand']}/{d['platform']}]")
            print(f"    Type: {d.get('content_type', 'text')}")
            print(f"    Visual: {d.get('visual_path') or 'not generated'}")
            print(f"    {d['body_text'][:80]}")
            print()
        return True

    # Deliver digest
    print(f"Delivering {len(drafts)} current draft(s) to Telegram...")
    deliver_digest(drafts)
    return True


def run_generate_all(dry_run: bool = False, brands: Optional[List[str]] = None) -> bool:
    """Run Stage 1 + deliver digest.

    App brands use static templates; personal brands can be generated separately
    by the CeeCee LLM cron, then included via digest --since-minutes.
    """
    brands = brands or list(BRANDS.keys())
    LLM_BRANDS = {"sahil_twitter", "sahil_linkedin"}
    
    print(f"Generating drafts for {len(brands)} brand(s)...")
    drafts = run_stage_1(brands, dry_run=dry_run, use_llm=True)
    
    if not drafts:
        print("No drafts generated.")
        return False
    
    print(f"\nStage 1: {len(drafts)} draft(s)")
    attach_free_visual_previews(drafts, dry_run=dry_run)
    
    if not dry_run:
        run_digest(dry_run=False, drafts=drafts)
    
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="KENSEI Content Engine v2")
    sub = parser.add_subparsers(dest="cmd")

    # Stage 1 (static templates)
    s1 = sub.add_parser("stage1", help="Stage 1: draft generation (static templates)")
    s1.add_argument("--brand", "-b", nargs="+", default=list(BRANDS.keys()))
    s1.add_argument("--platform", "-p", default=None)
    s1.add_argument("--dry-run", action="store_true")

    # Stage 1 LLM (personal brands only)
    s1llm = sub.add_parser("stage1-llm", help="Stage 1 LLM: personal brand generation via LLM")
    s1llm.add_argument("--brand", "-b", nargs="+", default=["sahil_twitter", "sahil_linkedin"])
    s1llm.add_argument("--platform", "-p", default=None)
    s1llm.add_argument("--dry-run", action="store_true")
    s1llm.add_argument("--self-call", action="store_true", help="Use local model call instead of subprocess")

    # Stage 2
    s2 = sub.add_parser("stage2", help="Stage 2: AI media generation")
    s2.add_argument("--dry-run", action="store_true")

    # Generate all
    gen = sub.add_parser("generate", help="Generate + deliver")
    gen.add_argument("--brand", "-b", nargs="+", default=list(BRANDS.keys()))
    gen.add_argument("--dry-run", action="store_true")

    # Digest
    dig = sub.add_parser("digest", help="Deliver Telegram digest")
    dig.add_argument("--dry-run", action="store_true")
    dig.add_argument("--since-minutes", type=int, default=None, help="Only include drafts created in the last N minutes")

    # review-list: recent drafts the agent should image, as compact JSON lines
    rls = sub.add_parser("review-list", help="List recent drafts (id, brand, platform, content_type, body)")
    rls.add_argument("--since-minutes", type=int, default=75)

    # gen-image: cheapest-first image for one draft, persisted to ai_image_path
    gi = sub.add_parser("gen-image", help="Generate + persist an image for a draft (FAL flux_klein → pollinations)")
    gi.add_argument("draft_id")
    gi.add_argument("--prompt", default=None, help="Art-directed prompt; falls back to an on-brand prompt from body_text")
    gi.add_argument("--model", default=None, help="Override the primary model (else the degrading chain)")
    gi.add_argument("--force", action="store_true", help="Regenerate even if ai_image_path is already set")

    # deliver-discord: grouped-by-brand review to Discord
    dd = sub.add_parser("deliver-discord", help="Deliver recent drafts to Discord, grouped by brand")
    dd.add_argument("--since-minutes", type=int, default=75)

    # review-digest: generate cheap images for recent text+image drafts, then deliver
    rd = sub.add_parser("review-digest", help="Generate images for recent text+image drafts and deliver to Discord")
    rd.add_argument("--since-minutes", type=int, default=75)
    rd.add_argument("--max", type=int, default=None, help="Cap drafts delivered (flood guard / testing)")

    # inbox-fetch: poll the repurpose inbox; print new items as JSON lines
    inb = sub.add_parser("inbox-fetch", help="Poll the Discord repurpose inbox for new reference items")

    # add-draft: insert an inspired-by draft (used by the repurpose agent)
    ad = sub.add_parser("add-draft", help="Insert a draft (inspired-by repurpose output)")
    ad.add_argument("--brand", required=True)
    ad.add_argument("--platform", required=True)
    ad.add_argument("--body", required=True)
    ad.add_argument("--content-type", default="text")
    ad.add_argument("--title", default=None)
    ad.add_argument("--pillar", default="repurpose")
    ad.add_argument("--image", default=None, help="Optional local image path to attach")

    # Approve
    app = sub.add_parser("approve", help="Approve a draft")
    app.add_argument("draft_id")

    # Reject
    rej = sub.add_parser("reject", help="Reject a draft")
    rej.add_argument("draft_id")

    # List
    lst = sub.add_parser("list", help="List drafts")
    lst.add_argument("--status", "-s", default="draft")
    lst.add_argument("--brand", "-b", default=None)

    # Truncate (dangerous — prefer purge)
    trunc = sub.add_parser("truncate", help="Delete all drafts (DANGEROUS — prefer purge)")
    trunc.add_argument("--force", action="store_true", help="Skip confirmation")

    # Purge (safe — 48h retention)
    purge = sub.add_parser("purge", help="Delete drafts older than 48h (safe cleanup)")
    purge.add_argument("--dry-run", action="store_true", help="Preview only")
    purge.add_argument("--retention", "-r", type=int, default=48, help="Retention in hours (default: 48)")
    purge.add_argument("--brand", "-b", default=None)

    args = parser.parse_args()
    
    init_db()

    if args.cmd == "stage1":
        drafts = run_stage_1(args.brand, dry_run=args.dry_run, platform=args.platform)
        print(f"\nStage 1 complete: {len(drafts)} draft(s)")
        return 0

    elif args.cmd == "stage1-llm":
        if args.self_call:
            # Self-call mode: print the prompt for each brand's first topic
            # so the calling agent can generate text directly
            for brand in args.brand:
                if brand not in BRANDS:
                    print(f"Unknown brand: {brand}. Skipping.")
                    continue
                from topics import get_topics
                topics = get_topics(brand, count=6)
                if not topics:
                    print(f"[{brand}] No topics found.")
                    continue
                brand_config = BRANDS.get(brand, {})
                brand_platforms = brand_config.get("platforms", [])
                effective_platform = args.platform or (brand_platforms[0] if brand_platforms else "twitter")

                for i, topic in enumerate(topics):
                    from llm_generate import build_generation_prompt
                    prompts = build_generation_prompt(brand, topic, effective_platform)
                    print(f"\n{'='*70}")
                    print(f"BRAND={brand} PLATFORM={effective_platform} TOPIC={i+1}/{len(topics)}")
                    print(f"PILLAR={topic.get('pillar','')} SUBJECT={topic.get('topic','')}")
                    print(f"{'='*70}")
                    print(f"\nSYSTEM PROMPT:\n{prompts['system']}")
                    print(f"\nUSER PROMPT:\n{prompts['user']}")
                    print(f"\n{'='*70}")
            print("\n--self-call: generate text for each TOPIC above, then call:")
            print("  content_engine.py stage1-llm --brand <brand> --persist")
            print("  passing body_text via pipe or --body-text-file")
            return 0

        # Normal mode: generate drafts using the LLM path
        drafts = run_stage_1(args.brand, dry_run=args.dry_run, platform=args.platform, use_llm=True)
        print(f"\nStage 1 LLM complete: {len(drafts)} draft(s)")
        return 0

    elif args.cmd == "stage2":
        drafts = run_stage_2(dry_run=args.dry_run)
        print(f"\nStage 2 complete: {len(drafts)} enriched")
        return 0

    elif args.cmd == "generate":
        ok = run_generate_all(dry_run=args.dry_run, brands=args.brand)
        return 0 if ok else 1

    elif args.cmd == "digest":
        digest_drafts = list_recent_drafts(args.since_minutes) if args.since_minutes else None
        if digest_drafts is not None:
            attach_free_visual_previews(digest_drafts, dry_run=args.dry_run)
        ok = run_digest(dry_run=args.dry_run, drafts=digest_drafts)
        return 0 if ok else 1

    elif args.cmd == "review-list":
        drafts = list_recent_drafts(args.since_minutes)
        for d in drafts:
            if not (d.get("body_text") or "").strip():
                continue
            print(json.dumps({
                "id": d["id"],
                "brand": d["brand"],
                "platform": d["platform"],
                "content_type": d.get("content_type", "text"),
                "has_image": bool(d.get("ai_image_path")),
                "body": (d.get("body_text") or "")[:200],
            }))
        return 0

    elif args.cmd == "gen-image":
        from draft_media import generate_post_image
        d = get_draft(args.draft_id)
        if not d:
            print(f"Draft not found: {args.draft_id}")
            return 1
        if d.get("ai_image_path") and not args.force:
            print(f"Already has image: {d['ai_image_path']} (use --force to regenerate)")
            return 0
        path = generate_post_image(d, model=args.model, scene_prompt=args.prompt)
        if not path:
            print(f"Image generation failed for {args.draft_id}")
            return 1
        update_draft_ai_image_path(args.draft_id, path)
        print(f"Image: {path}")
        return 0

    elif args.cmd == "deliver-discord":
        from discord_digest import deliver_discord_digest
        drafts = list_recent_drafts(args.since_minutes)
        ok = deliver_discord_digest(drafts)
        return 0 if ok else 1

    elif args.cmd == "inbox-fetch":
        from repurpose import fetch_inbox
        items = fetch_inbox()
        for it in items:
            print(json.dumps(it))
        if not items:
            print("# no new inbox items")
        return 0

    elif args.cmd == "add-draft":
        import uuid as _uuid
        draft_id = f"{args.brand[:4]}_{_uuid.uuid4().hex[:8]}"
        insert_draft(
            draft_id=draft_id,
            brand=args.brand,
            platform=args.platform,
            pillar=args.pillar,
            topic="repurpose",
            title=args.title,
            body_text=args.body,
            content_type=args.content_type,
        )
        if args.image and os.path.exists(args.image):
            update_draft_ai_image_path(draft_id, args.image)
        print(draft_id)
        return 0

    elif args.cmd == "review-digest":
        # One deterministic pass: generate a cheap on-brand image for each recent
        # text+image draft (cheapest-first, free fallback), then deliver the whole
        # batch to Discord grouped by brand. text+video shows copy only here;
        # the video is generated on approval (Phase 2).
        from draft_media import generate_post_image
        from discord_digest import deliver_discord_digest

        drafts = list_recent_drafts(args.since_minutes)
        drafts = [d for d in drafts if (d.get("body_text") or "").strip()]
        if args.max is not None:
            drafts = drafts[:args.max]
        if not drafts:
            print("No recent drafts to review.")
            return 0

        for d in drafts:
            ct = d.get("content_type", "text")
            if "image" not in ct or d.get("ai_image_path"):
                continue
            path = generate_post_image(d)
            if path:
                update_draft_ai_image_path(d["id"], path)
                d["ai_image_path"] = path
                print(f"  [{d['id']}] image: {path}")
            else:
                print(f"  [{d['id']}] image generation failed")

        ok = deliver_discord_digest(drafts)
        return 0 if ok else 1

    elif args.cmd == "approve":
        approve_draft(args.draft_id)
        print(f"Approved {args.draft_id}")
        d = get_draft(args.draft_id)
        if d:
            brand = d["brand"]
            platform = d["platform"]
            ct = d.get("content_type", "text")
            from draft_media import generate_post_image, generate_draft_video

            # Ensure a base image exists for any visual post.
            if ("image" in ct or "video" in ct) and not d.get("ai_image_path"):
                img = generate_post_image(d)
                if img:
                    update_draft_ai_image_path(d["id"], img)
                    d["ai_image_path"] = img

            # Video is generated on approval (cheapest: free ffmpeg motion clip).
            media_path = None
            if "video" in ct:
                if not d.get("ai_video_path"):
                    vid = generate_draft_video(d.get("ai_image_path"), d.get("body_text", ""), brand, d["id"])
                    if vid:
                        update_draft_ai_video_path(d["id"], vid)
                        d["ai_video_path"] = vid
                media_path = d.get("ai_video_path") or d.get("ai_image_path")
            elif "image" in ct:
                media_path = d.get("ai_image_path")

            from postiz_bridge import queue_post
            post_id = queue_post(
                body_text=d["body_text"],
                brand=brand,
                platform=platform,
                title=d.get("title"),
                media_path=media_path,
            )
            if post_id:
                print(f"  Queued in Postiz: {post_id}")
            else:
                print(f"  No Postiz integration for {brand}/{platform} — exported to data/publish_queue/ for manual posting.")
                print(f"  To link this platform, log into Postiz at http://localhost:8080 and add the social account.")
        return 0

    elif args.cmd == "reject":
        reject_draft(args.draft_id)
        print(f"Rejected {args.draft_id}")
        return 0

    elif args.cmd == "list":
        drafts = list_drafts(status=args.status, brand=args.brand)
        print(f"{len(drafts)} draft(s) with status '{args.status}':")
        for d in drafts:
            ct = d.get("content_type", "text")
            print(f"  {d['id']} | {d['brand']} | {d['platform']} | {ct} | {d['body_text'][:60]}")
        return 0

    elif args.cmd == "truncate":
        if not args.force:
            confirm = input("DANGER: Delete ALL drafts? This cannot be undone. Type 'yes' to confirm: ")
            if confirm.strip().lower() != "yes":
                print("Aborted.")
                return 1
        truncate_drafts()
        print("All drafts deleted.")
        return 0

    elif args.cmd == "purge":
        retention = args.retention
        if args.dry_run:
            count = count_drafts_older_than(retention_hours=retention, brand=args.brand)
            scope = f"brand={args.brand}" if args.brand else "all brands"
            print(f"[DRY RUN] Would delete {count} draft(s) older than {retention}h ({scope})")
        else:
            deleted = purge_stale_drafts(retention_hours=retention, brand=args.brand)
            scope = f"brand={args.brand}" if args.brand else "all brands"
            print(f"Purged {deleted} draft(s) older than {retention}h ({scope})")
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
