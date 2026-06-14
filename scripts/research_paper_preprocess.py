#!/usr/bin/env python3
"""
Research Paper Pre-processing Script — Phase 3
Offloads 4-API fetching + dedup + pre-scoring from LLM to deterministic Python.

Outputs structured JSON to stdout. The LLM cron receives only the filtered
candidate list (~10-15 papers) instead of raw API output, cutting token usage ~60%.

Usage:
  python3 research_paper_preprocess.py [--days 14] [--output scored.json]

Integration:
  Add as `script: research_paper_preprocess.py` on cron job 823708309a8e.
  Script stdout is injected as context for the LLM's scoring + cross-referencing pass.
"""

import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from urllib.parse import quote

# ── Config ──────────────────────────────────────────────────────────────────
ATOM_NS = "http://www.w3.org/2005/Atom"
CUTOFF_DAYS = int(os.environ.get("PAPER_CUTOFF_DAYS", "14"))
MAX_CANDIDATES = int(os.environ.get("PAPER_MAX_CANDIDATES", "30"))
OUTPUT_PATH = os.environ.get("PAPER_OUTPUT", "")
SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_DIR = SCRIPT_DIR / ".paper_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── arXiv Category Queries ──────────────────────────────────────────────────
ARXIV_QUERIES = {
    "ai": "cat:cs.AI",
    "cl": "cat:cs.CL",
    "lg": "cat:cs.LG",
    "se": "cat:cs.SE",
    "hc": "cat:cs.HC",
    "kw1": 'all:"coding agent" OR all:"LLM agent" OR all:"MCP server" OR all:"tool calling" OR all:"context window"',
    "kw2": 'all:"agent memory" OR all:"prompt engineering" OR all:"agent orchestration" OR all:"AI workflow" OR all:"local LLM"',
}

# ── Tight Scoring Phrases (v2.1.1 — calibrated for precision) ──────────────
# Score 5: Direct stack match — exact phrases only
S5_PHRASES = [
    "mcp server", "mcp-style", "tool calling", "tool-augmented agent",
    "executable tool workflow", "tool workflow", "hyper tool",
    "context compression", "end-to-end context compression",
    "long-term agent memory", "agent memory", "graph memory",
    "selection integrity", "accumulability", "information-flow",
    "runtime enforcement", "runtime governance", "runtime memory poisoning",
    "shield synthesis", "defensibility analysis",
    "prompt injection", "red-teaming", "pi-hunter",
    "instructions-as-code", "instruction files on agentic",
    "recursive agent harness", "agent harness", "openclaw", "claw-swe",
    "delegation intelligence", "delegate intelligence",
    "multi-agent orchestration", "reward modeling for multi-agent",
    "skill self-evolution", "skill evolution", "skillcat",
    "agentic pull request", "agentic pr ", "agentic pull-request",
    "agent-native", "agent-native knowledge",
    "memory poisoning", "persistent llm agent",
    "compact agent", "inference-time evolution of executable tool",
]

# Score 4: Strong relevance, adjacent to stack
S4_PHRASES = [
    "rag ", "retrieval augmented", "fine-tuning", "prompt engineering",
    "code generation benchmark", "code review agent", "coding agent benchmark",
    "adversarial testing", "adversarial code", "adversarial",
    "llm evaluation", "llm benchmark", "agent benchmark",
    "ai-native software engineering", "ai workflow",
    "knowledge graph", "vector search", "reasoning enhanced",
    "tool-use", "tool use", "function calling",
    "agent framework", "agent platform", "agent system",
    "context management", "context retention",
    "code generation", "code synthesis",
]

# Score 3: Broader AI/ML relevance
S3_PHRASES = [
    "large language model", "transformer", "attention mechanism",
    "synthetic data", "distillation", "quantization",
    "reinforcement learning", "reasoning",
    "neural network", "deep learning",
    "natural language processing",
    "multi-modal", "multimodal",
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def fetch_url(url: str, timeout: int = 15) -> str | None:
    """Fetch a URL with basic retry. Returns body text or None."""
    for attempt in range(2):
        try:
            req = Request(url, headers={"User-Agent": "KenseiResearch/1.0"})
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, OSError) as e:
            if attempt == 0:
                time.sleep(2)
                continue
            print(f"  [WARN] Failed to fetch {url[:60]}: {e}", file=sys.stderr)
            return None
    return None


def parse_arxiv_id(text: str) -> str | None:
    """Extract arXiv ID from various formats."""
    text = text.strip()
    # Raw ID: "2606.00467" or "2606.00467v2"
    if text.replace(".", "").replace("v", "").isdigit() and len(text) >= 8:
        return text.split("v")[0]
    # URL: https://arxiv.org/abs/2606.00467
    if "/abs/" in text:
        return text.split("/abs/")[-1].split("v")[0]
    if "/pdf/" in text:
        return text.split("/pdf/")[-1].split(".pdf")[0].split("v")[0]
    return None


def tight_score(title: str, summary: str) -> int:
    """Two-pass scoring: exact phrases only. Returns 1-5."""
    text = (title + " " + summary).lower()

    # Pass 1: Score 5 — direct stack match
    for phrase in S5_PHRASES:
        if phrase in text:
            return 5

    # Pass 2: Score 4 — strong relevance
    for phrase in S4_PHRASES:
        if phrase in text:
            return 4

    # Pass 3: Score 3 — broader AI
    for phrase in S3_PHRASES:
        if phrase in text:
            return 3

    return 1


# ── Phase 1A: Fetch arXiv ───────────────────────────────────────────────────

def fetch_arxiv() -> list[dict]:
    """Fetch papers from arXiv API for all configured queries."""
    papers: dict[str, dict] = {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=CUTOFF_DAYS)

    for label, query in ARXIV_QUERIES.items():
        url = (
            f"https://export.arxiv.org/api/query?"
            f"search_query={quote(query)}&sortBy=submittedDate&sortOrder=descending"
            f"&max_results=30"
        )
        print(f"  [arXiv] Fetching {label}...", file=sys.stderr)
        body = fetch_url(url)
        if not body:
            continue

        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            continue

        for entry in root.findall(f"{{{ATOM_NS}}}entry"):
            _id = entry.find(f"{{{ATOM_NS}}}id")
            _title = entry.find(f"{{{ATOM_NS}}}title")
            _summary = entry.find(f"{{{ATOM_NS}}}summary")
            _published = entry.find(f"{{{ATOM_NS}}}published")

            arxiv_id = parse_arxiv_id(_id.text or "") if _id is not None else None
            if not arxiv_id or arxiv_id in papers:
                continue

            title = (_title.text or "").strip() if _title is not None else ""
            summary = (_summary.text or "").strip() if _summary is not None else ""
            published = (_published.text or "").strip() if _published is not None else ""

            if not title or not summary:
                continue

            try:
                pub_date = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                pub_date = datetime.now(timezone.utc)

            if pub_date < cutoff:
                continue

            score = tight_score(title, summary)
            if score < 2:
                continue

            papers[arxiv_id] = {
                "arxiv_id": arxiv_id,
                "title": title,
                "summary": summary[:500],
                "published": published,
                "score": score,
                "source": "arxiv",
                "url": f"https://arxiv.org/abs/{arxiv_id}",
            }

    return list(papers.values())


# ── Phase 1C: HuggingFace Daily Papers ──────────────────────────────────────

def fetch_hf_daily(papers: list[dict]) -> list[dict]:
    """Cross-reference HuggingFace Daily Papers against arXiv pool."""
    print("  [HF Daily] Fetching...", file=sys.stderr)
    body = fetch_url("https://huggingface.co/api/daily_papers?limit=30")
    if not body:
        return papers

    try:
        hf_papers = json.loads(body)
    except json.JSONDecodeError:
        return papers

    existing_ids = {p["arxiv_id"] for p in papers}

    for p in hf_papers:
        paper_data = p.get("paper", {})
        paper_id = paper_data.get("id", "")
        arxiv_id = parse_arxiv_id(paper_id)
        if not arxiv_id:
            continue

        title = paper_data.get("title", "")
        summary = paper_data.get("summary", "") or paper_data.get("abstract", "")

        if arxiv_id in existing_ids:
            # Mark existing paper as HF-featured
            for paper in papers:
                if paper["arxiv_id"] == arxiv_id:
                    paper["hf_featured"] = True
                    paper["hf_upvotes"] = p.get("upvotes", 0)
                    break
        else:
            # New paper from HF Daily not in arXiv results
            score = tight_score(title, summary)
            if score >= 2:
                papers.append({
                    "arxiv_id": arxiv_id,
                    "title": title,
                    "summary": summary[:500],
                    "published": paper_data.get("publishedAt", ""),
                    "score": score,
                    "source": "hf-daily",
                    "hf_featured": True,
                    "hf_upvotes": p.get("upvotes", 0),
                    "url": f"https://arxiv.org/abs/{arxiv_id}",
                })
                existing_ids.add(arxiv_id)

    return papers


# ── Phase 1D: Papers With Code (opportunistic) ─────────────────────────────

def fetch_pwc(papers: list[dict]) -> list[dict]:
    """Check Papers With Code for score >= 3 papers."""
    print("  [PwC] Checking top papers...", file=sys.stderr)
    for paper in papers:
        if paper["score"] < 3:
            continue
        url = f"https://paperswithcode.com/api/v1/papers/?arxiv_id={paper['arxiv_id']}"
        body = fetch_url(url, timeout=10)
        if not body:
            continue
        try:
            data = json.loads(body)
            results = data.get("results", [])
            if results:
                paper["pwc_repo"] = results[0].get("repository_url", "")
                paper["pwc_stars"] = results[0].get("stars", 0)
        except (json.JSONDecodeError, KeyError):
            pass

    return papers


# ── Scoring with Quality Weight (v2.1.1 — less harsh on new papers) ──────────

def apply_final_score(paper: dict) -> dict:
    """Apply quality weight + implementation multiplier to base relevance score.

    v2.1.1 changes from v2.1.0:
    - 0-2 citations with no HF/venue: weight raised from 0.3 to 0.5
      (brand-new papers shouldn't be penalised to Skip tier immediately)
    - 3-10 citations: weight raised from 0.5 to 0.6
    - Added recency boost: +0.1 weight for papers published in last 3 days
      (only applied if base score >= 4, prevents marginal papers from inflating)
    """
    base = paper["score"]
    qw = 0.7  # default fallback

    # Quality weight from HF featured status
    if paper.get("hf_featured"):
        qw = 0.8
        if paper.get("hf_upvotes", 0) > 50:
            qw = 0.9

    # Recency boost: +0.1 for papers <3 days old with base score >= 4
    try:
        pub = datetime.fromisoformat(paper["published"].replace("Z", "+00:00"))
        age_hours = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
        if age_hours < 72 and base >= 4:
            qw = min(qw + 0.1, 1.0)
    except (ValueError, KeyError):
        pass

    # Implementation multiplier
    impl = 1.0
    if paper.get("pwc_repo"):
        stars = paper.get("pwc_stars", 0)
        if stars >= 500:
            impl = 1.25
        elif stars >= 50:
            impl = 1.2
        else:
            impl = 1.1

    final = base * qw * impl
    paper["quality_weight"] = round(qw, 2)
    paper["impl_multiplier"] = impl
    paper["final_score"] = round(final, 2)

    # Thresholds
    if final >= 5.5:
        paper["action"] = "write_now"
    elif final >= 3.0:
        paper["action"] = "ask_first"
    elif final >= 1.5:
        paper["action"] = "file"
    else:
        paper["action"] = "skip"

    return paper


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("[paper-preprocess] Phase 3: Fetching + scoring papers", file=sys.stderr)
    print(f"[paper-preprocess] Cutoff: {CUTOFF_DAYS} days, max candidates: {MAX_CANDIDATES}", file=sys.stderr)

    # Phase 1A: arXiv
    papers = fetch_arxiv()
    print(f"  → {len(papers)} papers from arXiv", file=sys.stderr)

    # Phase 1C: HF Daily cross-ref
    papers = fetch_hf_daily(papers)
    print(f"  → {len(papers)} after HF Daily cross-ref", file=sys.stderr)

    # Phase 1D: Papers With Code (opportunistic)
    papers = fetch_pwc(papers)
    print(f"  → {len(papers)} after PwC check", file=sys.stderr)

    # Apply final scoring
    for p in papers:
        p = apply_final_score(p)

    # Sort by final score descending
    papers.sort(key=lambda p: p["final_score"], reverse=True)

    # Filter to actionable candidates
    candidates = [p for p in papers if p["action"] != "skip"]
    candidates = candidates[:MAX_CANDIDATES]

    # Summary
    actions = {}
    for p in candidates:
        actions.setdefault(p["action"], 0)
        actions[p["action"]] += 1

    print(f"\n[paper-preprocess] Candidates: {len(candidates)}", file=sys.stderr)
    for action, count in sorted(actions.items()):
        print(f"  {action}: {count}", file=sys.stderr)

    # Output JSON to stdout (this is what the cron captures)
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_fetched": len(papers),
        "candidates": candidates,
        "summary": {
            "write_now": actions.get("write_now", 0),
            "ask_first": actions.get("ask_first", 0),
            "file": actions.get("file", 0),
        },
    }

    json.dump(output, sys.stdout, indent=2, ensure_ascii=False)

    # Also write to file if OUTPUT_PATH set
    if OUTPUT_PATH:
        out_path = Path(OUTPUT_PATH)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"\n[paper-preprocess] Written to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
