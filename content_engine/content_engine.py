"""Main orchestrator for the KENSEI Content Engine.
Two-stage pipeline:
  Stage 1: text drafts + static visuals (free) → approval
  Stage 2: AI images + videos for approved drafts only (costs money)
"""
import argparse
import os
import sys
from datetime import datetime
from typing import List, Optional

from config import BRANDS
from database import init_db, insert_draft, list_drafts, approve_draft, reject_draft
from drafts import generate_drafts
from postiz_bridge import queue_post
from telegram_digest import deliver_digest, send_message
from topics import get_topics
from visuals import make_card, make_leaderboard_card, make_streak_card, make_stat_reveal
from ffmpeg_video import make_stat_reveal_video, make_countdown_video, make_battle_challenge_video
try:
    from hyperframes_video import generate_stat_reveal_video as make_hyperframes_stat_reveal_video, generate_countdown_video as make_hyperframes_countdown_video, generate_screenshot_overlay_video as make_hyperframes_screenshot_overlay_video
except ImportError:
    make_hyperframes_stat_reveal_video = None
    make_hyperframes_countdown_video = None
    make_hyperframes_screenshot_overlay_video = None


try:
    from fal_client import generate_image, generate_video, generate_image_from_text_card
except ImportError:
    generate_image = None
    generate_video = None
    generate_image_from_text_card = None


def run_stage_1(brands: List[str], dry_run: bool = False, platform: Optional[str] = None) -> List[dict]:
    """Generate text drafts + static Pillow cards only. Zero cost."""
    all_drafts: List[dict] = []

    for brand in brands:
        if brand not in BRANDS:
            print(f"Unknown brand: {brand}. Skipping.")
            continue

        print(f"[{brand}] Collecting topics...")
        topics = get_topics(brand, count=3)
        if not topics:
            print(f"[{brand}] No topics found. Skipping.")
            continue

        print(f"[{brand}] Generating text drafts + static visuals...")
        drafts = generate_drafts(brand, topics, platform=platform)

        for d in drafts:
            vis_path = make_card(brand, d["body_text"], title=d.get("title"), platform=d["platform"])
            d["visual_path"] = vis_path

            if not dry_run:
                insert_draft(
                    draft_id=d["id"],
                    brand=d["brand"],
                    platform=d["platform"],
                    pillar=d["pillar"],
                    topic=d["topic"],
                    title=d.get("title"),
                    body_text=d["body_text"],
                    visual_path=vis_path,
                )
            all_drafts.append(d)

    return all_drafts


def run_stage_2(dry_run: bool = False) -> List[dict]:
    """Generate AI images and videos ONLY for approved drafts. Costs money."""
    approved = list_drafts(status="approved")
    if not approved:
        print("No approved drafts for Stage 2. Skipping AI generation.")
        return []

    enriched: List[dict] = []
    print(f"[{len(approved)}] approved draft(s) — generating AI visuals...")

    for d in approved:
        brand = d["brand"]
        pillar = d.get("pillar", "")
        body_text = d["body_text"]
        ai_paths = []

        # FAL.ai image for hero content
        if generate_image_from_text_card and pillar in (
            "live_predictions", "football_beat", "launch", "build_in_public",
            "product", "ai_tools", "session_plan", "player_dev"
        ):
            print(f"  [{d['id']}] FAL.ai image...")
            img_path = generate_image_from_text_card(brand, body_text)
            if img_path:
                ai_paths.append(img_path)

        # FFMPEG video for stat reveals
        if make_stat_reveal_video and pillar in ("live_predictions", "football_beat"):
            print(f"  [{d['id']}] FFMPEG stat reveal...")
            stat_line = body_text.split("\n")[0][:40]
            sub_line = body_text.split("\n")[-1][:60] if "\n" in body_text else ""
            vid_path = make_stat_reveal_video(brand, stat_line, sub_line, duration=3)
            if vid_path:
                ai_paths.append(vid_path)

        # FFMPEG countdown for game modes
        if make_countdown_video and pillar in ("live_predictions", "game_modes"):
            print(f"  [{d['id']}] FFMPEG countdown...")
            q_line = body_text.split("\n")[0][:80]
            c_path = make_countdown_video(brand, q_line, countdown_from=3)
            if c_path:
                ai_paths.append(c_path)

        # HyperFrames video for stat reveals (alternative to FFMPEG)
        if make_hyperframes_stat_reveal_video and pillar in ("live_predictions", "football_beat"):
            print(f'  [{d["id"]}] HyperFrames stat reveal...')
            stat_line = body_text.split("\n")[0][:40]
            sub_line = body_text.split("\n")[-1][:60] if "\n" in body_text else ""
            vid_path = make_hyperframes_stat_reveal_video(brand, stat_line, sub_line, draft_id=d["id"])
            if vid_path:
                ai_paths.append(vid_path)

        # HyperFrames screenshot overlay (for showcasing analytics/images)
        if make_hyperframes_screenshot_overlay_video and pillar in ("analytics", "product", "ai_tools"):
            print(f'  [{d["id"]}] HyperFrames screenshot overlay...')
            overlay_text = body_text.split("\n")[0][:100] if "\n" in body_text else body_text[:100]
            vid_path = make_hyperframes_screenshot_overlay_video(brand, overlay_text, draft_id=d["id"])
            if vid_path:
                ai_paths.append(vid_path)

        d["ai_paths"] = ai_paths
        enriched.append(d)

    return enriched


def generate_html_report(drafts: List[dict], stage: int = 1) -> str:
    """Detailed HTML report of generated content."""
    from datetime import datetime
    today = datetime.now().strftime("%a %d %b %Y %H:%M")

    lines = [
        "<!DOCTYPE html><html><head>",
        "<meta charset='utf-8'>",
        "<style>",
        "body{font-family:sans-serif;background:#0A0A0A;color:#C0C0C0;padding:24px;max-width:900px;margin:0 auto;}",
        "h1{color:#8B0000;border-bottom:2px solid #8B0000;padding-bottom:8px;}",
        "h2{color:#FBBF24;} .brand{color:#10B981;font-weight:bold;}",
        ".draft{border:1px solid #333;margin:14px 0;padding:14px;border-radius:8px;background:#111;}",
        ".meta{font-size:12px;color:#888;margin-bottom:8px;} .body{font-size:14px;line-height:1.6;white-space:pre-wrap;}",
        ".visual{font-size:11px;color:#555;margin-top:8px;} .cost{color:#E11D48;}",
        "</style></head><body>",
        f"<h1>KENSEI Content Engine Report — Stage {stage}</h1>",
        f"<p><b>Generated:</b> {today}</p>",
        f"<p><b>Total drafts:</b> {len(drafts)}</p>",
        "<hr>",
    ]

    for d in drafts:
        brand_display = d.get("brand", "").replace("_", " ").title()
        platform = d.get("platform", "twitter")
        cost_indicator = ""
        if stage == 2 and d.get("ai_paths"):
            cost_items = len([p for p in d["ai_paths"] if "fal" in p])
            cost_indicator = f" <span class='cost'>[FAL cost: {cost_items} item(s)]</span>"

        lines.append(f"\n<div class='draft'>")
        lines.append(f"  <div class='meta'>ID: <code>{d['id']}</code> | Brand: <span class='brand'>{brand_display}</span> | Platform: {platform} | Pillar: {d.get('pillar', '')}{cost_indicator}</div>")
        lines.append(f"  <div class='body'>{d.get('body_text', '')}</div>")
        if d.get("visual_path"):
            lines.append(f"  <div class='visual'>Static: {d['visual_path']}</div>")
        if d.get("ai_paths"):
            for p in d["ai_paths"]:
                lines.append(f"  <div class='visual'>AI: {p}</div>")
        lines.append("</div>")

    lines.append("</body></html>")
    return "\n".join(lines)


def save_html_report(html: str, stage: int = 1) -> str:
    from datetime import datetime
    from pathlib import Path
    out_dir = Path("/home/kensei/repos/KenseiAgent/content_engine/output/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    path = out_dir / f"stage_{stage}_report_{ts}.html"
    path.write_text(html, encoding="utf-8")
    return str(path)


def deliver_concise_summary(drafts: List[dict], stage: int = 1) -> bool:
    """Short, scannable 1/2 liner summary for Telegram."""
    if not drafts:
        return send_message("<b>⚡ KENSEI Content Engine</b>\n\nNo drafts generated.")

    today = datetime.now().strftime("%a %d %b")
    brand_counts = {}
    for d in drafts:
        b = d.get("brand", "unknown").replace("_", " ").title()
        brand_counts[b] = brand_counts.get(b, 0) + 1

    lines = [
        f"<b>⚡ KENSEI Content — Stage {stage}</b>",
        f"{today} | {len(drafts)} draft(s)",
        "",
    ]
    for brand, count in brand_counts.items():
        lines.append(f"• {brand}: {count}")

    if stage == 1:
        lines.append("")
        lines.append("<i>Reply <code>A:&lt;id&gt;</code> to approve  |  <code>R:&lt;id&gt;</code> to reject</i>")
    elif stage == 2:
        lines.append("")
        lines.append("<i>AI visuals generated for approved drafts. Ready to queue.</i>")

    return send_message("\n".join(lines))


def run_digest(dry_run: bool = False) -> bool:
    """Fetch pending drafts and deliver concise summary + HTML report."""
    drafts = list_drafts(status="draft")
    if not drafts:
        print("No pending drafts to deliver.")
        return False

    if dry_run:
        for d in drafts[:3]:
            print(f"  [DRY] {d['id']} [{d['brand']}/{d['platform']}] — {d['body_text'][:60]}...")
        return True

    # Concise summary to Telegram
    deliver_concise_summary(drafts, stage=1)

    # Full HTML report saved to disk
    html = generate_html_report(drafts, stage=1)
    report_path = save_html_report(html, stage=1)
    print(f"HTML report saved: {report_path}")

    # Send full HTML report as document
    from telegram_digest import send_document
    send_document(report_path, caption=f"<b>Full Content Report</b> ({len(drafts)} draft{'s' if len(drafts) != 1 else ''})")

    return True


def run_approval(draft_id: str, action: str) -> None:
    if action == "approve":
        approve_draft(draft_id)
        print(f"Approved {draft_id}")
        drafts = list_drafts(status="approved")
        for d in drafts:
            if d["id"] == draft_id:
                post_id = queue_post(
                    body_text=d["body_text"],
                    brand=d["brand"],
                    platform=d["platform"],
                    title=d.get("title"),
                )
                if post_id:
                    print(f"Queued in Postiz: {post_id}")
                else:
                    print(f"No Postiz integration for {d['brand']}/{d['platform']} — stored, not queued.")
                break
    elif action == "reject":
        reject_draft(draft_id)
        print(f"Rejected {draft_id}")
    else:
        print(f"Unknown action: {action}. Use 'approve' or 'reject'.")


def main() -> int:
    parser = argparse.ArgumentParser(description="KENSEI Content Engine — Two-Stage Pipeline")
    sub = parser.add_subparsers(dest="cmd")

    # Stage 1: text + static visuals (free)
    s1 = sub.add_parser("stage1", help="Stage 1: text drafts + static visuals (free)")
    s1.add_argument("--brand", "-b", nargs="+", default=list(BRANDS.keys()), help="Brand(s)")
    s1.add_argument("--platform", "-p", default=None)
    s1.add_argument("--dry-run", action="store_true")

    # Stage 2: AI images + videos for approved drafts only
    s2 = sub.add_parser("stage2", help="Stage 2: AI images + videos for APPROVED drafts (costs money)")
    s2.add_argument("--dry-run", action="store_true")

    # Legacy generate command (runs full pipeline)
    gen = sub.add_parser("generate", help="Full pipeline: stage1 + stage2 combined")
    gen.add_argument("--brand", "-b", nargs="+", default=list(BRANDS.keys()))
    gen.add_argument("--platform", "-p", default=None)
    gen.add_argument("--dry-run", action="store_true")

    dig = sub.add_parser("digest", help="Deliver Telegram digest of pending drafts")
    dig.add_argument("--dry-run", action="store_true")

    app = sub.add_parser("approve", help="Approve a draft by ID")
    app.add_argument("draft_id")

    rej = sub.add_parser("reject", help="Reject a draft by ID")
    rej.add_argument("draft_id")

    lst = sub.add_parser("list", help="List drafts by status")
    lst.add_argument("--status", "-s", default="draft", choices=["draft", "approved", "rejected", "published"])
    lst.add_argument("--brand", "-b", default=None)

    args = parser.parse_args()

    init_db()

    if args.cmd == "stage1":
        drafts = run_stage_1(args.brand, dry_run=args.dry_run, platform=args.platform)
        print(f"\nStage 1 complete: {len(drafts)} draft(s)")
        if not args.dry_run:
            deliver_concise_summary(drafts, stage=1)
            html = generate_html_report(drafts, stage=1)
            report_path = save_html_report(html, stage=1)
            print(f"Report: {report_path}")
        return 0

    elif args.cmd == "stage2":
        drafts = run_stage_2(dry_run=args.dry_run)
        print(f"\nStage 2 complete: {len(drafts)} draft(s) enriched with AI visuals")
        if not args.dry_run and drafts:
            deliver_concise_summary(drafts, stage=2)
            html = generate_html_report(drafts, stage=2)
            report_path = save_html_report(html, stage=2)
            print(f"Report: {report_path}")
        return 0

    elif args.cmd == "generate":
        drafts = run_stage_1(args.brand, dry_run=args.dry_run, platform=args.platform)
        print(f"\nStage 1: {len(drafts)} draft(s)")
        if not args.dry_run:
            approved = run_stage_2(dry_run=args.dry_run)
            print(f"Stage 2: {len(approved)} approved draft(s) enriched")
            deliver_concise_summary(drafts + approved, stage=2)
            html = generate_html_report(drafts + approved, stage=2)
            report_path = save_html_report(html, stage=2)
            print(f"Report: {report_path}")
        return 0

    elif args.cmd == "digest":
        ok = run_digest(dry_run=args.dry_run)
        return 0 if ok else 1

    elif args.cmd == "approve":
        run_approval(args.draft_id, "approve")
        return 0

    elif args.cmd == "reject":
        run_approval(args.draft_id, "reject")
        return 0

    elif args.cmd == "list":
        drafts = list_drafts(status=args.status, brand=args.brand)
        print(f"{len(drafts)} draft(s) with status '{args.status}':")
        for d in drafts:
            print(f"  {d['id']} | {d['brand']} | {d['platform']} | {d['body_text'][:60]}...")
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
