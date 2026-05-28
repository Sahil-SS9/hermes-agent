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
from database import init_db, insert_draft, list_drafts, get_draft
from database import approve_draft, reject_draft, mark_enriched
from database import list_approved_pending_enrichment, truncate_drafts, purge_stale_drafts, count_drafts_older_than
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

    print(f"Enriching {len(approved)} approved draft(s)...")

    from fal_client import generate_image_from_text_card as fal_gen_image
    from hyperframes_video import generate_stat_reveal_video as make_hyperframes_stat_reveal_video

    enriched = []
    from visuals import make_card as make_pillow_card

    for d in approved:
        brand = d["brand"]
        draft_id = d["id"]
        body_text = d.get("body_text", "")
        visual_desc = d.get("visual_description", "")
        content_type = d.get("content_type", "text")

        print(f"  [{draft_id}] brand={brand} type={content_type}")

        # Stage 2.1: Pillow static card (free, always)
        static_path = make_pillow_card(brand, body_text, title=d.get("title"), pillar=d.get("pillar", ""))
        if static_path:
            print(f"    Static: {static_path}")

        # Stage 2.2: FAL.ai image for visual content types
        if "image" in content_type and fal_gen_image and visual_desc:
            print(f"    FAL.ai: Generating image...")
            try:
                img_path = fal_gen_image(brand, visual_desc)
                if img_path:
                    print(f"    Image: {img_path}")
            except Exception as e:
                print(f"    FAL.ai failed: {e}")

        # Stage 2.3: HyperFrames video for video content types
        if "video" in content_type and make_hyperframes_stat_reveal_video:
            print(f"    HyperFrames: Generating video...")
            try:
                vid_path = make_hyperframes_stat_reveal_video(brand, body_text[:100], draft_id=draft_id)
                if vid_path:
                    print(f"    Video: {vid_path}")
            except Exception as e:
                print(f"    HyperFrames failed: {e}")

        mark_enriched(draft_id)
        enriched.append(d)

    return enriched


def run_digest(dry_run: bool = False) -> bool:
    """Deliver Telegram digest of pending drafts for review."""
    drafts = list_drafts(status="draft")
    if not drafts:
        print("No pending drafts to deliver.")
        return False

    if dry_run:
        for d in drafts[:3]:
            print(f"  [DRY] {d['id']} [{d['brand']}/{d['platform']}]")
            print(f"    Type: {d.get('content_type', 'text')}")
            print(f"    {d['body_text'][:80]}")
            print()
        return True

    # Deliver digest
    print(f"Delivering {len(drafts)} draft(s) to Telegram...")
    deliver_digest(drafts)
    return True


def run_generate_all(dry_run: bool = False) -> bool:
    """Run Stage 1 + deliver digest.

    App brands use static templates; personal brands use LLM generation.
    """
    brands = list(BRANDS.keys())
    LLM_BRANDS = {"sahil_twitter", "sahil_linkedin"}
    
    print(f"Generating drafts for {len(brands)} brand(s)...")
    drafts = run_stage_1(brands, dry_run=dry_run, use_llm=True)
    
    if not drafts:
        print("No drafts generated.")
        return False
    
    print(f"\nStage 1: {len(drafts)} draft(s)")
    
    if not dry_run:
        run_digest(dry_run=False)
    
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
    gen.add_argument("--dry-run", action="store_true")

    # Digest
    dig = sub.add_parser("digest", help="Deliver Telegram digest")
    dig.add_argument("--dry-run", action="store_true")

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
        ok = run_generate_all(dry_run=args.dry_run)
        return 0 if ok else 1

    elif args.cmd == "digest":
        ok = run_digest(dry_run=args.dry_run)
        return 0 if ok else 1

    elif args.cmd == "approve":
        approve_draft(args.draft_id)
        print(f"Approved {args.draft_id}")
        d = get_draft(args.draft_id)
        if d:
            brand = d["brand"]
            platform = d["platform"]
            from postiz_bridge import queue_post
            post_id = queue_post(
                body_text=d["body_text"],
                brand=brand,
                platform=platform,
                title=d.get("title"),
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
