#!/usr/bin/env python3
"""
Moss Repo Scanner — scans Sahil's public repos for fix opportunities.
Inspired by P0/P1 PR patterns from NousResearch/hermes-agent.

Runs as a no_agent cron script. Outputs findings for delivery.

P0/P1 patterns observed:
- Auth credential write-through (multi-profile rotation)
- Nix dependency fixes
- Gateway command-line matcher hardening
- SQLite trigram tokenizer fallback
- Model picker caps
- Session message preservation
- Custom provider persistence
- Skill rmtree scope guard
- CUA environment scrubbing
- Curator snapshot pruning
- Docker gateway takeover
- Stale lock eviction
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

REPORT_FILE = os.path.expanduser("~/.hermes/data/moss-repo-scan.json")
TARGET_REPOS = [
    "Sahil-SS9/hermes-agent",       # Public fork
    "Sahil-SS9/GitRadar-Self-Improvement",
    "Sahil-SS9/hermes-memlock",
    "Sahil-SS9/hermaguard",
    "Sahil-SS9/Toolaria",
    "Sahil-SS9/hermes-multichannel-prompt-optimizer",
    "Sahil-SS9/mnemosyne",
    "Sahil-SS9/hermes-simplify-swarm",
    "Sahil-SS9/MrHermagi-tutorbot",
    "Sahil-SS9/hermes-Custom-CLI-Themes",
]

def run_gh(repo, cmd):
    """Run a gh command against a repo."""
    result = subprocess.run(
        ["gh", cmd, "--repo", repo, "--state", "open",
         "--json", "number,title,labels,createdAt,url",
         "--limit", "20"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return []
    return json.loads(result.stdout)

def check_repo_health(repo):
    """Basic health check on a repo."""
    findings = []

    # Check for open issues without labels
    issues = run_gh(repo, "issue")
    unlabelled = [i for i in issues if not i.get("labels")]
    if unlabelled:
        findings.append({
            "type": "unlabelled_issues",
            "count": len(unlabelled),
            "items": [f"#{i['number']}: {i['title']}" for i in unlabelled[:5]],
        })

    # Check for stale issues (no activity, needs-triage)
    needs_triage = [i for i in issues if any(l["name"] == "needs-triage" for l in i.get("labels", []))]
    if needs_triage:
        findings.append({
            "type": "needs_triage",
            "count": len(needs_triage),
            "items": [f"#{i['number']}: {i['title']}" for i in needs_triage[:5]],
        })

    return findings

def scan_for_common_issues(repo):
    """Scan repo for common fix patterns."""
    findings = []

    # Clone or fetch the repo
    clone_dir = f"/tmp/moss-scan-{repo.replace('/', '-')}"
    if not os.path.exists(clone_dir):
        result = subprocess.run(
            ["git", "clone", f"https://github.com/{repo}.git", clone_dir],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            return [{"type": "clone_failed", "detail": result.stderr[:200]}]

    # Fetch latest
    subprocess.run(["git", "-C", clone_dir, "fetch", "origin"], capture_output=True, timeout=30)
    subprocess.run(["git", "-C", clone_dir, "checkout", "main"], capture_output=True, timeout=10)

    # Pattern 1: Check for hardcoded values that should be configurable
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py", "--include=*.ts", "--include=*.tsx",
         "max_models=50\\|timeout=120\\|max_iterations=25", clone_dir],
        capture_output=True, text=True, timeout=30
    )
    if result.stdout.strip():
        lines = result.stdout.strip().split("\n")[:5]
        findings.append({
            "type": "hardcoded_constants",
            "count": len(result.stdout.strip().split("\n")),
            "items": [l.replace(clone_dir + "/", "") for l in lines],
        })

    # Pattern 2: Check for bare except: pass
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py", "except:.*pass\\|except: *\\n.*pass", clone_dir],
        capture_output=True, text=True, timeout=30
    )
    if result.stdout.strip():
        lines = result.stdout.strip().split("\n")[:5]
        findings.append({
            "type": "bare_except_pass",
            "count": len(result.stdout.strip().split("\n")),
            "items": [l.replace(clone_dir + "/", "") for l in lines],
        })

    # Pattern 3: Check for TODO/FIXME comments
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py", "--include=*.ts", "--include=*.tsx",
         "TODO\\|FIXME\\|HACK\\|XXX", clone_dir],
        capture_output=True, text=True, timeout=30
    )
    if result.stdout.strip():
        lines = result.stdout.strip().split("\n")[:5]
        findings.append({
            "type": "todo_fixme",
            "count": len(result.stdout.strip().split("\n")),
            "items": [l.replace(clone_dir + "/", "") for l in lines],
        })

    # Pattern 4: Check for missing type hints in function signatures
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py", "^def [^(]*([^)]*):$", clone_dir],
        capture_output=True, text=True, timeout=30
    )
    if result.stdout.strip():
        lines = result.stdout.strip().split("\n")[:5]
        findings.append({
            "type": "missing_type_hints",
            "count": len(result.stdout.strip().split("\n")),
            "items": [l.replace(clone_dir + "/", "") for l in lines],
        })

    # Pattern 5: Check for print() statements in production code
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py", "^[^#]*print(", clone_dir],
        capture_output=True, text=True, timeout=30
    )
    if result.stdout.strip():
        lines = result.stdout.strip().split("\n")[:5]
        findings.append({
            "type": "print_statements",
            "count": len(result.stdout.strip().split("\n")),
            "items": [l.replace(clone_dir + "/", "") for l in lines],
        })

    # Cleanup
    subprocess.run(["rm", "-rf", clone_dir], capture_output=True, timeout=10)

    return findings

def main():
    now = datetime.now(timezone.utc).isoformat()
    all_findings = {}

    for repo in TARGET_REPOS:
        repo_findings = []

        # Check repo health
        health = check_repo_health(repo)
        if health:
            repo_findings.extend(health)

        # Scan for common issues
        scan = scan_for_common_issues(repo)
        if scan:
            repo_findings.extend(scan)

        if repo_findings:
            all_findings[repo] = repo_findings

    # Save report
    report = {
        "last_scan": now,
        "findings": all_findings,
    }
    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)

    # Output for delivery
    if all_findings:
        total = sum(len(v) for v in all_findings.values())
        print(f"Moss repo scan: {total} findings across {len(all_findings)} repos")
        for repo, findings in all_findings.items():
            print(f"\n{repo}:")
            for f in findings:
                print(f"  [{f['type']}] {f['count']} occurrences")
                for item in f.get('items', [])[:3]:
                    print(f"    {item}")
    else:
        # Silent — nothing to report
        pass

if __name__ == "__main__":
    main()
