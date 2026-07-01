#!/usr/bin/env python3
"""
Mossy branch cleanup checker — scans the upstream repo for fix/ branches
whose associated issues are CLOSED or MERGED, and reports cleanup candidates.

Read-only: does NOT delete anything. Only flags branches for Sahil's approval.

Runs daily, delivers to #build-log.
Silent when no cleanup candidates exist.
"""
import subprocess, json, sys, os
from pathlib import Path
from datetime import datetime, timedelta

REPO = Path("/home/kensei/repos/hermes-agent-upstream")
DAYS_STALE = 14  # branches with no commits in 14 days + closed issue = cleanup candidate

def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=REPO)
        return r.stdout.strip() if r.returncode == 0 else None
    except:
        return None

def get_branches():
    """Get all local fix/ branches with their last commit date."""
    raw = run("git for-each-ref --format='%(refname:short)|%(committerdate:short)' refs/heads/fix/")
    if not raw:
        return []
    branches = []
    for line in raw.strip().split("\n"):
        parts = line.split("|")
        if len(parts) == 2:
            branches.append({"name": parts[0], "last_commit": parts[1]})
    return branches

def get_issue_status(issue_num):
    """Check if an issue is closed and whether it has closing PRs."""
    state = run(f"gh issue view {issue_num} --repo NousResearch/hermes-agent --json state --jq '.state' 2>/dev/null")
    closing_prs = run(f"gh issue view {issue_num} --repo NousResearch/hermes-agent --json closedByPullRequestsReferences --jq '.closedByPullRequestsReferences.totalCount' 2>/dev/null")
    return {
        "state": state or "UNKNOWN",
        "closing_prs": int(closing_prs) if closing_prs and closing_prs.isdigit() else 0
    }

def check_branch_merged(branch):
    """Check if the branch is merged into main."""
    result = run(f"git branch --merged main --format='%(refname:short)' | grep -Fx '{branch}'")
    return result is not None and result.strip() == branch

def main():
    if not REPO.exists():
        return 0  # silent — repo doesn't exist

    branches = get_branches()
    if not branches:
        return 0  # silent — no fix branches

    candidates = []
    stale_cutoff = (datetime.now() - timedelta(days=DAYS_STALE)).strftime("%Y-%m-%d")

    for branch in branches:
        name = branch["name"]
        last_commit = branch["last_commit"]

        # Extract issue number from branch name
        import re
        match = re.search(r'issue-(\d+)', name)
        if not match:
            continue
        issue_num = match.group(1)

        # Check if branch is merged into main
        is_merged = check_branch_merged(name)

        # Check issue status
        issue = get_issue_status(issue_num)

        # Determine if this is a cleanup candidate
        reasons = []
        if is_merged:
            reasons.append("branch merged into main")
        if issue["state"] == "CLOSED":
            reasons.append(f"issue #{issue_num} closed")
            if issue["closing_prs"] > 0:
                reasons.append(f"closed by {issue['closing_prs']} PR(s)")
        if last_commit < stale_cutoff and issue["state"] == "CLOSED":
            reasons.append(f"stale (last commit {last_commit})")

        if reasons:
            candidates.append({
                "branch": name,
                "issue": issue_num,
                "issue_state": issue["state"],
                "merged": is_merged,
                "last_commit": last_commit,
                "reasons": reasons
            })

    if not candidates:
        return 0  # silent — no cleanup candidates

    # Output cleanup candidates
    print(f"Branch cleanup: {len(candidates)} candidate(s) for deletion")
    for c in candidates:
        status = "MERGED" if c["merged"] else f"issue {c['issue_state']}"
        print(f"  {c['branch']} ({status}, last commit {c['last_commit']})")
        for r in c["reasons"]:
            print(f"    — {r}")
    print(f"\nReply with 'delete <branch>' to approve deletion. Branches are NOT auto-deleted.")

    return 0

if __name__ == "__main__":
    sys.exit(main())