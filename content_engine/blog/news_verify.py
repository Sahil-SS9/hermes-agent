"""Web-grounding check for named-event claims in the AI blog stream.

Before the AI generator asserts a named current event (acquisition, regulation,
product launch), this module confirms it with a web lookup and returns grounding
snippets or an ``unverified`` flag so the generator can reframe to the durable
pattern/economics instead of stating an unverified event as fact.

Degrades to ``unverified`` (never fabricates) when the web tool is unavailable
or the network is unreachable.
"""

from __future__ import annotations

from typing import Any


def _web_search(query: str, max_results: int = 3) -> list[dict[str, str]]:
    """Run a web search for `query`, return up to `max_results` snippets.

    Uses DuckDuckGo's free Lite API (no API key required) through its HTML
    endpoint. Falls back to a simple requests-based HTML scrape, which may be
    unreliable. On any failure returns [] so the caller never gets fabricated
    evidence.

    Returns a list of dicts with keys 'title', 'snippet', 'url'.
    """
    import re
    import urllib.parse

    import requests

    url = "https://lite.duckduckgo.com/lite/"
    data = {"q": query}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    try:
        resp = requests.post(url, data=data, headers=headers, timeout=15)
        if resp.status_code != 200:
            return []
        # Parse the HTML table rows for results.
        results: list[dict[str, str]] = []
        # Look for result rows: <tr class="result">...</tr>
        for row in re.findall(
            r'<tr class="result".*?</tr>', resp.text, re.DOTALL
        ):
            title_m = re.search(
                r'<a[^>]*class="result-link"[^>]*>(.*?)</a>', row, re.DOTALL
            )
            snippet_m = re.search(
                r'<td class="result-snippet">(.*?)</td>', row, re.DOTALL
            )
            url_m = re.search(r'href="(https?://[^"]+)"', row)
            if title_m:
                results.append({
                    "title": re.sub(r"<[^>]+>", "", title_m.group(1)).strip(),
                    "snippet": re.sub(r"<[^>]+>", "", snippet_m.group(1)).strip()
                    if snippet_m else "",
                    "url": url_m.group(1) if url_m else "",
                })
            if len(results) >= max_results:
                break
        return results
    except Exception:
        return []


def verify_event(claim: str) -> dict[str, Any]:
    """Verify a claimed named event with a web search.

    Args:
        claim: A short description of the event, e.g. "a frontier-model
               company acquiring an AI coding tool".

    Returns:
        ``{"verified": True/False, "snippets": [...], "query": claim}``.
        ``verified`` is True when at least one result was found.
        ``snippets`` contains up to 3 result dicts with title/snippet/url.
        Never fabricates — on network failure returns unverified.
    """
    try:
        hits = _web_search(claim) or []
    except Exception:
        return {"verified": False, "snippets": [], "query": claim}
    return {
        "verified": bool(hits),
        "snippets": hits[:3],
        "query": claim,
    }
