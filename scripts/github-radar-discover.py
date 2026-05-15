#!/usr/bin/env python3
"""
GitHub Radar — Automated Repo Discovery Pipeline (Daily Cron)
Phase 1-3: Discovery + Classification + Kanban Routing + Digest

Collects repos from GitHub Search API + trending scrape,
pre-filters noise, then outputs structured JSON for the
Hermes cron agent to classify and route.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# ── Config ──────────────────────────────────────────────────────────

STAR_THRESHOLD = 100
RECENCY_DAYS = 7
MAX_RESULTS_PER_QUERY = 100
MAX_PAGES = 10  # GitHub caps search results at 1000
TRENDING_URL = "https://github.com/trending?since=daily"
CACHE_FILE = os.path.expanduser("~/.hermes/data/github-radar/cache.json")
OUTPUT_FILE = os.path.expanduser("~/.hermes/data/github-radar/discoveries.json")
QUERIES = [
    # Primary: high-signal repos
    {"q": "stars:>100", "sort": "stars", "order": "desc"},
    # Language expanders
    {"q": "language:python stars:>50", "sort": "stars", "order": "desc"},
    {"q": "language:typescript stars:>50", "sort": "stars", "order": "desc"},
    {"q": "language:go stars:>50", "sort": "stars", "order": "desc"},
    {"q": "language:rust stars:>50", "sort": "stars", "order": "desc"},
    # Topic targets (low volume, high relevance)
    {"q": "topic:mcp stars:>10", "sort": "stars", "order": "desc"},
    {"q": "topic:agent-framework stars:>10", "sort": "stars", "order": "desc"},
    {"q": "topic:developer-tools stars:>20", "sort": "stars", "order": "desc"},
    {"q": "topic:hermes-plugin stars:>5", "sort": "stars", "order": "desc"},
]

# ── Helpers ─────────────────────────────────────────────────────────

def get_date_filter():
    """Returns the `created:>YYYY-MM-DD` qualifier for the recency window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENCY_DAYS)
    return cutoff.strftime("%Y-%m-%d")


def gh_auth_token():
    """Get GitHub PAT from gh CLI."""
    result = subprocess.run(
        ["gh", "auth", "token"], capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        print(f"WARN: gh auth failed: {result.stderr.strip()}", file=sys.stderr)
        return None
    return result.stdout.strip()


def github_search(query, sort="stars", order="desc", per_page=100, page=1):
    """Call GitHub Search API. Returns (items, total_count) or ([], 0)."""
    token = gh_auth_token()
    if not token:
        return [], 0

    date_q = get_date_filter()
    full_q = f"{query} created:>{date_q}"
    params = urllib.parse.urlencode({
        "q": full_q, "sort": sort, "order": order,
        "per_page": per_page, "page": page
    })
    url = f"https://api.github.com/search/repositories?{params}"

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "KENSEI-GitHub-Radar/1.0")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            items = data.get("items", [])
            return items, data.get("total_count", 0)
    except urllib.error.HTTPError as e:
        print(f"WARN: GitHub API error {e.code} for query '{query[:60]}': {e.reason}", file=sys.stderr)
        return [], 0
    except Exception as e:
        print(f"WARN: GitHub API exception: {e}", file=sys.stderr)
        return [], 0


def scrape_trending():
    """Scrape GitHub Trending page. Returns list of {full_name, ...}."""
    results = []
    try:
        req = urllib.request.Request(TRENDING_URL, headers={
            "User-Agent": "KENSEI-GitHub-Radar/1.0",
            "Accept": "text/html",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        import re
        repos = set()
        for match in re.finditer(
            r'<h2[^>]*class="[^"]*h3[^"]*"[^>]*>.*?<a[^>]*href="/([^/"]+)/([^/"]+)"',
            html, re.DOTALL
        ):
            owner = match.group(1)
            repo = match.group(2)
            if owner and repo:
                repos.add(f"{owner}/{repo}")

        for full_name in repos:
            results.append({
                "full_name": full_name,
                "source": "trending",
            })
    except Exception as e:
        print(f"WARN: Trending scrape failed: {e}", file=sys.stderr)
    return results


def parse_star_count(item):
    """Safely parse star count from GitHub item (API key or our normalised key)."""
    val = item.get("stargazers_count") or item.get("stars") or 0
    return int(val)


def extract_repo(item):
    """Normalise a GitHub API item into our standard dict."""
    return {
        "full_name": item.get("full_name", ""),
        "description": (item.get("description") or "").strip(),
        "stars": parse_star_count(item),
        "forks": item.get("forks_count", 0) or 0,
        "language": item.get("language") or "",
        "topics": item.get("topics", []) or [],
        "created_at": item.get("created_at", ""),
        "pushed_at": item.get("pushed_at", ""),
        "open_issues": item.get("open_issues_count", 0) or 0,
        "license": item.get("license", {}).get("spdx_id", "") if item.get("license") else "",
        "html_url": item.get("html_url", ""),
        "source": "api",
    }


# ── Pre-Filtering ──────────────────────────────────────────────────

NOISE_PATTERNS = {
    "awesome_list": lambda r: any(
        kw in (r.get("description", "") + " " + " ".join(r.get("topics", []))).lower()
        for kw in ["awesome", "curated list", "awesome list"]
    ),
    "tutorial_content": lambda r: any(
        r["full_name"].lower().startswith(prefix)
        for prefix in ["learn-", "awesome-", "tutorial-"]
    ),
    "dead_repo": lambda r: (
        parse_star_count(r) < 10
        or (r.get("forks", 0) or 0) > parse_star_count(r) * 3
    ),
    "non_code": lambda r: r.get("language", "") in ("HTML", "CSS", "Markdown", ""),
    "name_noise": lambda r: any(
        kw in r["full_name"].lower().split("/")[1]
        for kw in ["awesome", "learn", "tutorial", "list", "resource", "cheatsheet"]
    ),
}

NOISE_ORDER = ["awesome_list", "non_code", "name_noise", "tutorial_content", "dead_repo"]


def classify_noise(repo):
    """Returns (is_noise: bool, reason: str)."""
    for rule in NOISE_ORDER:
        if NOISE_PATTERNS[rule](repo):
            return True, rule
    return False, ""


def deduplicate(repos):
    """Deduplicate by full_name, keeping highest-star entry."""
    seen = {}
    for r in repos:
        name = r["full_name"]
        if name not in seen or parse_star_count(r) > parse_star_count(seen[name]):
            seen[name] = r
    return list(seen.values())


def load_cache():
    """Load previously-seen repo names."""
    if not os.path.exists(CACHE_FILE):
        return set()
    try:
        with open(CACHE_FILE) as f:
            data = json.load(f)
            return set(data.get("seen", []))
    except (json.JSONDecodeError, KeyError):
        return set()


def save_cache(seen):
    """Save seen repo names with expiry."""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump({"seen": list(seen)}, f)
    except Exception as e:
        print(f"WARN: Failed to write cache: {e}", file=sys.stderr)


# ── Main Pipeline ──────────────────────────────────────────────────

def collect():
    """Stage 1: Data Collection. Returns raw list of repos."""
    seen_cache = load_cache()
    seen = set(seen_cache)  # mutable working set
    all_repos = []
    rate_limited = False

    # ── Primary + Secondary API searches ──
    for query_def in QUERIES:
        if rate_limited:
            break
        q = query_def["q"]
        sort = query_def.get("sort", "stars")
        order = query_def.get("order", "desc")

        page = 1
        while page <= MAX_PAGES and not rate_limited:
            items, total = github_search(q, sort, order, 100, page)
            if not items:
                break
            for item in items:
                full_name = item.get("full_name", "")
                if full_name and full_name not in seen:
                    seen.add(full_name)
                    all_repos.append(extract_repo(item))
            page += 1
            # Be kind to the API
            if page <= MAX_PAGES:
                time.sleep(0.5)

    # ── Trending scrape (secondary source) ──
    trending = scrape_trending()
    for t in trending:
        name = t["full_name"]
        if name not in seen:
            seen.add(name)
            all_repos.append({
                "full_name": name,
                "description": "",
                "stars": 0,
                "forks": 0,
                "language": "",
                "topics": [],
                "created_at": "",
                "pushed_at": "",
                "open_issues": 0,
                "license": "",
                "html_url": f"https://github.com/{name}",
                "source": "trending",
            })

    # Save updated cache
    save_cache(seen)

    print(f"COLLECT: {len(all_repos)} repos collected "
          f"({len([r for r in all_repos if r['source'] == 'trending'])} from trending)",
          file=sys.stderr)

    return all_repos


def filter_repos(repos):
    """Stage 2: Pre-filtering. Returns (keep, filtered_out_with_reasons)."""
    keep = []
    filtered = defaultdict(list)

    for repo in repos:
        is_noise, reason = classify_noise(repo)
        if is_noise:
            filtered[reason].append(repo["full_name"])
        else:
            keep.append(repo)

    print(f"FILTER: {len(keep)} kept, {len(repos) - len(keep)} filtered:",
          file=sys.stderr)
    for reason, names in filtered.items():
        print(f"  {reason}: {len(names)}", file=sys.stderr)

    return keep, dict(filtered)


def deduplicate_repos(repos):
    """Stage 2b: Deduplication."""
    result = deduplicate(repos)
    print(f"DEDUP: {len(result)} unique after dedup "
          f"({len(repos) - len(result)} duplicates removed)",
          file=sys.stderr)
    return result


def run_pipeline():
    """Full pipeline: collect -> filter -> dedup -> output JSON."""
    all_repos = collect()
    filtered, filter_reasons = filter_repos(all_repos)
    final = deduplicate_repos(filtered)

    output = {
        "collected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "stats": {
            "total_collected": len(all_repos),
            "after_filter": len(filtered),
            "after_dedup": len(final),
            "collection_queries": len(QUERIES),
        },
        "filter_reasons": {k: len(v) for k, v in filter_reasons.items()},
        "repos": final,
    }

    # Write output to standard location
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    # Also output to stdout for cron agent consumption
    # Limit stdout to 200 repos max to keep token usage sane
    output_stdout = dict(output)
    output_stdout["repos"] = final[:200]
    if len(final) > 200:
        output_stdout["stats"]["truncated"] = True
        output_stdout["stats"]["showing"] = 200

    print(json.dumps(output_stdout))
    return output


if __name__ == "__main__":
    run_pipeline()
