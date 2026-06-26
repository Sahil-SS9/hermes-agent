#!/usr/bin/env python3
"""
Moss Issue & PR Watcher — polls GitHub for new issues AND PR activity
on target repos. Tracks submissions, comments, merges, and status changes.

Runs as a no_agent cron script. Outputs new activity for delivery.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

STATE_FILE = os.path.expanduser("~/.hermes/data/moss-issue-watch.json")
FIX_QUEUE_FILE = os.path.expanduser("~/.hermes/data/moss-fix-queue.json")
MAX_QUEUE_SIZE = 20
TARGET_REPOS = [
    "NousResearch/hermes-agent",
]
TRACKED_AUTHORS = [
    "Sahil-SS9",
]

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            state = json.load(f)
            # Migrate from old format (no seen_prs)
            if "seen_prs" not in state:
                state["seen_prs"] = {}
            return state
    return {"last_checked": None, "seen_issues": {}, "seen_prs": {}}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def get_open_issues(repo):
    result = subprocess.run(
        ["gh", "issue", "list", "--repo", repo, "--state", "open",
         "--json", "number,title,labels,createdAt,url,body",
         "--limit", "30"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        print(f"ERROR: gh issue list failed for {repo}: {result.stderr}", file=sys.stderr)
        return []
    return json.loads(result.stdout)

def classify_issue(issue):
    labels = [l["name"] for l in issue.get("labels", [])]
    body = issue.get("body", "").lower()
    if "type/feature" in labels and len(body) < 100:
        return None
    if "type/bug" in labels:
        return "bug"
    if "type/security" in labels:
        return "security"
    if "needs-repro" in labels:
        if "steps to reproduce" in body or "reproduction" in body:
            return "bug"
        return None
    return None

def has_linked_pr(repo, issue_number):
    """Check if an issue already has a closing PR reference (linked or merged).

    Returns True if a PR exists that references this issue, False otherwise.
    """
    # 1. Check via gh issue view for closing PR references
    result = subprocess.run(
        ["gh", "issue", "view", str(issue_number), "--repo", repo,
         "--json", "closedByPullRequestsReferences"],
        capture_output=True, text=True, timeout=15
    )
    if result.returncode == 0:
        data = json.loads(result.stdout)
        refs = data.get("closedByPullRequestsReferences", {})
        if refs.get("totalCount", 0) > 0:
            return True

    # 2. Search for open PRs that reference this issue number
    search_result = subprocess.run(
        ["gh", "search", "prs", f"repo:{repo}", "is:open", f"\"#{issue_number}\"",
         "--json", "number,title,state", "--limit", "10"],
        capture_output=True, text=True, timeout=15
    )
    if search_result.returncode == 0:
        prs = json.loads(search_result.stdout)
        for pr in prs:
            title = pr.get("title", "")
            if f"#{issue_number}" in title:
                return True

    return False

def get_recent_prs(repo):
    """Fetch recent PRs by tracked authors only. Uses --author filter at the API level."""
    tracked = []
    for author in TRACKED_AUTHORS:
        result = subprocess.run(
            ["gh", "pr", "list", "--repo", repo, "--state", "all", "--author", author,
             "--json", "number,title,state,author,createdAt,updatedAt,mergedAt,closedAt,url,labels,comments,reviews",
             "--limit", "50"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            print(f"ERROR: gh pr list failed for {repo} author {author}: {result.stderr}", file=sys.stderr)
            continue
        tracked.extend(json.loads(result.stdout))
    return tracked

def get_all_open_prs(repo):
    """Return all currently OPEN PRs by tracked authors (no state tracking, just snapshot)."""
    open_prs = []
    for author in TRACKED_AUTHORS:
        result = subprocess.run(
            ["gh", "pr", "list", "--repo", repo, "--state", "open", "--author", author,
             "--json", "number,title,createdAt,url,labels,headRefName",
             "--limit", "50"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            open_prs.extend(json.loads(result.stdout))
    return open_prs

def check_pr_activity(repo, state):
    """Check for new or updated PRs and return activity report."""
    prs = get_recent_prs(repo)
    seen = state["seen_prs"].get(repo, {})
    now = datetime.now(timezone.utc).isoformat()
    activity = []

    for pr in prs:
        num = pr["number"]
        key = str(num)
        prev = seen.get(key)

        if prev is None:
            # New PR — never seen before
            if pr["state"] == "OPEN":
                labels = [l["name"] for l in pr.get("labels", [])]
                priority = "P1" if "P1" in labels else ("P2" if "P2" in labels else "P3")
                activity.append({
                    "type": "new_pr",
                    "repo": repo,
                    "number": num,
                    "title": pr["title"],
                    "author": pr["author"]["login"],
                    "priority": priority,
                    "url": pr["url"],
                })
                seen[key] = {
                    "number": num,
                    "title": pr["title"],
                    "state": pr["state"],
                    "last_comment_count": len(pr.get("comments", [])),
                    "last_review_count": len(pr.get("reviews", [])),
                    "seen_at": now,
                }
            elif pr["state"] == "MERGED":
                activity.append({
                    "type": "merged_pr",
                    "repo": repo,
                    "number": num,
                    "title": pr["title"],
                    "author": pr["author"]["login"],
                    "url": pr["url"],
                })
                seen[key] = {
                    "number": num,
                    "title": pr["title"],
                    "state": "MERGED",
                    "seen_at": now,
                }
            else:
                seen[key] = {
                    "number": num,
                    "title": pr["title"],
                    "state": pr["state"],
                    "seen_at": now,
                }
        elif prev["state"] != pr["state"]:
            # State change — e.g. OPEN → MERGED
            if pr["state"] == "MERGED":
                activity.append({
                    "type": "merged_pr",
                    "repo": repo,
                    "number": num,
                    "title": pr["title"],
                    "author": pr["author"]["login"],
                    "url": pr["url"],
                })
            elif pr["state"] == "CLOSED":
                activity.append({
                    "type": "closed_pr",
                    "repo": repo,
                    "number": num,
                    "title": pr["title"],
                    "url": pr["url"],
                })
            seen[key]["state"] = pr["state"]
            seen[key]["seen_at"] = now
        elif pr["state"] == "OPEN" and prev["state"] == "OPEN":
            # Check for new comments or reviews using list response counts
            current_comments = len(pr.get("comments", []))
            current_reviews = len(pr.get("reviews", []))
            prev_comments = prev.get("last_comment_count", 0)
            prev_reviews = prev.get("last_review_count", 0)

            new_comments = current_comments - prev_comments
            new_reviews = current_reviews - prev_reviews

            if new_comments > 0 or new_reviews > 0:
                activity.append({
                    "type": "pr_activity",
                    "repo": repo,
                    "number": num,
                    "title": pr["title"],
                    "new_comments": new_comments,
                    "new_reviews": new_reviews,
                    "url": pr["url"],
                })
                seen[key]["last_comment_count"] = current_comments
                seen[key]["last_review_count"] = current_reviews
                seen[key]["seen_at"] = now

    state["seen_prs"][repo] = seen
    return activity

def main():
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()
    new_issues = []
    pr_activity = []
    all_open_prs = []

    for repo in TARGET_REPOS:
        # Check issues
        issues = get_open_issues(repo)
        seen = state["seen_issues"].get(repo, {})

        for issue in issues:
            num = issue["number"]
            key = str(num)
            if key in seen:
                continue
            classification = classify_issue(issue)
            if classification is None:
                seen[key] = {"number": num, "title": issue["title"], "classification": "skipped", "seen_at": now}
                continue
            # Skip issues that already have a linked or open PR — prevents
            # the fix-pipeline from queuing issues that someone already
            # addressed (the pipeline prompt says "skip any issue with an
            # existing open PR by anyone" but the gate was text-only, not
            # enforced programmatically. This is the programmatic gate.)
            if has_linked_pr(repo, num):
                seen[key] = {"number": num, "title": issue["title"], "classification": "has_pr", "seen_at": now}
                continue
            labels = [l["name"] for l in issue.get("labels", [])]
            priority = "P1" if "P1" in labels else ("P2" if "P2" in labels else "P3")
            seen[key] = {"number": num, "title": issue["title"], "classification": classification, "priority": priority, "url": issue["url"], "seen_at": now}
            new_issues.append({"repo": repo, "number": num, "title": issue["title"], "classification": classification, "priority": priority, "url": issue["url"]})

        state["seen_issues"][repo] = seen

        # Check PR activity
        pr_activity.extend(check_pr_activity(repo, state))

        # Collect all currently open PRs (for the report)
        all_open_prs.extend(get_all_open_prs(repo))

    state["last_checked"] = now
    save_state(state)

    # Output — short Discord body + HTML attachment
    output_lines = []
    html_parts = []

    # Write fixable bugs to pipeline queue
    fixable = [iss for iss in new_issues if iss["classification"] == "bug" and iss["priority"] in ("P1", "P2")]
    if fixable:
        queue_state = {"updated_at": now, "pending": []}
        if os.path.exists(FIX_QUEUE_FILE):
            try:
                with open(FIX_QUEUE_FILE) as f:
                    existing = json.load(f)
                    queue_state["pending"] = existing.get("pending", [])
            except (json.JSONDecodeError, OSError):
                pass
        existing_keys = {f"{i['repo']}#{i['number']}" for i in queue_state["pending"]}
        for iss in fixable:
            key = f"{iss['repo']}#{iss['number']}"
            if key not in existing_keys and len(queue_state["pending"]) < MAX_QUEUE_SIZE:
                queue_state["pending"].append(iss)
                existing_keys.add(key)
        with open(FIX_QUEUE_FILE, "w") as f:
            json.dump(queue_state, f, indent=2)

    # Only output on PR activity — new issues silently populate the fix queue
    if pr_activity:
        # Discord body — PR activity only, no issue counts
        parts = []
        pr_count = len([a for a in pr_activity if a["type"] in ("new_pr", "merged_pr", "closed_pr")])
        if pr_count:
            parts.append(f"{pr_count} PR updates")
        output_lines.append(" · ".join(parts))

        # Build HTML report
        def esc(s):
            return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;")

        html_parts.append(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mossy Issue Watch · {now[:10]}</title>
<style>
:root {{ color-scheme:dark; --bg:#0f1115; --card:#181b22; --line:#2a2f3a; --text:#e7e3d8; --muted:#8e96a6; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.55 system-ui,-apple-system,sans-serif; }}
main {{ width:min(900px,calc(100%-32px)); margin:0 auto; padding:28px 0 56px; }}
h1 {{ margin:0 0 2px; font-size:24px; letter-spacing:-.02em; }}
.sub {{ color:var(--muted); margin:0 0 24px; }}
.pills {{ display:flex; gap:10px; flex-wrap:wrap; margin:14px 0 20px; }}
.pill {{ background:var(--card); border:1px solid var(--line); border-radius:999px; padding:5px 11px; font-size:13px; font-variant-numeric:tabular-nums; }}
section {{ background:var(--card); border:1px solid var(--line); border-radius:12px; margin:16px 0; overflow:hidden; }}
h2 {{ font-size:16px; margin:0; padding:14px 16px; border-bottom:1px solid var(--line); }}
table {{ width:100%; border-collapse:collapse; }}
th {{ text-align:left; padding:10px 16px; font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; border-bottom:1px solid var(--line); }}
td {{ padding:10px 16px; border-bottom:1px solid var(--line); vertical-align:top; font-size:13px; }}
td:last-child, th:last-child {{ text-align:right; }}
a {{ color:#5b8def; text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
.tag {{ display:inline-block; padding:1px 7px; border-radius:4px; font-size:11px; font-weight:600; }}
.tag-bug {{ background:#401510; color:#e0584c; }}
.tag-sec {{ background:#152040; color:#5b8def; }}
.tag-P1 {{ background:#401510; color:#e0584c; }}
.tag-P2 {{ background:#402e10; color:#e0982e; }}
.tag-P3 {{ background:#152040; color:#5b8def; }}
.tag-new {{ background:#0c3d2e; color:#46b39a; }}
.tag-merged {{ background:#0c3d2e; color:#46b39a; }}
.tag-closed {{ background:#2a2f3a; color:#8e96a6; }}
</style></head><body>
<main>
<h1>Mossy Issue Watch</h1>
<p class="sub">{now[:19].replace("T", " ")}</p>
<div class="pills">""")

        if new_issues:
            p1 = sum(1 for iss in new_issues if iss["priority"] == "P1")
            p2 = sum(1 for iss in new_issues if iss["priority"] == "P2")
            p3 = sum(1 for iss in new_issues if iss["priority"] == "P3")
            html_parts.append(f"""<span class="pill">📋 <b>{len(new_issues)}</b> new issues</span>""")
            if p1: html_parts.append(f"""<span class="pill">🔴 P1 <b>{p1}</b></span>""")
            if p2: html_parts.append(f"""<span class="pill">🟡 P2 <b>{p2}</b></span>""")
            if p3: html_parts.append(f"""<span class="pill">⚪ P3 <b>{p3}</b></span>""")

        if pr_activity:
            new_prs = sum(1 for a in pr_activity if a["type"] == "new_pr")
            merged = sum(1 for a in pr_activity if a["type"] == "merged_pr")
            closed = sum(1 for a in pr_activity if a["type"] == "closed_pr")
            activity_count = sum(1 for a in pr_activity if a["type"] == "pr_activity")
            if new_prs: html_parts.append(f"""<span class="pill">🆕 <b>{new_prs}</b> new PRs</span>""")
            if merged: html_parts.append(f"""<span class="pill">✅ <b>{merged}</b> merged</span>""")
            if closed: html_parts.append(f"""<span class="pill">❌ <b>{closed}</b> closed</span>""")
            if activity_count: html_parts.append(f"""<span class="pill">💬 <b>{activity_count}</b> with activity</span>""")

        html_parts.append("</div>")

        # Issues table
        if new_issues:
            html_parts.append("""<section><h2>New Issues</h2><table><thead><tr><th>Issue</th><th>Title</th><th></th></tr></thead><tbody>""")
            for iss in new_issues:
                cls = "bug" if iss["classification"] == "bug" else "sec"
                tag_line = f"<span class='tag tag-{cls}'>{iss['classification']}</span> <span class='tag tag-{iss['priority']}'>{iss['priority']}</span>"
                html_parts.append(f"""<tr><td><a href="{esc(iss['url'])}">{esc(iss['repo'])}#{iss['number']}</a></td><td>{esc(iss['title'][:80])}</td><td>{tag_line}</td></tr>""")
            html_parts.append("</tbody></table></section>")

        # PR activity table
        if pr_activity:
            html_parts.append("""<section><h2>PR Activity</h2><table><thead><tr><th>PR</th><th>Title</th><th></th></tr></thead><tbody>""")
            for a in pr_activity:
                if a["type"] == "new_pr":
                    tag = "<span class='tag tag-new'>NEW</span>"
                    suffix = f"by {esc(a.get('author',''))}"
                elif a["type"] == "merged_pr":
                    tag = "<span class='tag tag-merged'>MERGED</span>"
                    suffix = f"by {esc(a.get('author',''))}"
                elif a["type"] == "closed_pr":
                    tag = "<span class='tag tag-closed'>CLOSED</span>"
                    suffix = ""
                elif a["type"] == "pr_activity":
                    parts = []
                    if a["new_comments"] > 0: parts.append(f"{a['new_comments']} comments")
                    if a["new_reviews"] > 0: parts.append(f"{a['new_reviews']} reviews")
                    tag = "<span class='tag tag-new'>💬</span>"
                    suffix = " · ".join(parts)
                else:
                    tag, suffix = "", ""
                html_parts.append(f"""<tr><td><a href="{esc(a['url'])}">{esc(a['repo'])}#{a['number']}</a></td><td>{esc(a['title'][:70])}</td><td>{tag} {esc(suffix)}</td></tr>""")
            html_parts.append("</tbody></table></section>")

        # All Open PRs section (always shown when PRs exist)
        if all_open_prs:
            html_parts.append("""<section><h2>All Open PRs</h2><table><thead><tr><th>PR</th><th>Title</th><th>Opened</th></tr></thead><tbody>""")
            for pr in sorted(all_open_prs, key=lambda p: p.get("createdAt", "")):
                created = pr.get("createdAt", "")[:10]
                labels = [l["name"] for l in pr.get("labels", [])]
                priority = "P1" if "P1" in labels else ("P2" if "P2" in labels else "P3")
                pri_tag = f"<span class='tag tag-{priority}'>{priority}</span>"
                html_parts.append(f"""<tr><td><a href="{esc(pr['url'])}">{esc(pr.get('repo','NousResearch/hermes-agent'))}#{pr['number']}</a></td><td>{esc(pr['title'][:80])}</td><td>{esc(created)} {pri_tag}</td></tr>""")
            html_parts.append("</tbody></table></section>")

        html_parts.append("</main></body></html>")

        # Write HTML report
        report_dir = os.path.expanduser("~/.hermes/cron/output/moss-watch-reports")
        os.makedirs(report_dir, exist_ok=True)
        report_path = os.path.join(report_dir, f"moss-watch-{now[:10]}.html")
        with open(report_path, "w") as f:
            f.write("\n".join(html_parts))

        # Final output: short Discord body + MEDIA tag
        print("\n".join(output_lines))
        print(f"MEDIA:{report_path}")

if __name__ == "__main__":
    main()
