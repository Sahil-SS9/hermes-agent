"""Activity collector — gathers real signals for autobiographical content.

Feeds into topics.py and llm_drafts.py so Sahil's personal Twitter/LinkedIn
content is about what he actually did, contributed, discovered, or architected.

Signal types:
  - github_push       → repos pushed/created recently
  - hermes_pr         → upstream Hermes Agent PRs submitted
  - hermes_skill      → new/modified skills in ~/.hermes/skills/
  - research_tool     → tool/model releases from research digest
  - research_signal   → data points/trends from research digest
  - gitradar_repo     → interesting repos from github-radar
  - architecture      → evergreen content about KENSEI's architecture
"""

import json
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
STATE_FILE = DATA_DIR / "activity_state.json"
HERMES_HOME = Path(os.path.expanduser("~/.hermes"))
RUNBOOKS_DIR = HERMES_HOME / "runbooks"

# How long to wait before a used signal can be repeated (days)
SIGNAL_REPEAT_TTL_DAYS = 7

# Max signals of each type per run
MAX_PER_TYPE = {
    "github_push": 2,
    "hermes_pr": 2,
    "hermes_skill": 1,
    "research_tool": 2,
    "research_signal": 1,
    "gitradar_repo": 2,
    "architecture": 1,
    "harness_change": 2,
}


def _ensure_state():
    """Load or create state file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        default = {
            "used_signals": [],
            "last_run": None,
            "cycle_signals": {},
        }
        STATE_FILE.write_text(json.dumps(default, indent=2))
        return default
    return json.loads(STATE_FILE.read_text())


def _save_state(state: dict):
    """Persist state file."""
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def _is_used(state: dict, signal_id: str) -> bool:
    """Check if a signal was already used (within TTL)."""
    used = state.get("used_signals", [])
    # used entries can be string signal_id or dict with {id, timestamp}
    ids = {u["id"] if isinstance(u, dict) else u for u in used}
    return signal_id in ids


def _mark_used(state: dict, signal_id: str):
    """Mark a signal as used."""
    used = state.setdefault("used_signals", [])
    used.append({"id": signal_id, "used_at": datetime.now(timezone.utc).isoformat()})
    _prune_stale(state)


def _prune_stale(state: dict):
    """Remove signals older than TTL from used list."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=SIGNAL_REPEAT_TTL_DAYS)
    used = state.get("used_signals", [])
    fresh = []
    for u in used:
        if isinstance(u, dict):
            ts = u.get("used_at", "")
            if ts and datetime.fromisoformat(ts) > cutoff:
                fresh.append(u)
        else:
            fresh.append(u)
    state["used_signals"] = fresh


def _run_gh(args: list[str]) -> list[dict]:
    """Run gh CLI and return parsed JSON output."""
    try:
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return []
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return []


def collect_github_pushes(state: dict) -> list[dict]:
    """Collect recently pushed/created repos."""
    signals = []

    # Get owner repos, sorted by updatedAt
    repos = _run_gh(["repo", "list", "--limit", "20", "--json",
                      "name", "owner", "description", "primaryLanguage",
                      "updatedAt", "url"])
    if not repos:
        return signals

    # Filter to Sahil's own repos and sort by most recently updated
    own_repos = [r for r in repos if r.get("owner", {}).get("login") == "Sahil-SS9"]
    # Exclude repos that haven't been touched in 30 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    for repo in own_repos:
        updated = repo.get("updatedAt", "")
        if updated:
            try:
                updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                if updated_dt < cutoff:
                    continue
            except ValueError:
                pass

        signal_id = f"gh-push:{repo['name']}"
        if _is_used(state, signal_id):
            continue

        lang = repo.get("primaryLanguage", {}).get("name", "") if repo.get("primaryLanguage") else ""
        signals.append({
            "signal_id": signal_id,
            "signal_type": "github_push",
            "pillar": "build_in_public",
            "priority": 8,
            "freshness_hours": 72,
            "variables": {
                "repo_name": repo["name"],
                "description": repo.get("description", "") or "",
                "language": lang,
                "url": repo.get("url", ""),
            },
        })
        if len(signals) >= MAX_PER_TYPE["github_push"]:
            break

    return signals


def collect_hermes_prs(state: dict) -> list[dict]:
    """Collect upstream Hermes Agent PRs by Sahil."""
    signals = []

    # Get open PRs
    prs = _run_gh([
        "pr", "list", "--repo", "NousResearch/hermes-agent",
        "--author", "Sahil-SS9",
        "--state", "all",
        "--limit", "10",
        "--json", "title,state,createdAt,url,headRepository",
    ])

    if not prs:
        return signals

    for pr in prs:
        signal_id = f"hermes-pr:{pr['url']}"
        if _is_used(state, signal_id):
            continue

        repo_name = ""
        head_repo = pr.get("headRepository")
        if head_repo and isinstance(head_repo, dict):
            repo_name = head_repo.get("name", "hermes-agent")

        signals.append({
            "signal_id": signal_id,
            "signal_type": "hermes_pr",
            "pillar": "build_in_public",
            "priority": 9,
            "freshness_hours": 168,
            "variables": {
                "pr_title": pr["title"],
                "pr_summary": pr["title"][:120],  # use title as summary
                "upstream_repo": repo_name,
                "status": pr["state"].lower(),
                "url": pr["url"],
            },
        })
        if len(signals) >= MAX_PER_TYPE["hermes_pr"]:
            break

    return signals


def collect_hermes_skills(state: dict) -> list[dict]:
    """Detect recently added/modified skills."""
    signals = []
    skills_dir = HERMES_HOME / "skills"

    if not skills_dir.exists():
        return signals

    now = time.time()
    cutoff = now - (7 * 86400)  # 7 days

    try:
        skill_dirs = [d for d in skills_dir.iterdir() if d.is_dir()]
    except OSError:
        return signals

    recent = []
    for sd in skill_dirs:
        skill_md = sd / "SKILL.md"
        if skill_md.exists():
            mtime = skill_md.stat().st_mtime
            if mtime > cutoff:
                recent.append((sd.name, mtime))

    if not recent:
        return signals

    # Sort most recent first
    recent.sort(key=lambda x: x[1], reverse=True)

    for skill_name, _ in recent[:MAX_PER_TYPE["hermes_skill"]]:
        signal_id = f"hermes-skill:{skill_name}"
        if _is_used(state, signal_id):
            continue

        signals.append({
            "signal_id": signal_id,
            "signal_type": "hermes_skill",
            "pillar": "ai_tools",
            "priority": 7,
            "freshness_hours": 168,
            "variables": {
                "skill_name": skill_name,
            },
        })

    return signals


def _extract_research_digest() -> list[dict]:
    """Read the latest research digest HTML and extract items."""
    items = []

    rd_dir = RUNBOOKS_DIR / "research-digest"
    if not rd_dir.exists():
        return items

    # Find most recent HTML file
    html_files = sorted(rd_dir.glob("research-brief-*.html"), reverse=True)
    if not html_files:
        return items

    try:
        html = html_files[0].read_text(encoding="utf-8")
    except OSError:
        return items

    # Extract item blocks: class="item-title" -> text, class="item-summary" -> text
    title_matches = re.findall(
        r'<div class="item-title">(.*?)</div>', html, re.DOTALL
    )
    summary_matches = re.findall(
        r'<div class="item-summary">(.*?)</div>', html, re.DOTALL
    )

    # Determine which section each item belongs to
    # Use <section class= to avoid matching CSS style blocks
    news_pos = html.find('<section class="news"')
    tools_pos = html.find('<section class="tools"')
    signal_pos = html.find('<section class="signal"')

    for i, title in enumerate(title_matches):
        item_html_pos = html.find(title)
        if item_html_pos == -1:
            continue

        # Determine section by proximity
        section = "news"
        if tools_pos != -1 and item_html_pos > tools_pos:
            section = "tools"
        if signal_pos != -1 and item_html_pos > signal_pos:
            section = "signal"

        summary = summary_matches[i] if i < len(summary_matches) else ""
        # Strip HTML tags from summary
        summary = re.sub(r"<[^>]+>", "", summary).strip()

        items.append({
            "title": title,
            "summary": summary,
            "section": section,
        })

    return items


def collect_research_digest(state: dict) -> list[dict]:
    """Collect top picks from the research digest."""
    items = _extract_research_digest()

    # Separate by type, then pick best N of each
    tools = []
    signals = []

    for item in items:
        section = item["section"]
        signal_id = f"research:{item['title'][:60]}"
        if _is_used(state, signal_id):
            continue

        if section == "tools":
            signal_type = "research_tool"
            pillar = "ai_tools"
        elif section == "signal":
            signal_type = "research_signal"
            pillar = "wry"
        else:
            # News items — skip for content purposes (too general)
            continue

        target_list = tools if signal_type == "research_tool" else signals
        target_list.append({
            "signal_id": signal_id,
            "signal_type": signal_type,
            "pillar": pillar,
            "priority": 6,
            "freshness_hours": 48,
            "variables": {
                "title": item["title"],
                "summary": item["summary"],
                "section": section,
            },
        })

    # Take max per type
    result = tools[:MAX_PER_TYPE.get("research_tool", 2)]
    result += signals[:MAX_PER_TYPE.get("research_signal", 1)]
    return result


def _extract_github_radar() -> list[dict]:
    """Read the latest github-radar HTML and extract repo entries."""
    items = []

    radar_dir = RUNBOOKS_DIR / "github-radar"
    if not radar_dir.exists():
        return items

    # Find most recent day directory with HTML
    day_dirs = sorted([d for d in radar_dir.iterdir() if d.is_dir()], reverse=True)
    if not day_dirs:
        return items

    html_files = sorted(day_dirs[0].glob("*.html"), reverse=True)
    if not html_files:
        return items

    try:
        html = html_files[0].read_text(encoding="utf-8")
    except OSError:
        return items

    # Extract repo blocks: name, description, finding
    # Pattern: class="repo-name" href="URL">text</a>
    repo_names = re.findall(
        r'class="repo-name"[^>]*>([^<]+)</a>', html
    )
    # class="repo-desc"
    repo_descs = re.findall(
        r'class="repo-desc">(.*?)</div>', html, re.DOTALL
    )
    # class="repo-finding"
    repo_findings = re.findall(
        r'class="repo-finding">(.*?)</div>', html, re.DOTALL
    )

    for i, name in enumerate(repo_names):
        desc = repo_descs[i] if i < len(repo_descs) else ""
        finding = repo_findings[i] if i < len(repo_findings) else ""

        # Clean HTML tags
        desc = re.sub(r"<[^>]+>", "", desc).strip()
        finding = re.sub(r"<[^>]+>", "", finding).strip()

        items.append({
            "repo_name": name.strip(),
            "description": desc,
            "finding": finding,
        })

    return items


def collect_github_radar(state: dict) -> list[dict]:
    """Collect top repos from the GitHub radar."""
    signals = []
    items = _extract_github_radar()

    for item in items:
        signal_id = f"gitradar:{item['repo_name']}"
        if _is_used(state, signal_id):
            continue

        signals.append({
            "signal_id": signal_id,
            "signal_type": "gitradar_repo",
            "pillar": "ai_tools",
            "priority": 5,
            "freshness_hours": 72,
            "variables": {
                "repo_name": item["repo_name"],
                "description": item["description"],
                "finding": item["finding"],
            },
        })
        if len(signals) >= MAX_PER_TYPE["gitradar_repo"]:
            break

    return signals


def collect_architecture_insights(state: dict) -> list[dict]:
    """Evergreen content about KENSEI architecture and setup.

    These don't use state tracking — they rotate through topics.
    """
    topics = [
        {
            "topic": "lead_sub_agent_architecture",
            "label": "15 leads, 29 sub-agents",
            "description": "Why I split my personal AI into specialised agents with distinct identities, toolsets, and quality gates",
            "pillar": "tutorial",
        },
        {
            "topic": "quality_gates",
            "label": "multiple quality gates",
            "description": "How review, QA, and governance agents prevent silent drift across a multi-agent system",
            "pillar": "tutorial",
        },
        {
            "topic": "governance_agent",
            "label": "governance with Denji",
            "description": "Why a 15-agent workforce needs its own governance agent for profile changes, audits, and auto-handoffs",
            "pillar": "ai_tools",
        },
        {
            "topic": "content_pipeline",
            "label": "content engine",
            "description": "How four brands, one pipeline, and zero API spend generates 30 posts/day",
            "pillar": "tutorial",
        },
        {
            "topic": "coding_workflow",
            "label": "hybrid coding pipeline",
            "description": "Claude Code + Hermes + Octacon as a coded review chain — the architecture that keeps code quality high without slowing down",
            "pillar": "tutorial",
        },
        {
            "topic": "research_pipeline",
            "label": "daily research digest",
            "description": "How Remii curates 10-15 daily items from 6 sources with a single LLM cron, no scripts",
            "pillar": "ai_tools",
        },
    ]

    # Return one per run, rotating through them
    return [
        {
            "signal_id": f"arch:{topics[0]['topic']}",
            "signal_type": "architecture",
            "pillar": topics[0]["pillar"],
            "priority": 7,
            "freshness_hours": 9999,  # nearly evergreen
            "variables": {
                "topic_label": topics[0]["label"],
                "description": topics[0]["description"],
                "topic": topics[0]["topic"],
            },
        }
    ]


_HARNESS_REPOS = [
    Path(os.path.expanduser("~/repos/KenseiAgent")),
    Path(os.path.expanduser("~/.hermes/profiles")),   # declarative config only; READ-ONLY
]
_HARNESS_KEYWORDS = ("model", "routing", "fallback", "governance", "profile", "cron",
                     "context", "memory", "skill", "tool", "harness", "orchestrat")


def _git_log(repo: "Path", n: int = 15) -> str:
    """Recent commits as 'hash\x1fsubject\x1fdate' lines. Empty on any failure."""
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "log", f"-{n}", "--no-merges",
             "--pretty=format:%h\x1f%s\x1f%cs", "--since=10.days"],
            capture_output=True, text=True, timeout=15)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def collect_harness_changes(state: dict) -> list:
    """Surface 'what I adjusted in my agentic harness and why' from KenseiAgent +
    profiles git logs. Read-only; degrades to [] on any error."""
    signals = []
    cap = MAX_PER_TYPE.get("harness_change", 2)
    for repo in _HARNESS_REPOS:
        if not (repo / ".git").exists():
            continue
        for line in _git_log(repo).splitlines():
            parts = line.split("\x1f")
            if len(parts) != 3:
                continue
            sha, subject, date = parts
            if not any(k in subject.lower() for k in _HARNESS_KEYWORDS):
                continue
            sid = f"harness:{repo.name}:{sha}"
            if _is_used(state, sid):
                continue
            signals.append({
                "signal_id": sid, "signal_type": "harness_change",
                "summary": subject.strip(), "repo": repo.name, "sha": sha, "date": date,
                "priority": 8, "pillar": "harness_tuning",
                "freshness_hours": 72,
                "variables": {"summary": subject.strip(), "repo": repo.name, "sha": sha},
            })
            if len(signals) >= cap:
                return signals
    return signals


def collect_all() -> dict:
    """Run all collectors and return structured activity data.

    Returns:
        dict with:
          - "signals": list of signal dicts (unused, deduped)
          - "has_activity": bool
          - "state": updated state dict
    """
    state = _ensure_state()

    all_signals = []
    collectors = [
        collect_github_pushes,
        collect_hermes_prs,
        collect_hermes_skills,
        collect_research_digest,
        collect_github_radar,
        collect_architecture_insights,
        collect_harness_changes,
    ]

    for collector in collectors:
        try:
            signals = collector(state)
            all_signals.extend(signals)
        except Exception as e:
            print(f"[activity_collector] {collector.__name__} failed: {e}")

    # Sort by priority descending
    all_signals.sort(key=lambda s: s["priority"], reverse=True)

    # Mark used signals in state (but don't save yet — save only if topics.py uses them)
    # We'll pass state back so topics.py can mark used signals
    state["last_run"] = datetime.now(timezone.utc).isoformat()

    return {
        "signals": all_signals,
        "has_activity": len(all_signals) > 0,
        "state": state,
    }


def mark_signals_used(state: dict, signal_ids: list[str]):
    """Mark specific signals as used (called from topics.py after generation)."""
    for sid in signal_ids:
        _mark_used(state, sid)
    _save_state(state)


if __name__ == "__main__":
    result = collect_all()
    print(f"Activity signals found: {len(result['signals'])}")
    print(f"Has activity: {result['has_activity']}")
    for s in result["signals"]:
        print(f"  [{s['signal_type']}] {s['variables'].get('repo_name', s['variables'].get('title', s['signal_id']))} (priority={s['priority']})")
