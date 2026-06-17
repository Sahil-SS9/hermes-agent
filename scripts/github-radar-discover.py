#!/usr/bin/env python3
"""
GitHub Radar — Automated Repo Discovery Pipeline (v4.0)
no_agent mode: script produces Discord summary + HTML attachment + structured repos file.

- Collects repos from GitHub Search API + trending scrape
- Pre-filters noise + self-tunes thresholds
- Scores + classifies repos deterministically
- Writes dark-theme HTML report
- Writes structured ---REPOS--- text file for downstream librarian cron
- Prints concise Discord summary + MEDIA tag to stdout

stdout → Discord message (summary + MEDIA tag)
~/.hermes/runbooks/github-radar/YYYY-MM-DD/...html → full dark report
~/.hermes/runbooks/github-radar/YYYY-MM-DD/github-radar-repos.txt → structured repos for librarian
"""

import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone, timedelta

# ── Data Paths ──────────────────────────────────────────────────────

DATA_DIR = os.path.expanduser("~/.hermes/data/github-radar")
RUNBOOKS_DIR = os.path.expanduser("~/.hermes/runbooks/github-radar")
CACHE_FILE = os.path.join(DATA_DIR, "cache.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "discoveries.json")
METRICS_FILE = os.path.join(DATA_DIR, "metrics.json")
THRESHOLDS_FILE = os.path.join(DATA_DIR, "thresholds.json")

DATE_STR = datetime.now(timezone.utc).strftime("%Y-%m-%d")
TIME_STR = datetime.now(timezone.utc).strftime("%H%M")
DAY_LABEL = datetime.now(timezone.utc).strftime("%d/%m/%Y")
TODAY_ISO = datetime.now(timezone.utc).strftime("%Y-%m-%d")
RUNBOOKS_TODAY = os.path.join(RUNBOOKS_DIR, DATE_STR)
HTML_FILE = os.path.join(RUNBOOKS_TODAY, f"github-radar-{DATE_STR}-{TIME_STR}.html")
REPOS_TXT_FILE = os.path.join(RUNBOOKS_TODAY, "github-radar-repos.txt")
TEMPLATE_HTML = os.path.expanduser("~/.hermes/templates/dark-report-template.html")

# ── Static Config ───────────────────────────────────────────────────

RECENCY_DAYS = 7
CREATED_RECENCY_DAYS = 90  # wider window to exclude truly ancient repos
MAX_RESULTS_PER_QUERY = 100
MAX_PAGES = 10
TRENDING_URL = "https://github.com/trending?since=daily"

QUERY_TEMPLATES = [
    {"q": "stars:>{stars}", "sort": "stars", "order": "desc", "star_base": 100},
    {"q": "language:python stars:>{stars}", "sort": "stars", "order": "desc", "star_base": 50},
    {"q": "language:typescript stars:>{stars}", "sort": "stars", "order": "desc", "star_base": 50},
    {"q": "language:go stars:>{stars}", "sort": "stars", "order": "desc", "star_base": 50},
    {"q": "language:rust stars:>{stars}", "sort": "stars", "order": "desc", "star_base": 50},
    {"q": "topic:mcp stars:>{stars}", "sort": "stars", "order": "desc", "star_base": 10},
    {"q": "topic:agent-framework stars:>{stars}", "sort": "stars", "order": "desc", "star_base": 10},
    {"q": "topic:developer-tools stars:>{stars}", "sort": "stars", "order": "desc", "star_base": 20},
    {"q": "topic:hermes-plugin stars:>{stars}", "sort": "stars", "order": "desc", "star_base": 5},
]

# Relevance keywords for Sahil's stack (weight 0.3), tiered so on-mission
# terms outrank incidental keyword hits. HIGH = core agent/AI stack; GENERIC =
# adjacent or domain terms that only matter alongside a high-signal hit.
RELEVANCE_HIGH = [
    "mcp server", "mcp", "agent", "agentic", "claude", "anthropic", "llm",
    "react native", "expo", "convex", "supabase", "hermes", "deepgram",
    "orchestration", "rag", "memory", "skill", "plugin",
]
RELEVANCE_GENERIC = [
    "python", "typescript", "rust", "react", "flutter", "cli", "tui",
    "terminal", "voice", "tts", "stt", "proxy", "filter",
    "kitchen", "grocery", "pantry", "inventory", "e-ink",
    "football", "soccer", "sports", "grassroots", "matchday",
    "prediction", "cv builder", "portfolio",
]
RELEVANCE_HIGH_WEIGHT = 20
RELEVANCE_GENERIC_WEIGHT = 6
RELEVANCE_SIGNAL_FLOOR = 20  # min relevance for a repo to count as on-mission

# Classification score cutoffs, calibrated to the corrected star curve (scores
# now centre ~60, top ~75, vs the old curve which inflated most repos into the
# 80s). HIGH = strong / act-now tier; EXTRACT = on-mission mid tier.
CLASSIFY_HIGH = 68
CLASSIFY_EXTRACT = 60

# Relevance floor: repos classified above INSPIRATION must have at least this
# relevance score. Prevents high-star but off-mission repos (Logitech drivers,
# travel planners) from landing in FORK/PRODUCT.
RELEVANCE_FLOOR = 10

# ── Default thresholds ──────────────────────────────────────────────

DEFAULT_THRESHOLDS = {
    "star_threshold": 100,
    "min_star_threshold": 25,
    "max_star_threshold": 500,
    "noise_keywords": ["awesome", "curated list", "awesome list", "learn", "tutorial", "list", "resource", "cheatsheet"],
    "language_filters": ["HTML", "CSS", "Markdown"],
    # High-precision spam patterns for star-farmed repos (date-suffixed names,
    # cracked-software bait). Conservative: must not catch llama-3 / gpt-4.
    "spam_name_patterns": [
        r"-(19|20)\d\d(-|$)",
        r"(?i)(crack|keygen|nulled|allprompts|free-?download|activation-?key|license-?key|-latest-|version-\d)",
    ],
    "dead_repo_forks_ratio": 3.0,
    "dead_repo_min_stars": 10,
    "consecutive_noise_high_days": 3,
    "consecutive_signal_good_days": 3,
    "consecutive_signal_low_days": 5,
    "noise_high_threshold_pct": 40.0,
    "noise_low_threshold_pct": 20.0,
    "signal_high_threshold_pct": 60.0,
    "signal_low_threshold_pct": 10.0,
    "star_adjust_step": 25,
    "history": [],
    "last_tuned": None,
}

# ── Dark Theme CSS (embedded fallback if template missing) ─────────────

DARK_CSS = """
:root { color-scheme: dark; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #11100f; color: #e0dcd6; margin: 0; padding: 20px; line-height: 1.5; }
.container { max-width: 900px; margin: 0 auto; }
h1 { color: #fbbf24; border-bottom: 2px solid #fbbf24; padding-bottom: 8px; margin-bottom: 16px; }
h2 { color: #fbbf24; margin-top: 28px; font-size: 1.1em; text-transform: uppercase; letter-spacing: 0.03em; }
.stats { display: grid; grid-template-columns: repeat(auto-fit,minmax(140px,1fr)); gap: 8px; margin: 12px 0 20px; }
.stat { background: #1c1a18; border: 1px solid #34302c; border-radius: 6px; padding: 10px 12px; }
.stat-label { font-size: 0.75em; color: #a8a29e; text-transform: uppercase; }
.stat-value { font-size: 1.25em; font-weight: 600; color: #fbbf24; }
.repo { background: #1c1a18; border: 1px solid #34302c; border-radius: 8px; padding: 14px; margin-bottom: 10px; }
.repo-header { display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px; flex-wrap: wrap; }
.repo-name { font-weight: 600; color: #fbbf24; font-size: 1.05em; }
.repo-stars { color: #a8a29e; font-size: 0.85em; }
.repo-lang { color: #a8a29e; font-size: 0.85em; }
.repo-meta { margin-bottom: 6px; }
.repo-score { font-size: 0.85em; color: #a8a29e; }
.repo-desc { color: #e0dcd6; margin-bottom: 6px; }
.repo-why { color: #d6d3d1; font-style: italic; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75em; font-weight: 600; margin-right: 6px; }
.badge-green { background: #3f6212; color: #bef264; }
.badge-yellow { background: #713f12; color: #fde047; }
.badge-red { background: #7f1d1d; color: #fca5a5; }
.badge-blue { background: #1e3a5f; color: #93c5fd; }
.badge-grey { background: #3d3d3d; color: #d4d4d4; }
.footer { margin-top: 20px; color: #78716c; font-size: 0.8em; border-top: 1px solid #34302c; padding-top: 10px; }
a { color: #60a5fa; text-decoration: none; }
a:hover { text-decoration: underline; }
""".strip()


def load_thresholds():
    if not os.path.exists(THRESHOLDS_FILE):
        save_thresholds(DEFAULT_THRESHOLDS)
        return dict(DEFAULT_THRESHOLDS)
    try:
        with open(THRESHOLDS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(DEFAULT_THRESHOLDS)
        merged.update(data)
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_THRESHOLDS)


def save_thresholds(thresholds):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(THRESHOLDS_FILE, "w", encoding="utf-8") as f:
            json.dump(thresholds, f, indent=2, default=str)
    except OSError as e:
        print(f"WARN: Failed to write thresholds: {e}", file=sys.stderr)


def build_queries(thresholds):
    base_threshold = thresholds["star_threshold"]
    queries = []
    for tpl in QUERY_TEMPLATES:
        star_eff = max(tpl["star_base"], int(base_threshold * 0.75))
        q = tpl["q"].replace("{stars}", str(star_eff))
        queries.append({"q": q, "sort": tpl["sort"], "order": tpl["order"]})
    return queries


# ── Self-Tuning ─────────────────────────────────────────────────────

METRICS_LOOKBACK_DAYS = 7


def load_metrics():
    if not os.path.exists(METRICS_FILE):
        return []
    try:
        with open(METRICS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def append_metrics_entry(entry):
    metrics = load_metrics()
    metrics.append(entry)
    if len(metrics) > 365:
        metrics = metrics[-365:]
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(METRICS_FILE, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)
    except OSError as e:
        print(f"WARN: Failed to write metrics: {e}", file=sys.stderr)


def self_tune(thresholds, noise_rate_pct, signal_rate_pct):
    actions = []
    metrics = load_metrics()
    today = {"noise_rate_pct": noise_rate_pct, "signal_rate_pct": signal_rate_pct}
    recent = metrics[-METRICS_LOOKBACK_DAYS:] if len(metrics) >= METRICS_LOOKBACK_DAYS else metrics
    window = list(recent) + [today] if recent else [today]

    if len(window) < 2:
        return thresholds, ["Not enough data to tune (need 2+ runs)"]

    high_noise_consecutive = 0
    good_signal_consecutive = 0
    low_signal_consecutive = 0
    low_noise_consecutive = 0

    for entry in window:
        nr = entry.get("noise_rate_pct", 0)
        sr = entry.get("signal_rate_pct", 0)
        if nr >= thresholds["noise_high_threshold_pct"]:
            high_noise_consecutive += 1
        else:
            high_noise_consecutive = 0
        if sr >= thresholds["signal_high_threshold_pct"] and nr <= thresholds["noise_low_threshold_pct"]:
            good_signal_consecutive += 1
        else:
            good_signal_consecutive = 0
        if sr <= thresholds["signal_low_threshold_pct"]:
            low_signal_consecutive += 1
        else:
            low_signal_consecutive = 0
        if nr <= thresholds["noise_low_threshold_pct"]:
            low_noise_consecutive += 1
        else:
            low_noise_consecutive = 0

    star_changed = False

    if high_noise_consecutive >= thresholds["consecutive_noise_high_days"]:
        old = thresholds["star_threshold"]
        new = min(old + thresholds["star_adjust_step"], thresholds["max_star_threshold"])
        if new != old:
            thresholds["star_threshold"] = new
            star_changed = True
            actions.append(f"TIGHTEN: noise >{thresholds['noise_high_threshold_pct']}% for {high_noise_consecutive}d — star_threshold {old} → {new}")
    elif good_signal_consecutive >= thresholds["consecutive_signal_good_days"] and low_noise_consecutive >= thresholds["consecutive_signal_good_days"]:
        old = thresholds["star_threshold"]
        new = max(old - thresholds["star_adjust_step"], thresholds["min_star_threshold"])
        if new != old:
            thresholds["star_threshold"] = new
            star_changed = True
            actions.append(f"EASE: signal >{thresholds['signal_high_threshold_pct']}% for {good_signal_consecutive}d — star_threshold {old} → {new}")

    if not star_changed:
        actions.append(f"NO CHANGE: star_threshold stays at {thresholds['star_threshold']}")

    return thresholds, actions


# ── GitHub API helpers ───────────────────────────────────────────────


def gh_auth_token():
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        return token
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return r.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def get_date_filters():
    """Return (pushed_cutoff, created_cutoff) for compound recency filter."""
    pushed_cutoff = datetime.now(timezone.utc) - timedelta(days=RECENCY_DAYS)
    created_cutoff = datetime.now(timezone.utc) - timedelta(days=CREATED_RECENCY_DAYS)
    return pushed_cutoff.strftime("%Y-%m-%d"), created_cutoff.strftime("%Y-%m-%d")


def github_search(query, sort="stars", order="desc", per_page=100, page=1):
    token = gh_auth_token()
    if not token:
        return [], 0
    pushed_q, created_q = get_date_filters()
    full_q = f"{query} pushed:>{pushed_q} created:>{created_q}"
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
            return data.get("items", []), data.get("total_count", 0)
    except urllib.error.HTTPError as e:
        print(f"WARN: GitHub API error {e.code} for query '{query[:60]}': {e.reason}", file=sys.stderr)
        return [], 0
    except Exception as e:
        print(f"WARN: GitHub API exception: {e}", file=sys.stderr)
        return [], 0


def scrape_trending():
    results = []
    try:
        req = urllib.request.Request(TRENDING_URL, headers={
            "User-Agent": "KENSEI-GitHub-Radar/1.0",
            "Accept": "text/html",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        repos = set()
        for match in re.finditer(
            r'<h2[^>]*class="[^\"]*h3[^\"]*"[^>]*>.*?<a[^>]*href="/([^/\"]+)/([^/\"]+)"',
            html, re.DOTALL
        ):
            owner, repo = match.group(1), match.group(2)
            if owner and repo:
                repos.add(f"{owner}/{repo}")
        for full_name in repos:
            results.append({"full_name": full_name, "source": "trending"})
    except Exception as e:
        print(f"WARN: Trending scrape failed: {e}", file=sys.stderr)
    return results


def parse_star_count(item):
    val = item.get("stargazers_count") or item.get("stars") or 0
    return int(val)


def extract_repo(item):
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


def build_noise_patterns(thresholds):
    keywords = thresholds.get("noise_keywords", DEFAULT_THRESHOLDS["noise_keywords"])
    lang_filters = thresholds.get("language_filters", DEFAULT_THRESHOLDS["language_filters"])
    fork_ratio = thresholds.get("dead_repo_forks_ratio", 3.0)
    dead_min = thresholds.get("dead_repo_min_stars", 10)
    spam_patterns = thresholds.get("spam_name_patterns", DEFAULT_THRESHOLDS["spam_name_patterns"])
    return {
        "awesome_list": lambda r: any(
            kw in (r.get("description", "") + " " + " ".join(r.get("topics", []))).lower()
            for kw in ["awesome", "curated list", "awesome list"]
        ),
        "tutorial_content": lambda r: any(
            r["full_name"].lower().startswith(prefix)
            for prefix in ["learn-", "awesome-", "tutorial-"]
        ),
        "dead_repo": lambda r: (
            parse_star_count(r) < dead_min
            or (r.get("forks", 0) or 0) > parse_star_count(r) * fork_ratio
        ),
        "non_code": lambda r: r.get("language", "") in lang_filters,
        "name_noise": lambda r: any(
            kw in r["full_name"].lower().split("/")[1]
            for kw in keywords
        ),
        "spam_name": lambda r: any(
            re.search(p, r["full_name"].split("/")[-1])
            for p in spam_patterns
        ),
    }


NOISE_ORDER = ["awesome_list", "non_code", "name_noise", "spam_name", "tutorial_content", "dead_repo"]


def classify_noise(repo, thresholds):
    patterns = build_noise_patterns(thresholds)
    for rule in NOISE_ORDER:
        if patterns[rule](repo):
            return True, rule
    return False, ""


def deduplicate(repos):
    seen = {}
    for r in repos:
        name = r["full_name"]
        if name not in seen or parse_star_count(r) > parse_star_count(seen[name]):
            seen[name] = r
    return list(seen.values())


# ── Scoring ──────────────────────────────────────────────────────────


def score_repo(repo):
    """Deterministic scoring: returns (score, classification, why)."""
    stars = parse_star_count(repo)

    # Stars score (0-100, weight 0.4): log curve with real spread across the
    # realistic 0-2000 star range. The old sqrt curve saturated by ~50 stars and
    # went negative for 0-star trending finds, making the 40% weight inert.
    star_score = min(100.0, 20 + 80 * math.log10(stars + 1) / math.log10(2000))

    # Relevance score (0-100, weight 0.3), tiered: high-signal terms are worth
    # more than incidental ones, so on-mission repos rank above keyword noise.
    text_blob = f"{repo.get('description', '')} {' '.join(repo.get('topics', []))} {repo.get('language', '')}".lower()
    high_hits = sum(1 for kw in RELEVANCE_HIGH if kw in text_blob)
    generic_hits = sum(1 for kw in RELEVANCE_GENERIC if kw in text_blob)
    relevance_score = min(100, high_hits * RELEVANCE_HIGH_WEIGHT + generic_hits * RELEVANCE_GENERIC_WEIGHT)

    # Freshness (0-100, weight 0.2)
    try:
        pushed = datetime.fromisoformat(repo.get("pushed_at", "").replace("Z", "+00:00"))
        days_since_push = (datetime.now(timezone.utc) - pushed).days
        freshness_score = max(0, 100 - days_since_push * 10)  # linear decay
    except (ValueError, TypeError):
        freshness_score = 50
    
    # Active dev (0-100, weight 0.1)
    try:
        created = datetime.fromisoformat(repo.get("created_at", "").replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - created).days
        active_score = 100 if age_days < 30 else (80 if age_days < 90 else 50)
    except (ValueError, TypeError):
        active_score = 50
    
    score = round(star_score * 0.4 + relevance_score * 0.3 + freshness_score * 0.2 + active_score * 0.1, 1)
    
    # Classification. EXTRACT now requires a real on-mission signal (a
    # description plus a relevance hit) rather than being the catch-all at
    # score>=65; otherwise the repo drops to INSPIRATION. This stops EXTRACT
    # swallowing two-thirds of every batch.
    on_mission = bool(repo.get("description", "").strip()) and relevance_score >= RELEVANCE_SIGNAL_FLOOR
    classification, why = "INSPIRATION", "Moderate signal: worth noting for future reference."

    if score >= CLASSIFY_HIGH:
        if any(kw in text_blob for kw in ["mcp server", "mcp", "plugin", "skill"]):
            classification, why = "PLUGIN/SKILL", "Agent tooling: aligns with Hermes/KENSEI ecosystem."
        elif any(kw in text_blob for kw in ["product", "saas", "platform", "app", "react native", "expo"]):
            classification, why = "FORK/PRODUCT", "Could become a standalone product: evaluate for Plenishd/CoachOS or new spinoff."
        elif any(kw in text_blob for kw in ["proxy", "filter", "terminal", "cli", "tui", "voice"]):
            classification, why = "ADOPT", "Direct internal tool: install or integrate into KENSEI workflows."
        elif on_mission:
            classification, why = "EXTRACT", "Contains a pattern worth extracting for our own tools."
    elif score >= CLASSIFY_EXTRACT:
        if any(kw in text_blob for kw in ["mcp server", "mcp", "plugin", "skill"]):
            classification, why = "PLUGIN/SKILL", "Agent tooling: worth monitoring."
        elif on_mission:
            classification, why = "EXTRACT", "Interesting architecture or utility: extract if time permits."

    # Relevance floor: demote off-mission repos that scored high on stars alone.
    if classification != "INSPIRATION" and relevance_score < RELEVANCE_FLOOR:
        classification, why = "INSPIRATION", "High stars but off-mission: worth noting for future reference."

    return score, classification, why


def classify_all(repos):
    """Add score and classification to each repo. Returns list with scores."""
    scored = []
    for r in repos:
        score, classification, why = score_repo(r)
        scored.append({
            **r,
            "score": score,
            "classification": classification,
            "why": why,
        })
    # Sort by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


# ── LLM enrichment (opt-in, top picks only) ──────────────────────────

# Opt-in via env. Default ON locally; the public edition ships it OFF.
ENRICH_ENABLED = os.getenv("GITRADAR_ENRICH", "0") not in ("0", "false", "no", "")
ENRICH_TOP_N = int(os.getenv("GITRADAR_ENRICH_TOP_N", "8"))
ENRICH_BASE_URL = os.getenv("GITRADAR_ENRICH_BASE_URL", "https://ollama.com/v1")
ENRICH_MODEL = os.getenv("GITRADAR_ENRICH_MODEL", "deepseek-v4-flash")
ENRICH_API_KEY_ENV = os.getenv("GITRADAR_ENRICH_API_KEY_ENV", "OLLAMA_API_KEY")


def enrich_why(repos):
    """Replace the boilerplate `why` on the top-N non-noise repos with a genuine
    one-line rationale from a cheap model. Best-effort: any failure leaves the
    deterministic text untouched. One batched call, no per-repo requests."""
    if not ENRICH_ENABLED:
        return
    api_key = os.getenv(ENRICH_API_KEY_ENV, "")
    if not api_key:
        print(f"ENRICH: skipped (no {ENRICH_API_KEY_ENV})", file=sys.stderr)
        return

    picks = [r for r in repos if r.get("classification") != "NOISE"][:ENRICH_TOP_N]
    if not picks:
        return

    listing = "\n".join(
        f'{i+1}. {r["full_name"]} [{r["classification"]}] ({r.get("language") or "?"}, ★{r["stars"]}): '
        f'{(r.get("description") or "no description")[:200]}'
        for i, r in enumerate(picks)
    )
    prompt = (
        "You triage new GitHub repos for an AI-agent builder. For each repo below, "
        "write ONE concrete sentence (max 22 words) on why it matters or what is worth "
        "taking from it. Be specific to the repo, not generic. No marketing fluff.\n\n"
        f"{listing}\n\n"
        'Reply with ONLY a JSON object mapping each repo full_name to its sentence, '
        'e.g. {"owner/repo": "..."}.'
    )
    payload = json.dumps({
        "model": ENRICH_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "stream": False,
    }).encode()
    req = urllib.request.Request(f"{ENRICH_BASE_URL}/chat/completions", data=payload)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", content, re.DOTALL)
        mapping = json.loads(match.group(0) if match else content)
    except Exception as e:
        print(f"ENRICH: failed, keeping deterministic text ({e})", file=sys.stderr)
        return

    enriched = 0
    for r in picks:
        line = mapping.get(r["full_name"])
        if isinstance(line, str) and line.strip():
            r["why"] = line.strip()
            r["why_enriched"] = True
            enriched += 1
    print(f"ENRICH: {enriched}/{len(picks)} top picks enriched", file=sys.stderr)


# ── Cache ───────────────────────────────────────────────────────────


CACHE_TTL_DAYS = 14  # repos expire from cache after 14 days, allowing re-discovery


def load_cache():
    """Load cache and prune entries older than CACHE_TTL_DAYS.
    Supports both old format {seen: [list]} and new format {seen: {repo: date_str}}."""
    if not os.path.exists(CACHE_FILE):
        return set()
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        seen_data = data.get("seen", [])
        # Old format: list of repo names (no timestamps) — prune all (treat as expired)
        if isinstance(seen_data, list):
            print(f"CACHE: old list format ({len(seen_data)} entries), clearing", file=sys.stderr)
            return set()
        # New format: dict of {repo: date_seen_str}
        if isinstance(seen_data, dict):
            now = datetime.now(timezone.utc)
            expired = 0
            active = set()
            for repo, date_str in seen_data.items():
                try:
                    seen_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if (now - seen_date).days < CACHE_TTL_DAYS:
                        active.add(repo)
                    else:
                        expired += 1
                except (ValueError, TypeError):
                    expired += 1
            if expired > 0:
                print(f"CACHE: pruned {expired} expired entries (TTL={CACHE_TTL_DAYS}d), {len(active)} active", file=sys.stderr)
            return active
    except (json.JSONDecodeError, KeyError):
        return set()


def save_cache(seen):
    """Save cache in new timestamped format: {seen: {repo: date_seen_str}}."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        seen_dict = {repo: now_str for repo in seen}
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"seen": seen_dict}, f)
    except Exception as e:
        print(f"WARN: Failed to write cache: {e}", file=sys.stderr)


# ── HTML Report Builder ──────────────────────────────────────────────


def badge_class(label):
    return {
        "ADOPT": "badge-green",
        "EXTRACT": "badge-blue",
        "PLUGIN/SKILL": "badge-yellow",
        "FORK/PRODUCT": "badge-red",
        "INSPIRATION": "badge-grey",
    }.get(label, "badge-grey")


def build_html(repos, stats):
    """Build dark-theme HTML report. Returns HTML string."""
    rows = []
    rows.append("<!DOCTYPE html><html><head><meta charset='utf-8'><title>GitHub Radar</title>")
    rows.append(f"<style>{DARK_CSS}</style></head><body><div class='container'>")
    rows.append(f"<h1>GitHub Radar · {DAY_LABEL}</h1>")
    
    # Stats cards
    rows.append("<div class='stats'>")
    for label, value in [
        ("Repos", stats["after_dedup"]),
        ("Scored", stats["scored"]),
        ("ADOPT", len([r for r in repos if r["classification"] == "ADOPT"])),
        ("EXTRACT", len([r for r in repos if r["classification"] == "EXTRACT"])),
        ("PLUGIN/SKILL", len([r for r in repos if r["classification"] == "PLUGIN/SKILL"])),
        ("FORK/PRODUCT", len([r for r in repos if r["classification"] == "FORK/PRODUCT"])),
        ("INSPIRATION", len([r for r in repos if r["classification"] == "INSPIRATION"])),
        ("NOISE", stats["noise"]),
    ]:
        rows.append(f'<div class="stat"><div class="stat-label">{label}</div><div class="stat-value">{value}</div></div>')
    rows.append("</div>")
    
    # Top 15 scored repos
    top_repos = [r for r in repos if r["classification"] != "NOISE"][:15]
    if top_repos:
        rows.append(f"<h2>Top {len(top_repos)} Scored Repos</h2>")
    for r in top_repos:
        bc = badge_class(r["classification"])
        rows.append(f'<div class="repo">')
        rows.append(f'<div class="repo-header">')
        rows.append(f'<span class="repo-name"><a href="{r["html_url"]}" target="_blank">{r["full_name"]}</a></span>')
        rows.append(f'<span class="repo-stars">★ {r["stars"]}</span>')
        rows.append(f'<span class="repo-lang">{r["language"] or "Unknown"}</span>')
        rows.append(f'<span class="badge {bc}">{r["classification"]}</span>')
        rows.append(f'<span class="repo-score">Score: {r["score"]}</span>')
        rows.append(f'</div>')
        if r.get("description"):
            rows.append(f'<div class="repo-desc">{r["description"]}</div>')
        rows.append(f'<div class="repo-why">→ {r["why"]}</div>')
        rows.append(f'</div>')
    
    if len(repos) > len(top_repos):
        noise_count = len([r for r in repos if r["classification"] == "NOISE"])
        rows.append(f"<div class='footer'>+ {noise_count} noise-repos filtered. Full data in {OUTPUT_FILE}.</div>")
    
    rows.append("</div></body></html>")
    return "\n".join(rows)


# ── Structured Text (for downstream librarian cron) ───────────────────


def build_repos_text(repos, stats):
    """Build structured text with ---REPOS--- section for librarian context_from."""
    lines = [
        f"**GitHub Radar** · {DAY_LABEL} {datetime.now(timezone.utc).strftime('%H:%M')}",
        f"{stats['after_dedup']} repos · {stats['scored']} scored · " +
        f"{len([r for r in repos if r['classification']=='ADOPT'])} ADOPT · " +
        f"{len([r for r in repos if r['classification']=='EXTRACT'])} EXTRACT · " +
        f"{len([r for r in repos if r['classification']=='PLUGIN/SKILL'])} PLUGIN/SKILL · " +
        f"{len([r for r in repos if r['classification']=='FORK/PRODUCT'])} FORK/PRODUCT · " +
        f"{len([r for r in repos if r['classification']=='INSPIRATION'])} INSPIRATION",
        "",
        "---REPOS---",
    ]
    
    for r in repos:
        if r.get("classification") == "NOISE":
            continue
        lines.append(f"[REPO] {r['full_name']} | stars:{r['stars']} | lang:{r.get('language','')} | classification:{r['classification']} | score:{r['score']} | url:{r['html_url']}")
        lines.append(f"  Description: {r.get('description', 'No description')}")
        lines.append(f"  Why it matters: {r['why']}")
    
    lines.append("---END REPOS---")
    lines.append("")
    lines.append("Top 3 this batch:")
    for idx, r in enumerate([r for r in repos if r.get("classification") != "NOISE"][:3], 1):
        lines.append(f"{idx}. {r['full_name']} — {r['why']}")
    
    lines.append("")
    lines.append("Tuning:")
    for action in stats.get("tuning_actions", []):
        lines.append(f"  • {action}")
    
    return "\n".join(lines)


# ── Discord Summary ──────────────────────────────────────────────────


def build_discord_summary(repos, stats):
    """Concise summary for Discord — 3-5 lines max."""
    top = [r for r in repos if r.get("classification") != "NOISE"][:3]
    lines = [
        f"**GitHub Radar** · {DAY_LABEL} {datetime.now(timezone.utc).strftime('%H:%M')}",
        f"`{stats['after_dedup']} repos · {stats['scored']} scored`",
        "",
        "**Top picks**",
    ]
    for r in top:
        lines.append(f"• `{r['classification']}` [{r['full_name']}](&lt;{r['html_url']}&gt;) — ★ {r['stars']}, score {r['score']}")
    
    lines.append("")
    lines.append(f"**Summary:** `ADOPT:{len([r for r in repos if r['classification']=='ADOPT'])} EXTRACT:{len([r for r in repos if r['classification']=='EXTRACT'])} PLUGIN/SKILL:{len([r for r in repos if r['classification']=='PLUGIN/SKILL'])} FORK/PRODUCT:{len([r for r in repos if r['classification']=='FORK/PRODUCT'])} INSPIRATION:{len([r for r in repos if r['classification']=='INSPIRATION'])}`")
    lines.append("")
    lines.append(f"**Full detail:** MEDIA:{HTML_FILE}")
    
    return "\n".join(lines)


# ── Collection + Pipeline ───────────────────────────────────────────


def collect(queries):
    seen_cache = load_cache()
    seen = set(seen_cache)
    all_repos = []
    rate_limited = False
    
    for query_def in queries:
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
                fn = item.get("full_name", "")
                if fn and fn not in seen:
                    seen.add(fn)
                    all_repos.append(extract_repo(item))
            page += 1
            if page <= MAX_PAGES:
                time.sleep(0.5)
    
    trending = scrape_trending()
    for t in trending:
        name = t["full_name"]
        if name not in seen:
            seen.add(name)
            all_repos.append({
                "full_name": name, "description": "", "stars": 0, "forks": 0,
                "language": "", "topics": [], "created_at": "", "pushed_at": "",
                "open_issues": 0, "license": "", "html_url": f"https://github.com/{name}",
                "source": "trending",
            })
    
    save_cache(seen)
    print(f"COLLECT: {len(all_repos)} repos ({len([r for r in all_repos if r['source']=='trending'])} from trending)", file=sys.stderr)
    return all_repos


def filter_repos(repos, thresholds):
    keep = []
    filtered = defaultdict(list)
    for repo in repos:
        is_noise, reason = classify_noise(repo, thresholds)
        if is_noise:
            filtered[reason].append(repo["full_name"])
        else:
            keep.append(repo)
    print(f"FILTER: {len(keep)} kept, {len(repos)-len(keep)} filtered", file=sys.stderr)
    for reason, names in sorted(filtered.items()):
        print(f"  {reason}: {len(names)}", file=sys.stderr)
    return keep, dict(filtered)


def deduplicate_repos(repos):
    result = deduplicate(repos)
    print(f"DEDUP: {len(result)} unique ({len(repos)-len(result)} removed)", file=sys.stderr)
    return result


# ── Main ───────────────────────────────────────────────────────────


def main():
    thresholds = load_thresholds()
    queries = build_queries(thresholds)
    
    print(f"CONFIG: star_threshold={thresholds['star_threshold']}, queries={len(queries)}", file=sys.stderr)
    
    # Stage 1: Collection
    all_repos = collect(queries)
    
    # Stage 2: Filter + dedup
    filtered, filter_reasons = filter_repos(all_repos, thresholds)
    final = deduplicate_repos(filtered)
    
    # Score + classify
    scored = classify_all(final)

    # Enrich the top picks' rationale with a cheap model (opt-in, best-effort)
    enrich_why(scored)

    # Stats
    total = len(all_repos)
    noise_count = total - len(filtered)
    signal_count = len(final)
    noise_rate_pct = round(noise_count / total * 100, 1) if total > 0 else 0.0
    signal_rate_pct = round(signal_count / total * 100, 1) if total > 0 else 0.0
    
    # Self-tune
    thresholds, tuning_actions = self_tune(thresholds, noise_rate_pct, signal_rate_pct)
    save_thresholds(thresholds)
    
    print("TUNING:", file=sys.stderr)
    for a in tuning_actions:
        print(f"  {a}", file=sys.stderr)
    
    # Build stats dict
    stats = {
        "total_collected": total,
        "after_filter": len(filtered),
        "after_dedup": len(final),
        "scored": len(scored),
        "noise": noise_count,
        "signal_rate_pct": signal_rate_pct,
        "noise_rate_pct": noise_rate_pct,
        "active_threshold": thresholds["star_threshold"],
        "tuning_actions": tuning_actions,
        "collection_queries": len(queries),
    }
    
    # Write JSON output
    output = {
        "collected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "stats": stats,
        "filter_reasons": {k: len(v) for k, v in filter_reasons.items()},
        "tuning": {"actions": tuning_actions, "thresholds": {k: thresholds[k] for k in ["star_threshold", "noise_keywords", "language_filters"]}},
        "repos": scored,
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    
    # Write HTML report + structured repos text
    os.makedirs(RUNBOOKS_TODAY, exist_ok=True)
    
    html = build_html(scored, stats)
    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    
    repos_txt = build_repos_text(scored, stats)
    with open(REPOS_TXT_FILE, "w", encoding="utf-8") as f:
        f.write(repos_txt)
    
    # Print Discord summary + MEDIA tag
    print(build_discord_summary(scored, stats))
    
    # Metrics
    metrics_entry = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "total_repos": total,
        "actionable": signal_count,
        "noise": noise_count,
        "signal_rate_pct": signal_rate_pct,
        "noise_rate_pct": noise_rate_pct,
        "star_threshold": thresholds["star_threshold"],
    }
    append_metrics_entry(metrics_entry)


if __name__ == "__main__":
    main()
