#!/usr/bin/env python3
"""KENSEI Research Digest collector and static renderer.

Collects high-signal daily AI/devtools/personal-agent news candidates with Tavily,
dedupes and scores them, then writes JSON, Markdown, HTML, and Telegram text.
"""

from __future__ import annotations

import argparse
import email.utils
import html
import json
import math
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo


LANE_A = "AI News"
LANE_B = "Tool News"
LANE_C = "Research"
LANE_ORDER = [LANE_A, LANE_B, LANE_C]
LANE_LABELS = {
    LANE_A: "AI News",
    LANE_B: "Tool News",
    LANE_C: "Research",
}

TOPIC_QUERIES = [
    {
        "lane": LANE_A,
        "query": "new AI model launch release announced today 2026",
        "include_domains": ["anthropic.com", "openai.com", "blog.google", "deepmind.google", "developers.googleblog.com", "huggingface.co", "deepseek.com", "x.ai", "mistral.ai", "techcrunch.com", "arstechnica.com", "theverge.com", "venturebeat.com", "nousresearch.com", "ollama.com"],
    },
    {
        "lane": LANE_B,
        "query": "new AI developer tool library SDK framework launched released 2026",
        "include_domains": ["github.com", "github.blog", "vercel.com", "cloudflare.com", "huggingface.co", "openai.com", "anthropic.com", "deepseek.com", "ollama.com", "hermes-agent.nousresearch.com"],
    },
    {
        "lane": LANE_C,
        "query": "new open source AI agent project launched released 2026",
        "include_domains": [],
    },
]

RSS_SOURCES = [
    # AI News — Model releases, announcements
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "lane": LANE_A},
    {"name": "OpenAI News", "url": "https://openai.com/news/rss.xml", "lane": LANE_A, "official": True},
    {"name": "Google AI Blog", "url": "https://blog.google/technology/ai/rss/", "lane": LANE_A, "official": True},
    {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml", "lane": LANE_A, "official": True},
    # Tool News — Platform updates, devtools, releases
    {"name": "GitHub Changelog", "url": "https://github.blog/changelog/feed/", "lane": LANE_B, "official": True},
    {"name": "HN frontpage (150+)", "url": "https://hnrss.org/frontpage?points=150", "lane": LANE_B},
    {"name": "HN Show", "url": "https://hnrss.org/show", "lane": LANE_C},
    # Research — GitHub repos, agent frameworks, devtools
    {"name": "Reddit r/hermesagent", "url": "https://www.reddit.com/r/hermesagent/.rss", "lane": LANE_C},
    {"name": "Reddit r/LocalLLaMA", "url": "https://www.reddit.com/r/LocalLLaMA/.rss", "lane": LANE_C},
    {"name": "Reddit r/ClaudeAI", "url": "https://www.reddit.com/r/ClaudeAI/.rss", "lane": LANE_C},
]

X_ACCOUNT_QUERIES = [
    # AI News + Community — 20 targeted accounts across labs, curated AI, indie builders
    {"query": "from:nousresearch OR from:ollama OR from:openai OR from:AnthropicAI OR from:deepseek_ai OR from:xai OR from:mistralai OR from:huggingface OR from:teknium OR from:intheworldofai OR from:claudedevs OR from:petergyang OR from:rileybrown OR from:rasmic OR from:godofprompt OR from:iam_elias1 OR from:davidondrej1 OR from:aaditsh OR from:akshay_pachaar", "lane": LANE_A},
    # DevTools & Platform — 11 accounts
    {"query": "from:OpenRouterAI OR from:vercel OR from:supabase OR from:expo OR from:github OR from:cloudflaredev OR from:langchainai OR from:modelcontextprot OR from:thdxr OR from:bccherny OR from:durov", "lane": LANE_B},
]

X_RESULTS_PER_QUERY = 8

RSS_USER_AGENT = "KENSEI Research Digest/1.0 (+https://hermes-agent.nousresearch.com)"

OFFICIAL_OR_HIGH_SIGNAL_DOMAINS = {
    "hermes-agent.nousresearch.com",
    "github.com",
    "docs.anthropic.com",
    "anthropic.com",
    "openai.com",
    "developers.openai.com",
    "ollama.com",
    "qwenlm.github.io",
    "moonshot.ai",
    "huggingface.co",
    "arxiv.org",
    "news.ycombinator.com",
    "langchain.com",
    "blog.langchain.dev",
    "expo.dev",
    "reactnative.dev",
    "convex.dev",
    "supabase.com",
    "deepgram.com",
    "blog.google",
    "deepmind.google",
    "developers.googleblog.com",
    "github.blog",
    "modelcontextprotocol.io",
    "news.ycombinator.com",
    "hnrss.org",
    "nousresearch.com",
    "techcrunch.com",
}

PRESS_RELEASE_DOMAINS = {
    "accesswire.com",
    "businesswire.com",
    "einnews.com",
    "globenewswire.com",
    "morningstar.com",
    "newsfilecorp.com",
    "openpr.com",
    "prnewswire.com",
}

ALWAYS_BLOCKED_PR_CARRIERS = {"morningstar.com", "openpr.com"}

DIRECT_STACK_TERMS = {
    "claude code",
    "codex",
    "hermes",
    "kensei",
    "mcp",
    "openai codex",
    "openclaw",
    "opencode",
}

SEO_COMPARISON_TERMS = {
    "alternatives",
    "best ai tools",
    "best tools",
    "compare",
    "compared",
    "comparison",
    "pricing",
    "reviews",
    "top ai tools",
    "vs",
}

MEME_TERMS = {"dank", "funny", "joke", "lol", "meme", "shitpost"}

REDDIT_DISCUSSION_NOISE_TERMS = {
    "are you switching",
    "chain of thought",
    "complaints",
    "does the",
    "drama",
    "experiencing",
    "fixed the slowdown",
    "for users experiencing",
    "gap",
    "has anyone",
    "hot take",
    "how to setup",
    "issues with upgrading",
    "just leaked",
    "leaked",
    "let's not",
    "looooong",
    "long delays",
    "messed with",
    "opinion",
    "rant",
    "should i",
    "speculation",
    "tired of reading",
    "what are",
}

REDDIT_STRONG_SIGNAL_TERMS = {
    "announced",
    "available",
    "changelog",
    "launch",
    "launched",
    "new version",
    "now works",
    "release",
    "released",
    "release notes",
    "version",
}

NEWS_TERMS = {
    "announced",
    "announcement",
    "available",
    "changelog",
    "general availability",
    "github release",
    "introducing",
    "launch",
    "launched",
    "now available",
    "preview",
    "release",
    "released",
    "release notes",
    "rollout",
    "ships",
    "update",
    "updated",
    "upgrade",
    "version",
}

HIGH_VALUE_TOPIC_TERMS = {
    "agent",
    "agents",
    "claude code",
    "codex",
    "convex",
    "deepseek",
    "expo",
    "gemini",
    "hermes",
    "kimi",
    "langgraph",
    "mcp",
    "memory",
    "ollama cloud",
    "openai codex",
    "openclaw",
    "opencode",
    "qwen",
    "react native",
    "supabase",
    "workspace",
}

POSITIVE_TERMS = {
    "agent",
    "agents",
    "changelog",
    "claude code",
    "codex",
    "convex",
    "cron",
    "daily briefing",
    "deepseek",
    "devtool",
    "devtools",
    "expo",
    "gemini",
    "github",
    "hermes",
    "kimi",
    "kensei",
    "langgraph",
    "llm",
    "mcp",
    "ollama",
    "open source",
    "open-weight",
    "qwen",
    "react native",
    "release",
    "released",
    "release notes",
    "supabase",
    "version",
    "launch",
    "announced",
    "workspace",
    "memory",
    "workflow",
}

NEGATIVE_TERMS = {
    "funding",
    "raises",
    "series a",
    "series b",
    "enterprise transformation",
    "press release",
    "sponsored",
    "crypto",
    "stock",
    "hype",
    "how to",
    "guide",
    "tutorial",
    "docs",
    "documentation",
}

EXCLUDED_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "composio.dev",
}

EXCLUDED_PHRASES = {
    "awesome-",
    "composio",
    "best ai tools",
    "github topics",
    "my-awesome-stars",
    "top ai tools",
    "who is hiring",
    "who wants to be hired",
    "sponsored",
}

BLOCKED_GITHUB_REPOS = {
    ("warpdot-dev", "composio"),
}

MIN_SELECTED_SCORE = 4.0

KNOWN_GITHUB_ORGS = {
    "nousresearch",
    "anthropics",
    "openai",
    "openclaw",
    "ollama",
    "qwenlm",
    "langchain-ai",
    "modelcontextprotocol",
}

TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "igshid"}
STOPWORDS = {"a", "an", "and", "for", "from", "in", "new", "of", "on", "the", "to", "with"}


@dataclass(frozen=True)
class OutputPaths:
    directory: Path
    json_path: Path
    markdown_path: Path
    html_path: Path
    telegram_path: Path


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()


def default_output_dir(now: datetime | None = None) -> Path:
    now = now or datetime.now(ZoneInfo("Europe/London"))
    return hermes_home() / "runbooks" / "research-digest" / now.strftime("%Y-%m-%d")


def output_paths(out_dir: Path) -> OutputPaths:
    return OutputPaths(
        directory=out_dir,
        json_path=out_dir / "research-digest.json",
        markdown_path=out_dir / "research-digest.md",
        html_path=out_dir / "research-digest.html",
        telegram_path=out_dir / "telegram.txt",
    )


def load_env_values(env_path: Path, names: Iterable[str]) -> dict[str, str]:
    wanted = set(names)
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in wanted:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value:
            values[key] = value
    return values


def command_env() -> dict[str, str]:
    env = os.environ.copy()
    env_values = load_env_values(hermes_home() / ".env", ["TAVILY_API_KEY"])
    env.update(env_values)
    return env


def canonical_url(url: str) -> str:
    parsed = urlparse(url)
    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lower = key.lower()
        if lower in TRACKING_KEYS or any(lower.startswith(prefix) for prefix in TRACKING_PREFIXES):
            continue
        query.append((key, value))
    netloc = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or parsed.path
    return urlunparse((parsed.scheme.lower(), netloc, path, "", urlencode(query), ""))


def source_from_url(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.") or "unknown"


def xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def child_text(element: ET.Element, names: set[str]) -> str:
    for child in list(element):
        if xml_local_name(child.tag) in names:
            if child.text:
                return child.text.strip()
            href = child.attrib.get("href", "").strip()
            if href:
                return href
    return ""


def strip_markup(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def parse_popularity(value: str) -> tuple[int, int]:
    text = strip_markup(value).lower()
    points = 0
    comments = 0
    points_match = re.search(r"(?<!\d)(\d{1,6})\s+(?:points?|upvotes?|score)", text)
    comments_match = re.search(r"(?<!\d)(\d{1,6})\s+comments?", text)
    if points_match:
        points = int(points_match.group(1))
    if comments_match:
        comments = int(comments_match.group(1))
    return points, comments


def iter_feed_entries(root: ET.Element) -> Iterable[ET.Element]:
    for element in root.iter():
        if xml_local_name(element.tag) in {"item", "entry"}:
            yield element


def rss_item_within_time_range(published: str, time_range: str, now: datetime | None = None) -> bool:
    if not published:
        return False
    try:
        parsed = email.utils.parsedate_to_datetime(published)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Europe/London"))
    now = now or datetime.now(ZoneInfo("Europe/London"))
    window_days = {"day": 1, "week": 7, "month": 31, "year": 366}.get(time_range, 7)
    return now - parsed.astimezone(now.tzinfo) <= timedelta(days=window_days)


def tavily_result_within_time_range(item: dict, time_range: str, now: datetime | None = None) -> bool:
    published = item.get("published_date", "")
    if not published:
        return True  # No date info means we keep it for manual review
    try:
        parsed = datetime.fromisoformat(published.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        try:
            parsed = datetime.strptime(published, "%Y-%m-%d")
            parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
        except ValueError:
            return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    now = now or datetime.now(ZoneInfo("Europe/London"))
    window_days = {"day": 1, "week": 7, "month": 31, "year": 366}.get(time_range, 7)
    return now - parsed.astimezone(now.tzinfo) <= timedelta(days=window_days)


def normalise_rss_entry(entry: ET.Element, source: dict) -> dict | None:
    title = strip_markup(child_text(entry, {"title"}))
    url = child_text(entry, {"link"})
    if not url:
        return None
    content = strip_markup(child_text(entry, {"description", "summary", "content", "encoded"}))
    points, comments = parse_popularity(f"{title} {content}")
    return {
        "title": title or source.get("name", source_from_url(url)),
        "url": url.strip(),
        "source": source_from_url(url),
        "lane": source.get("lane", LANE_B),
        "query": f"rss:{source.get('name', source.get('url', 'feed'))}",
        "content": clean_content(content),
        "source_type": "rss",
        "feed_name": source.get("name", source.get("url", "rss")),
        "official_source": bool(source.get("official")),
        "search_score": 0.7,
        "points": points,
        "comments": comments,
        "published": child_text(entry, {"pubdate", "published", "updated", "date"}),
    }


def collect_rss_feed(source: dict, max_items: int = 8, timeout: int = 20, time_range: str = "week", now: datetime | None = None) -> list[dict]:
    request = urllib.request.Request(
        source["url"],
        headers={"User-Agent": RSS_USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    root = ET.fromstring(raw)
    candidates = []
    for entry in iter_feed_entries(root):
        item = normalise_rss_entry(entry, source)
        if item and rss_item_within_time_range(item.get("published", ""), time_range, now=now):
            candidates.append(item)
        if len(candidates) >= max_items:
            break
    return candidates


def collect_rss_candidates(max_items_per_feed: int = 8, time_range: str = "week") -> tuple[list[dict], list[dict]]:
    candidates: list[dict] = []
    diagnostics: list[dict] = []
    now = datetime.now(ZoneInfo("Europe/London"))
    for source in RSS_SOURCES:
        try:
            items = collect_rss_feed(source, max_items=max_items_per_feed, time_range=time_range, now=now)
            candidates.extend(items)
            diagnostics.append({"status": "ok", "query": f"rss:{source['name']}", "lane": source["lane"], "results": len(items), "time_range": time_range})
        except Exception as exc:  # pragma: no cover, live feed failures vary
            diagnostics.append({"status": "error", "query": f"rss:{source.get('name', source.get('url', 'feed'))}", "lane": source.get("lane"), "message": str(exc)[:300]})
    return candidates, diagnostics


def candidate_haystack(candidate: dict) -> str:
    return f"{candidate.get('title', '')} {candidate.get('content', '')} {candidate.get('url', '')} {candidate.get('lane', '')}".lower()


def has_version_signal(text: str) -> bool:
    return bool(re.search(r"\bv?\d+(?:\.\d+){1,4}\b", text))


def term_in_text(text: str, term: str) -> bool:
    escaped = re.escape(term.lower()).replace(r"\ ", r"\s+")
    return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text.lower()))


def any_term_in_text(text: str, terms: Iterable[str]) -> bool:
    return any(term_in_text(text, term) for term in terms)


def has_news_signal(candidate: dict) -> bool:
    haystack = candidate_haystack(candidate)
    if has_version_signal(haystack):
        return True
    if any_term_in_text(haystack, NEWS_TERMS):
        return True
    source = candidate.get("source") or source_from_url(candidate.get("url", ""))
    if source == "github.com":
        path_bits = [bit.lower() for bit in urlparse(candidate.get("url", "")).path.split("/") if bit]
        return any(bit in {"releases", "tags"} for bit in path_bits)
    return False


def has_high_value_topic(candidate: dict) -> bool:
    haystack = candidate_haystack(candidate)
    return any_term_in_text(haystack, HIGH_VALUE_TOPIC_TERMS)


def has_strong_github_root_news(candidate: dict) -> bool:
    haystack = candidate_haystack(candidate)
    return has_version_signal(haystack) or any_term_in_text(
        haystack,
        {"announced", "changelog", "introducing", "launch", "launched", "now available", "release", "released", "release notes", "version"},
    )


def is_static_reference_candidate(candidate: dict) -> bool:
    haystack = candidate_haystack(candidate)
    source = candidate.get("source") or source_from_url(candidate.get("url", ""))
    path = urlparse(candidate.get("url", "")).path.lower()
    title_url = f"{candidate.get('title', '')} {candidate.get('url', '')}".lower()
    if source in {"docs.anthropic.com", "hermes-agent.nousresearch.com", "modelcontextprotocol.io"}:
        return not any_term_in_text(title_url, {"changelog", "release", "released", "release notes", "version", "what's new", "whats new"})
    if source == "huggingface.co" and ("/activity/" in path or "/resolve/" in path or "/raw/" in path or "/blob/" in path or "/datasets/" in path or "/spaces/" in path):
        return True
    if source == "ollama.com" and (path == "/search" or path.startswith("/library/")):
        return True
    if "/docs" in path and not any_term_in_text(title_url, {"changelog", "release", "release notes", "what's new", "whats new"}):
        return True
    return any_term_in_text(haystack, {"how to", "tutorial", "guide", "documentation"}) and not has_news_signal(candidate)


def is_direct_stack_news(candidate: dict) -> bool:
    haystack = candidate_haystack(candidate)
    return has_news_signal(candidate) and any_term_in_text(haystack, DIRECT_STACK_TERMS)


def is_press_release_fluff(candidate: dict) -> bool:
    source = candidate.get("source") or source_from_url(candidate.get("url", ""))
    if source in ALWAYS_BLOCKED_PR_CARRIERS:
        return True
    if source in PRESS_RELEASE_DOMAINS:
        return not is_direct_stack_news(candidate)
    haystack = candidate_haystack(candidate)
    return any_term_in_text(haystack, {"press release", "globenewswire", "pr newswire", "business wire", "openpr", "morningstar"}) and not is_direct_stack_news(candidate)


def is_seo_comparison_candidate(candidate: dict) -> bool:
    source = candidate.get("source") or source_from_url(candidate.get("url", ""))
    if source in OFFICIAL_OR_HIGH_SIGNAL_DOMAINS:
        return False
    title_url = f"{candidate.get('title', '')} {candidate.get('url', '')}".lower()
    path = urlparse(candidate.get("url", "")).path.lower()
    if re.search(r"\b[a-z0-9][a-z0-9.+-]*\s+vs\s+[a-z0-9][a-z0-9.+-]*\b", title_url):
        return True
    if any_term_in_text(title_url, SEO_COMPARISON_TERMS):
        return True
    return any(segment in path for segment in {"/alternatives", "/compare", "/comparison", "/pricing", "/reviews", "-vs-"})


def is_meme_candidate(candidate: dict) -> bool:
    haystack = candidate_haystack(candidate)
    return any_term_in_text(haystack, MEME_TERMS) and not is_direct_stack_news(candidate)


def is_low_signal_reddit_candidate(candidate: dict) -> bool:
    source = candidate.get("source") or source_from_url(candidate.get("url", ""))
    if source != "reddit.com" and not str(candidate.get("feed_name", "")).startswith("r/"):
        return False
    title = candidate.get("title", "")
    haystack = candidate_haystack(candidate)
    has_strong_signal = has_version_signal(haystack) or any_term_in_text(haystack, REDDIT_STRONG_SIGNAL_TERMS)
    title_has_release_signal = any_term_in_text(
        title,
        {"announced", "changelog", "launch", "launched", "new version", "release", "released", "release notes", "version"},
    )
    if any_term_in_text(haystack, REDDIT_DISCUSSION_NOISE_TERMS):
        return True
    if not title_has_release_signal:
        return True
    if not has_strong_signal:
        return True
    return False


def github_repo_identity(url: str) -> tuple[str, str] | None:
    if source_from_url(url) != "github.com":
        return None
    path_bits = [bit.lower() for bit in urlparse(url).path.split("/") if bit]
    if len(path_bits) < 2:
        return None
    return path_bits[0], path_bits[1]


def is_stale_rss_item(candidate: dict, now: datetime | None = None) -> bool:
    """Reject RSS entries older than 7 days. Prevents stale RSS from polluting the digest."""
    published = candidate.get("published", "")
    if not published:
        return False  # No date means we can't judge — keep it
    try:
        parsed = email.utils.parsedate_to_datetime(published)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            return False  # Unparseable date, keep it
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Europe/London"))
    now = now or datetime.now(ZoneInfo("Europe/London"))
    return now - parsed.astimezone(now.tzinfo) > timedelta(days=7)


def is_stale_by_url_date(candidate: dict, now: datetime | None = None) -> bool:
    """Extract date from URL path and reject items older than 7 days for daily digest."""
    url = candidate.get("url", "")
    title = candidate.get("title", "")
    now = now or datetime.now(ZoneInfo("Europe/London"))

    # Pattern 1: URL date path like /2026/05/12/ or /2026-01-27
    date_match = re.search(r"/(\d{4})[-/](\d{2})[-/](\d{1,2})", url)
    if date_match:
        try:
            year, month, day = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
            url_date = datetime(year, month, day, tzinfo=ZoneInfo("Europe/London"))
            return (now - url_date) > timedelta(days=90)
        except ValueError:
            pass

    # Pattern 2: Title contains a month-year like "March 2025", "January 2026", "Jan 2026"
    month_names = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
        'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
    }
    title_lower = title.lower()
    date_match = re.search(r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})", title_lower)
    if date_match:
        try:
            month = month_names[date_match.group(1)]
            year = int(date_match.group(2))
            if year < datetime.now(ZoneInfo("Europe/London")).year:
                return True  # any content explicitly referencing a past year is stale
            url_date = datetime(year, month, 1, tzinfo=ZoneInfo("Europe/London"))
            return (now - url_date) > timedelta(days=90)
        except ValueError:
            pass

    # Pattern 3: URL path contains a date like march-2025, jan-27-2026, 20260127
    date_match = re.search(r"(?:^|[-/])(\d{8})(?:$|[-/])", url)
    if date_match:
        try:
            date_str = date_match.group(1)
            url_date = datetime(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]), tzinfo=ZoneInfo("Europe/London"))
            return (now - url_date) > timedelta(days=90)
        except ValueError:
            pass

    return False


def is_excluded_candidate(candidate: dict) -> bool:
    url = candidate.get("url", "")
    source = candidate.get("source") or source_from_url(url)
    if source in EXCLUDED_DOMAINS:
        return True
    haystack = candidate_haystack(candidate)
    if is_press_release_fluff(candidate):
        return True
    if is_seo_comparison_candidate(candidate):
        return True
    if is_meme_candidate(candidate):
        return True
    if is_low_signal_reddit_candidate(candidate):
        return True
    if any_term_in_text(haystack, EXCLUDED_PHRASES):
        return True
    if candidate.get("source_type") == "rss" and is_stale_rss_item(candidate):
        return True
    if candidate.get("source_type") == "tavily" and is_stale_by_url_date(candidate):
        return True
    if source == "techcrunch.com":
        if candidate.get("source_type") == "tavily" and "p=31" in url:
            return True
    if is_static_reference_candidate(candidate):
        return True
    # Community sources (HN, Reddit, X) don't need version/news signals — they're curated
    if source not in {"news.ycombinator.com", "reddit.com", "x.com"}:
        if not has_news_signal(candidate):
            # Tavily results: search snippets are short, keywords rarely appear verbatim.
            # If the candidate has high-value topic terms and came from a targeted search,
            # treat it as having sufficient signal.
            if candidate.get("source_type") != "tavily" or not has_high_value_topic(candidate):
                return True
    repo_identity = github_repo_identity(url)
    if repo_identity in BLOCKED_GITHUB_REPOS:
        return True
    if source == "github.com":
        path_bits = [bit.lower() for bit in urlparse(url).path.split("/") if bit]
        if path_bits and path_bits[0] == "topics":
            return True
        if len(path_bits) >= 2 and (path_bits[1].startswith("awesome-") or path_bits[1] in {"starred", "my-awesome-stars", "zstar", "todo", "archive", "forked", "fork"}):
            return True
        if any(bit in {"blob", "tree", "pull", "pulls", "issue", "issues"} for bit in path_bits):
            return True
        if len(path_bits) == 2:
            # Only block GitHub repos if they're stale or clearly noise
            # Allow repos with recent release tags or version-like titles
            haystack = candidate_haystack(candidate)
            if not has_version_signal(haystack) and not any_term_in_text(haystack, {"release", "changelog", "announce", "launch", "new", "update", "agent", "framework", "tool", "library", "sdk"}):
                return True
    return False


def clean_content(content: str, max_chars: int = 1500) -> str:
    content = re.sub(r"\* \[!\[@[^\]]+\]\([^)]*avatars\.githubusercontent\.com[^)]*\)\]\([^)]*\)\.?", " ", content)
    content = re.sub(r"\[Skip to content\]\([^)]*\)\.?", " ", content)
    content = re.sub(r"\[Reload\]\([^)]*\)[^.]*\.", " ", content)
    content = re.sub(r"\s+", " ", content).strip()
    if len(content) <= max_chars:
        return content
    return content[:max_chars].rstrip() + "…"


def title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", title.lower())
    normalised = []
    for word in words:
        if word in STOPWORDS:
            continue
        if word in {"released", "releases", "releasing"}:
            word = "release"
        elif word.endswith("ing") and len(word) > 6:
            word = word[:-3]
        elif word.endswith("s") and len(word) > 4:
            word = word[:-1]
        normalised.append(word)
    return set(normalised)


def near_duplicate_title(a: str, b: str) -> bool:
    a_tokens = title_tokens(a)
    b_tokens = title_tokens(b)
    if not a_tokens or not b_tokens:
        return False
    overlap = len(a_tokens & b_tokens) / len(a_tokens | b_tokens)
    return overlap >= 0.62


def dedupe_candidates(candidates: list[dict]) -> list[dict]:
    unique: list[dict] = []
    seen_urls: set[str] = set()
    for candidate in sorted(candidates, key=lambda item: item.get("search_score", item.get("score", 0)), reverse=True):
        url = candidate.get("url", "")
        title = candidate.get("title", "")
        key = canonical_url(url)
        if key in seen_urls:
            continue
        if any(near_duplicate_title(title, item.get("title", "")) for item in unique):
            continue
        seen_urls.add(key)
        unique.append(candidate)
    return unique


def score_candidate(candidate: dict) -> float:
    title = candidate.get("title", "")
    content = candidate.get("content", "")
    url = candidate.get("url", "")
    lane = candidate.get("lane", "")
    haystack = candidate_haystack(candidate)
    source = source_from_url(url)

    score = float(candidate.get("search_score", candidate.get("score", 0)) or 0) * 5
    if has_news_signal(candidate):
        score += 5
    if has_version_signal(haystack):
        score += 3
    if any_term_in_text(haystack, {"now available", "release notes", "changelog", "introducing", "announced"}):
        score += 2
    if has_high_value_topic(candidate):
        score += 2
    if source in OFFICIAL_OR_HIGH_SIGNAL_DOMAINS:
        if has_high_value_topic(candidate) or has_news_signal(candidate):
            score += 4
        else:
            score += 2  # Half bonus when official source has no relevant topic
    if candidate.get("official_source"):
        if has_high_value_topic(candidate) or has_news_signal(candidate):
            score += 4
        else:
            score += 2  # Half bonus when official source has no relevant topic
    if candidate.get("source_type") == "rss":
        score += 1
    if candidate.get("source_type") == "x":
        score += 4  # X is early-signal: these catch announcements hours before RSS/Tavily
    if source == "arxiv.org" and lane != LANE_C:
        score -= 8
    if source == "arxiv.org" and lane == LANE_C:
        score -= 3
    if source == "huggingface.co" and "/posts/" in urlparse(url).path:
        score += 4

    # Penalise items explicitly referencing past years
    current_year = datetime.now(ZoneInfo("Europe/London")).year
    title = candidate.get("title", "").lower()
    content = candidate.get("content", "").lower()
    for year_offset in [current_year - 3, current_year - 2, current_year - 1]:
        if str(year_offset) in title or str(year_offset) in content[:200]:
            if "2026" not in title and f"2026" not in content[:200]:
                score -= 4

    points = int(candidate.get("points") or 0)
    comments = int(candidate.get("comments") or 0)
    if points:
        score += min(4.0, math.log10(points + 1) * 1.6)
    if comments:
        score += min(3.5, math.log10(comments + 1) * 1.7)
    feed_name = str(candidate.get("feed_name", ""))
    if source == "news.ycombinator.com" or feed_name.startswith("HN"):
        score += 2
    if source == "reddit.com" or feed_name.startswith("r/"):
        score -= 3
    if is_press_release_fluff(candidate):
        score -= 10
    if is_seo_comparison_candidate(candidate):
        score -= 10
    if source == "github.com":
        score += 2
        path_bits = [bit.lower() for bit in urlparse(url).path.split("/") if bit]
        org = path_bits[0] if path_bits else ""
        if org in KNOWN_GITHUB_ORGS:
            score += 3
        else:
            score -= 6
        if "releases" in path_bits:
            score += 3
        if "issues" in path_bits and ("Hermes" in lane or "cron" in haystack or "brief" in haystack):
            score += 2
        if "blob" in path_bits or "tree" in path_bits:
            score -= 4
    for term in POSITIVE_TERMS:
        if term in haystack:
            score += 1.2
    for term in NEGATIVE_TERMS:
        if term in haystack:
            score -= 3
    if lane == LANE_C or "Hermes Agent" in lane or "personal-agent" in lane:
        score += 2
    if len(content) < 80:
        score -= 1
    return round(score, 3)


def normalise_tavily_result(result: dict, lane: str, query: str) -> dict:
    url = result.get("url", "").strip()
    title = re.sub(r"\s+", " ", result.get("title", "")).strip()
    content = clean_content(result.get("content", ""))
    return {
        "title": title or source_from_url(url),
        "url": url,
        "source": source_from_url(url),
        "lane": lane,
        "query": query,
        "content": content,
        "search_score": result.get("score", 0),
        "source_type": "tavily",
        "published_date": result.get("published_date", ""),
    }


def run_tavily_search(
    query: str,
    env: dict[str, str],
    max_results: int = 7,
    time_range: str = "week",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> dict:
    """Run Tavily search with configurable fallback to Brave Search."""
    def _tavily_cmd(query: str, max_results: int, time_range: str) -> list[str]:
        cmd = [
            "tvly",
            "search",
            query,
            "--max-results",
            str(max_results),
            "--time-range",
            time_range,
            "--json",
        ]
        if include_domains:
            cmd.extend(["--include-domains", ",".join(include_domains)])
        if exclude_domains:
            cmd.extend(["--exclude-domains", ",".join(exclude_domains)])
        return cmd

    # Primary: Tavily
    try:
        raw = subprocess.check_output(_tavily_cmd(query, max_results, time_range), env=env, stderr=subprocess.STDOUT, timeout=60)
        return json.loads(raw.decode("utf-8"))
    except subprocess.CalledProcessError as exc:
        tavily_error = exc.output.decode("utf-8", errors="ignore") if exc.output else str(exc)
    except Exception as exc:
        tavily_error = str(exc)

    # Fallback 1: Brave Search (requires BRAVE_API_KEY in env)
    brave_key = env.get("BRAVE_API_KEY", os.environ.get("BRAVE_API_KEY", ""))
    if brave_key:
        try:
            return _run_brave_search(query, brave_key, max_results, time_range)
        except Exception as exc:
            brave_error = str(exc)
            raise RuntimeError(
                f"Tavily failed: {tavily_error}. Brave Search fallback also failed: {brave_error}. "
                f"Consider adding BRAVE_API_KEY to env or checking Tavily API key."
            )
    else:
        # Final fallback: return empty but structured error so caller can handle
        raise RuntimeError(
            f"Tavily failed: {tavily_error}. "
            f"Brave Search not configured (add BRAVE_API_KEY to ~/.hermes/.env for fallback)."
        )


def _run_brave_search(query: str, api_key: str, max_results: int, time_range: str) -> dict:
    """Brave Search API via HTTP."""
    import urllib.request
    params = urlencode({"q": query, "count": str(max_results), "freshness": time_range})
    request = urllib.request.Request(
        f"https://api.search.brave.com/res/v1/web/search?{params}",
        headers={
            "X-Subscription-Token": api_key,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    # Normalize Brave results to Tavily format
    results = []
    for item in data.get("web", {}).get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": item.get("description", ""),
            "score": item.get("score", 0.7),
            "published_date": item.get("age", ""),
        })
    return {"results": results}


def collect_github_trending(now: datetime | None = None) -> list[dict]:
    """Scrape GitHub trending repos for Python and TypeScript, filter for AI/devtools relevance."""
    candidates: list[dict] = []
    now = now or datetime.now(ZoneInfo("Europe/London"))

    trending_urls = [
        ("https://github.com/trending/python?since=daily", "Python"),
        ("https://github.com/trending/typescript?since=daily", "TypeScript"),
    ]

    for url, language in trending_urls:
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": RSS_USER_AGENT, "Accept": "text/html"},
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                html_body = response.read().decode("utf-8", errors="replace")
        except Exception:
            continue

        # Parse repo blocks from GitHub trending page
        repo_blocks = re.findall(
            r'<h2[^>]*>\s*<a[^>]*href="(/[^"]+)"[^>]*>.*?</a>\s*/\s*<a[^>]*href="(/[^"]+)"[^>]*>([^<]+)</a>\s*</h2>(.*?)(?=<h2[^>]*>|$)',
            html_body,
            re.DOTALL,
        )

        for org_path, repo_path, repo_name, rest in repo_blocks:
            full_name = f"{org_path.strip('/')}/{repo_path.strip('/')}"
            repo_name = repo_name.strip()
            repo_url = f"https://github.com/{full_name}"

            # Extract description
            desc_match = re.search(r'<p[^>]*class="[^"]*col-9[^"]*"[^>]*>(.*?)</p>', rest, re.DOTALL)
            description = re.sub(r"<[^>]+>", " ", desc_match.group(1)).strip() if desc_match else ""

            # Extract star count
            stars_match = re.search(r'(\d[\d,]*)\s+stars', rest, re.IGNORECASE)
            stars_today_match = re.search(r'(\d[\d,]*)\s+stars today', rest, re.IGNORECASE)
            stars = int(stars_match.group(1).replace(",", "")) if stars_match else 0
            stars_today = int(stars_today_match.group(1).replace(",", "")) if stars_today_match else 0

            # Filter: must relate to AI, agents, devtools, or our stack
            haystack = f"{repo_name} {full_name} {description}".lower()
            relevant_terms = {
                "ai", "agent", "llm", "claude", "codex", "hermes", "ollama",
                "mcp", "workflow", "memory", "rag", "skill", "plugin",
                "vibe", "open source", "framework", "devtool", "tool",
                "langchain", "langgraph", "autogen", "crew", "cursor",
                "supabase", "convex", "expo", "react native", "deepseek",
                "qwen", "moonshot", "gemini", "openai", "anthropic",
                "transformer", "vision", "video", "audio", "speech",
                "generative", "diffusion", "benchmark", "evaluation",
            }
            if not any(term in haystack for term in relevant_terms):
                continue

            candidates.append({
                "title": f"{full_name}: {description}" if description else full_name,
                "url": repo_url,
                "source": "github.com",
                "lane": LANE_C,
                "query": f"github-trending:{language}",
                "content": description,
                "search_score": 0.8 + min(0.2, math.log10(stars_today + 1) * 0.05) if stars_today else 0.8,
                "source_type": "github-trending",
                "points": stars,
                "comments": 0,
                "published": now.isoformat(),
                "feed_name": f"GH Trending {language}",
                "official_source": False,
            })

    return candidates


def collect_x_candidates(now: datetime | None = None) -> tuple[list[dict], list[dict]]:
    """Search X/Twitter for AI news, tool releases, and agent launches via xurl CLI."""
    candidates: list[dict] = []
    diagnostics: list[dict] = []
    now = now or datetime.now(ZoneInfo("Europe/London"))

    # Verify xurl is available
    try:
        subprocess.check_output(["which", "xurl"], stderr=subprocess.STDOUT, timeout=5)
    except (subprocess.CalledProcessError, FileNotFoundError):
        diagnostics.append({"status": "error", "query": "x-check", "lane": LANE_A, "message": "xurl CLI not available. Install with: curl -fsSL https://raw.githubusercontent.com/xdevplatform/xurl/main/install.sh | bash"})
        return candidates, diagnostics

    for topic in X_ACCOUNT_QUERIES:
        query = topic["query"]
        lane = topic["lane"]
        try:
            raw = subprocess.check_output(
                ["xurl", "search", query, "-n", str(X_RESULTS_PER_QUERY)],
                stderr=subprocess.STDOUT,
                timeout=30,
                env=os.environ.copy(),
            )
            data = json.loads(raw.decode("utf-8"))
        except subprocess.CalledProcessError as exc:
            raw_output = exc.output.decode("utf-8", errors="ignore") if exc.output else str(exc)
            # CreditsDepleted, rate limit, auth errors are common — report and skip
            try:
                err_data = json.loads(raw_output)
                err_msg = err_data.get("title", err_data.get("detail", raw_output[:200]))
            except (json.JSONDecodeError, AttributeError):
                err_msg = raw_output[:200]
            diagnostics.append({"status": "error", "query": query, "lane": lane, "message": err_msg})
            continue
        except Exception as exc:
            diagnostics.append({"status": "error", "query": query, "lane": lane, "message": str(exc)[:300]})
            continue

        # xurl search returns {"data": [...], "includes": {"users": [...]}}
        posts = data.get("data", [])
        users = {u["id"]: u for u in (data.get("includes", {}).get("users", []))}

        result_count = 0
        for post in posts:
            user_id = post.get("author_id", "")
            user = users.get(user_id, {})
            username = user.get("username", "unknown")
            author_name = user.get("name", username)
            text = post.get("text", "").strip()
            post_id = post.get("id", "")
            post_url = f"https://x.com/{username}/status/{post_id}" if username and post_id else ""
            created_at = post.get("created_at", now.isoformat())

            # Skip retweets/reposts
            if text.startswith("RT "):
                continue

            # Clean text content
            content = re.sub(r"\s+", " ", text[:500]).strip()
            title = text[:120].strip()

            candidates.append({
                "title": f"@{username}: {title}",
                "url": post_url,
                "source": "x.com",
                "lane": lane,
                "query": query,
                "content": content,
                "search_score": 0.85,
                "source_type": "x",
                "feed_name": f"X: {author_name} (@{username})",
                "official_source": False,
                "points": int(post.get("public_metrics", {}).get("like_count", 0) or 0),
                "comments": int(post.get("public_metrics", {}).get("reply_count", 0) or 0),
                "published": created_at,
            })
            result_count += 1

        diagnostics.append({"status": "ok", "query": query, "lane": lane, "results": result_count, "source": "xurl"})

    return candidates, diagnostics


def collect_candidates(max_results_per_query: int = 7, time_range: str = "week", include_rss: bool = True) -> tuple[list[dict], list[dict]]:
    env = command_env()
    diagnostics = []
    candidates = []
    now = datetime.now(ZoneInfo("Europe/London"))

    # GitHub trending — fast, no API key needed, catches repos before they hit RSS
    try:
        trending_candidates = collect_github_trending(now=now)
        candidates.extend(trending_candidates)
        diagnostics.append({"status": "ok", "query": "github-trending", "lane": LANE_C, "results": len(trending_candidates)})
    except Exception as exc:
        diagnostics.append({"status": "error", "query": "github-trending", "lane": LANE_C, "message": str(exc)[:300]})

    # X/Twitter — catches official announcements and launches hours before RSS
    try:
        x_candidates, x_diagnostics = collect_x_candidates(now=now)
        candidates.extend(x_candidates)
        diagnostics.extend(x_diagnostics)
    except Exception as exc:
        diagnostics.append({"status": "error", "query": "x-collect", "lane": LANE_A, "message": str(exc)[:300]})

    if not env.get("TAVILY_API_KEY"):
        diagnostics.append({"status": "error", "message": "TAVILY_API_KEY not available to subprocess env"})
    else:
        for topic in TOPIC_QUERIES:
            query = topic["query"]
            lane = topic["lane"]
            try:
                data = run_tavily_search(
                    query,
                    env,
                    max_results=max_results_per_query,
                    time_range=time_range,
                    include_domains=topic.get("include_domains"),
                    exclude_domains=topic.get("exclude_domains"),
                )
                results = data.get("results", [])
                # Filter Tavily results by publish date before adding to candidates
                filtered_results = [r for r in results if tavily_result_within_time_range(r, time_range, now)]
                removed_count = len(results) - len(filtered_results)
                diagnostics.append({
                    "status": "ok", 
                    "query": query, 
                    "lane": lane, 
                    "results": len(results),
                    "date_filtered": removed_count,
                    "kept": len(filtered_results),
                })
                for result in filtered_results:
                    item = normalise_tavily_result(result, lane, query)
                    if item["url"]:
                        candidates.append(item)
            except Exception as exc:  # pragma: no cover, only hit on live Tavily failures
                diagnostics.append({"status": "error", "query": query, "lane": lane, "message": str(exc)[:300]})

    if include_rss:
        rss_candidates, rss_diagnostics = collect_rss_candidates(max_items_per_feed=max_results_per_query, time_range=time_range)
        candidates.extend(rss_candidates)
        diagnostics.extend(rss_diagnostics)
    return candidates, diagnostics


def select_candidates(candidates: list[dict], limit: int = 5) -> list[dict]:
    prepared = []
    for candidate in candidates:
        candidate = dict(candidate)
        candidate.setdefault("source", source_from_url(candidate.get("url", "")))
        if is_excluded_candidate(candidate):
            continue
        prepared.append(candidate)

    deduped = dedupe_candidates(prepared)
    for candidate in deduped:
        candidate["final_score"] = score_candidate(candidate)

    deduped = [candidate for candidate in deduped if candidate["final_score"] >= MIN_SELECTED_SCORE]

    by_lane: dict[str, list[dict]] = {}
    for candidate in sorted(deduped, key=lambda item: item["final_score"], reverse=True):
        by_lane.setdefault(candidate.get("lane", "Other"), []).append(candidate)

    per_lane_max = 10  # generous cap — scoring does the real filtering
    lane_caps: dict[str, int] = {}  # no hard per-lane cap, score-based selection

    selected: list[dict] = []
    lane_counts: dict[str, int] = {}

    # First pass: pick top items per lane up to their cap
    for lane in LANE_ORDER:
        lane_items = by_lane.get(lane, [])
        cap = lane_caps.get(lane, per_lane_max)
        for item in lane_items[:cap]:
            if len(selected) < limit:
                selected.append(item)
                lane_counts[lane] = lane_counts.get(lane, 0) + 1

    # Second pass: fill remaining by score, but respect lane caps
    remaining = [item for lane_items in by_lane.values() for item in lane_items if item not in selected]
    for candidate in sorted(remaining, key=lambda item: item["final_score"], reverse=True):
        if len(selected) >= limit:
            break
        lane = candidate.get("lane", "Other")
        if lane_counts.get(lane, 0) >= lane_caps.get(lane, per_lane_max):
            continue
        selected.append(candidate)
        lane_counts[lane] = lane_counts.get(lane, 0) + 1

    return sorted(selected, key=lambda item: item["final_score"], reverse=True)


def summarise_item(item: dict, max_chars: int = 150) -> str:
    content = item.get("content", "").strip().replace("—", "-").replace("–", "-")
    if not content:
        return "High-signal source to review."
    content = re.sub(r"\s+", " ", content)
    if len(content) <= max_chars:
        return content
    cut = content[:max_chars].rsplit(" ", 1)[0]
    return cut.rstrip(".,") + "."


def truncate_text(value: str, max_chars: int) -> str:
    value = value.replace("—", "-").replace("–", "-")
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= max_chars:
        return value
    cut = value[: max_chars - 1].rsplit(" ", 1)[0].rstrip()
    return cut or value[: max_chars - 1].rstrip()


def grouped_selected(selected: list[dict]) -> dict[str, list[dict]]:
    grouped = {lane: [] for lane in LANE_ORDER}
    other = []
    for item in selected:
        lane = item.get("lane", "")
        if lane in grouped:
            grouped[lane].append(item)
        else:
            other.append(item)
    if other:
        grouped.setdefault("Other", []).extend(other)
    return grouped


def source_mix(payload: dict) -> str:
    source_types = set(payload.get("source_types") or [])
    if source_types == {"rss"}:
        return "RSS"
    if source_types == {"tavily"}:
        return "Tavily"
    if "rss" in source_types and "tavily" in source_types:
        return "RSS + Tavily"
    # Anything involving trending, tavily, or mixed
    parts = []
    if "rss" in source_types:
        parts.append("RSS")
    if "tavily" in source_types:
        parts.append("Tavily")
    if "github-trending" in source_types:
        parts.append("GH Trending")
    if "x" in source_types:
        parts.append("X")
    return " + ".join(parts) if parts else "Tavily/RSS"


def recommendation_for(selected: list[dict]) -> str:
    if not selected:
        return "Keep the Research Digest manual until Tavily returns useful candidates."
    top = selected[0]
    lane = top.get("lane", "")
    source = top.get("source", "")
    if lane == LANE_C or "Hermes" in lane or "nousresearch" in source:
        return "Review whether this changes KENSEI cron prompts, skills, or the Morning Brief runbook."
    if lane == LANE_B or "Coding agents" in lane or "Codex" in lane or "Claude" in lane:
        return "Check whether the coding-agent workflow needs a skill or model-routing tweak."
    if lane == LANE_A or "Model" in lane or "Ollama" in lane or "Qwen" in lane or "Kimi" in lane:
        return "Probe live model availability before changing worker defaults."
    return "Turn the highest-signal item into one small KENSEI workflow improvement if it survives review."


def telegram_text(payload: dict, html_path: Path, include_media_tag: bool = False) -> str:
    selected = payload.get("selected", [])
    min_signal_count = int(payload.get("min_signal_count") or 1)
    if not selected or len(selected) < min_signal_count or payload.get("silent"):
        return "[SILENT]"

    generated = datetime.fromisoformat(payload["generated_at"])
    ts = generated.strftime("%a %d %b · %H:%M")

    grouped = grouped_selected(selected)
    lane_counts = {lane: len(items) for lane, items in grouped.items() if items}

    lines = [
        f"📰 <b>Research brief</b> · {ts}",
        f"{len(selected)} signals · {source_mix(payload)}",
        "",
    ]

    for lane in LANE_ORDER:
        items = grouped.get(lane, [])
        if not items:
            continue
        lines.append(f"<b>{LANE_LABELS.get(lane, lane)}</b>")
        for item in items[:3]:
            summary = summarise_item(item, 120)
            lines.append(f"• <a href=\"{item.get('url', '')}\">{item.get('title', '?')}</a> — {summary}")
        if len(items) > 3:
            lines.append(f"• +{len(items) - 3} more in full report")
        lines.append("")

    lines.append("<b>Full report</b>")
    lines.append(f"<code>{html_path}</code>")
    lines.append("")
    lines.append(f"MEDIA:{html_path}")

    text = "\n".join(lines)
    if len(text) <= 1400:
        return text

    compact = [
        f"📰 <b>Research brief</b> · {ts}",
        f"{len(selected)} signals · {source_mix(payload)}",
        "",
        "<b>Findings</b>",
    ]
    for lane in LANE_ORDER:
        items = grouped.get(lane, [])
        for item in items[:2]:
            compact.append(f"• <a href=\"{item.get('url', '')}\">{item.get('title', '?')}</a>")
    compact.extend(["", "<b>Full report</b>", f"<code>{html_path}</code>", "", f"MEDIA:{html_path}"])
    return "\n".join(compact)

def markdown_text(payload: dict, html_path: Path) -> str:
    selected = payload.get("selected", [])
    lines = [
        f"# Research Digest, {payload['date_label']}",
        "",
        f"Generated: {payload['generated_at']}",
        f"Candidates considered: {payload['candidates_considered']}",
        f"Sources considered: {payload['sources_considered']}",
        f"HTML artifact: `{html_path}`",
        "",
        "## Signals by lane",
        "",
    ]
    if not selected:
        lines.append("No high-signal research items found.")
    idx = 1
    for lane, items in grouped_selected(selected).items():
        if not items:
            continue
        lines.extend([f"## {LANE_LABELS.get(lane, lane)}", ""])
        for item in items:
            lines.extend(
                [
                    f"### {idx}. {item['title']}",
                    "",
                    f"- Source: [{item['source']}]({item['url']})",
                    f"- Lane: {item['lane']}",
                    f"- Score: {item.get('final_score', 0)}",
                    f"- Why it matters: {summarise_item(item, 320)}",
                    "",
                ]
            )
            idx += 1
    lines.extend(["## Practical recommendation", "", recommendation_for(selected), ""])
    return "\n".join(lines)


def html_text(payload: dict) -> str:
    selected = payload.get("selected", [])
    cards = []
    rank = 1
    for lane, items in grouped_selected(selected).items():
        if not items:
            continue
        cards.append(f"<section class=\"lane\"><h2>{html.escape(LANE_LABELS.get(lane, lane))}</h2>")
        for item in items:
            cards.append(
                f"""
                <article class="card">
                  <div class="meta">#{rank} · {html.escape(item.get('source', 'source'))}</div>
                  <h3>{html.escape(item.get('title', 'Untitled'))}</h3>
                  <p>{html.escape(summarise_item(item, 360))}</p>
                  <a href="{html.escape(item.get('url', ''))}">Read source</a>
                </article>
                """
            )
            rank += 1
        cards.append("</section>")
    if not cards:
        cards.append("<article class=\"card\"><h2>No high-signal items</h2><p>Tavily returned no useful candidates.</p></article>")

    freshness = "last 24 hours" if payload.get("time_range_used") == "day" else "last 24 hours, with 7-day fallback"
    recommendation = recommendation_for(selected)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Research Digest, {html.escape(payload['date_label'])}</title>
  <style>
    :root {{ color-scheme: dark; --bg: #11100f; --panel: #1c1a18; --muted: #a8a29e; --text: #f5f5f4; --accent: #fbbf24; --line: #34302c; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: radial-gradient(circle at top left, #2c2a28, var(--bg)); color: var(--text); font: 16px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ width: min(940px, calc(100% - 32px)); margin: 0 auto; padding: 32px 0 48px; }}
    header {{ margin-bottom: 24px; }}
    .eyebrow {{ color: var(--accent); font-weight: 700; letter-spacing: .08em; text-transform: uppercase; font-size: 13px; }}
    h1 {{ font-size: clamp(34px, 6vw, 64px); line-height: .95; margin: 10px 0; }}
    .summary {{ color: var(--muted); max-width: 720px; }}
    .grid {{ display: grid; gap: 16px; }}
    .card {{ background: color-mix(in srgb, var(--panel) 92%, transparent); border: 1px solid var(--line); border-radius: 20px; padding: 20px; box-shadow: 0 16px 48px rgba(0,0,0,.22); }}
    .lane {{ display: grid; gap: 14px; }}
    .lane h2 {{ margin: 8px 0 0; color: var(--accent); font-size: 18px; }}
    .card h2, .card h3 {{ margin: 8px 0 10px; font-size: 22px; }}
    .card p {{ color: #d6d3d1; }}
    .meta {{ color: var(--muted); font-size: 13px; }}
    a {{ color: var(--accent); word-break: break-word; }}
    .recommendation {{ margin-top: 18px; border-color: color-mix(in srgb, var(--accent) 55%, var(--line)); }}
  </style>
</head>
<body>
  <main>
    <header>
      <div class="eyebrow">KENSEI AI/Agent Brief</div>
      <h1>{html.escape(payload['date_label'])}</h1>
      <p class="summary">A clean source-backed brief for Sahil. Freshness window: {html.escape(freshness)}. Stale RSS items are rejected before ranking.</p>
    </header>
    <section class="grid">
      {''.join(cards)}
      <article class="card recommendation">
        <div class="meta">Practical recommendation</div>
        <h2>Next move</h2>
        <p>{html.escape(recommendation)}</p>
      </article>
    </section>
  </main>
</body>
</html>
"""


def render_digest(payload: dict, out_dir: Path, include_media_tag: bool = False) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = output_paths(out_dir)
    markdown = markdown_text(payload, paths.html_path)
    html_doc = html_text(payload)
    telegram = telegram_text(payload, paths.html_path, include_media_tag=include_media_tag)

    paths.markdown_path.write_text(markdown, encoding="utf-8")
    paths.html_path.write_text(html_doc, encoding="utf-8")
    paths.telegram_path.write_text(telegram, encoding="utf-8")
    return {"telegram": telegram, "markdown": markdown, "html": html_doc}


def build_payload(selected: list[dict], candidates: list[dict], diagnostics: list[dict], now: datetime, time_range_used: str, min_signal_count: int = 1) -> dict:
    source_types = sorted({item.get("source_type", "tavily") for item in candidates})
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "date_label": now.strftime("%A %-d %B"),
        "time_range_used": time_range_used,
        "query_count": len(TOPIC_QUERIES),
        "rss_source_count": len(RSS_SOURCES),
        "candidates_considered": len(candidates),
        "sources_considered": len({item.get("source") for item in candidates if item.get("source")}),
        "source_types": source_types,
        "min_signal_count": min_signal_count,
        "silent": len(selected) < min_signal_count,
        "selected": selected,
        "diagnostics": diagnostics,
        "all_candidates": candidates,
    }


def run(
    out_dir: Path | None = None,
    max_results_per_query: int = 7,
    selected_limit: int = 5,
    time_range: str = "day",
    fallback_time_range: str | None = "week",
    min_selected_before_fallback: int = 3,
    include_media_tag: bool = False,
) -> tuple[dict, OutputPaths, dict[str, str]]:
    now = datetime.now(ZoneInfo("Europe/London"))
    out_dir = out_dir or default_output_dir(now)
    paths = output_paths(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates, diagnostics = collect_candidates(max_results_per_query=max_results_per_query, time_range=time_range)
    selected = select_candidates(candidates, limit=selected_limit)
    time_range_used = time_range
    if fallback_time_range and fallback_time_range != time_range and len(selected) < min_selected_before_fallback:
        fallback_candidates, fallback_diagnostics = collect_candidates(
            max_results_per_query=max_results_per_query,
            time_range=fallback_time_range,
        )
        candidates = fallback_candidates
        diagnostics.append({"status": "info", "message": f"Expanded search from {time_range} to {fallback_time_range} because only {len(selected)} selected items passed filters."})
        diagnostics.extend(fallback_diagnostics)
        selected = select_candidates(candidates, limit=selected_limit)
        time_range_used = f"{time_range} + {fallback_time_range} fallback"

    payload = build_payload(selected, candidates, diagnostics, now, time_range_used, min_signal_count=min_selected_before_fallback)
    paths.json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    rendered = render_digest(payload, out_dir, include_media_tag=include_media_tag)
    return payload, paths, rendered


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect and render KENSEI Research Digest")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--max-results-per-query", type=int, default=7)
    parser.add_argument("--selected-limit", type=int, default=10)
    parser.add_argument("--time-range", default="day", choices=["day", "week", "month", "year"])
    parser.add_argument("--fallback-time-range", default="week", choices=["none", "day", "week", "month", "year"])
    parser.add_argument("--min-selected-before-fallback", type=int, default=3)
    parser.add_argument("--print-telegram", action="store_true")
    parser.add_argument("--include-media-tag", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    fallback_time_range = None if args.fallback_time_range == "none" else args.fallback_time_range
    payload, paths, rendered = run(
        out_dir=args.out_dir,
        max_results_per_query=args.max_results_per_query,
        selected_limit=args.selected_limit,
        time_range=args.time_range,
        fallback_time_range=fallback_time_range,
        min_selected_before_fallback=args.min_selected_before_fallback,
        include_media_tag=args.include_media_tag,
    )
    if args.print_telegram:
        print(rendered["telegram"])
    else:
        print(f"Research Digest generated: {paths.directory}")
        print(f"Candidates: {payload['candidates_considered']} | Sources: {payload['sources_considered']} | Selected: {len(payload['selected'])}")
        print(f"JSON: {paths.json_path}")
        print(f"Markdown: {paths.markdown_path}")
        print(f"HTML: {paths.html_path}")
        print(f"Telegram: {paths.telegram_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
