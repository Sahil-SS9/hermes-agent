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

def get_recent_prs(repo):
    """Fetch recent PRs by tracked authors only."""
    result = subprocess.run(
        ["gh", "pr", "list", "--repo", repo, "--state", "all",
         "--json", "number,title,state,author,createdAt,updatedAt,mergedAt,closedAt,url,labels,comments,reviews",
         "--limit", "50"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        print(f"ERROR: gh pr list failed for {repo}: {result.stderr}", file=sys.stderr)
        return []
    all_prs = json.loads(result.stdout)
    # Only track PRs by Sahil-SS9 — everyone else's PRs are noise
    tracked = [pr for pr in all_prs if pr.get("author", {}).get("login") in TRACKED_AUTHORS]
    return tracked

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
            labels = [l["name"] for l in issue.get("labels", [])]
            priority = "P1" if "P1" in labels else ("P2" if "P2" in labels else "P3")
            seen[key] = {"number": num, "title": issue["title"], "classification": classification, "priority": priority, "url": issue["url"], "seen_at": now}
            new_issues.append({"repo": repo, "number": num, "title": issue["title"], "classification": classification, "priority": priority, "url": issue["url"]})

        state["seen_issues"][repo] = seen

        # Check PR activity
        pr_activity.extend(check_pr_activity(repo, state))

    state["last_checked"] = now
    save_state(state)

    # Output
    output_lines = []
    if new_issues:
        output_lines.append(f"New issues ({len(new_issues)}):")
        for iss in new_issues:
            output_lines.append(f"  [{iss['classification']}] {iss['repo']}#{iss['number']}: {iss['title']}")
            output_lines.append(f"    {iss['url']}  Priority: {iss['priority']}")

    if pr_activity:
        if new_issues:
            output_lines.append("")
        output_lines.append(f"PR activity ({len(pr_activity)}):")
        for a in pr_activity:
            if a["type"] == "new_pr":
                output_lines.append(f"  [NEW PR] {a['repo']}#{a['number']} by {a['author']}: {a['title']}")
                output_lines.append(f"    {a['url']}  Priority: {a['priority']}")
            elif a["type"] == "merged_pr":
                output_lines.append(f"  [MERGED] {a['repo']}#{a['number']} by {a['author']}: {a['title']}")
                output_lines.append(f"    {a['url']}")
            elif a["type"] == "closed_pr":
                output_lines.append(f"  [CLOSED] {a['repo']}#{a['number']}: {a['title']}")
                output_lines.append(f"    {a['url']}")
            elif a["type"] == "pr_activity":
                parts = []
                if a["new_comments"] > 0:
                    parts.append(f"{a['new_comments']} new comment(s)")
                if a["new_reviews"] > 0:
                    parts.append(f"{a['new_reviews']} new review(s)")
                output_lines.append(f"  [ACTIVITY] {a['repo']}#{a['number']}: {', '.join(parts)}")
                output_lines.append(f"    {a['title']}")
                output_lines.append(f"    {a['url']}")

    if output_lines:
        print("\n".join(output_lines))

if __name__ == "__main__":
    main()
