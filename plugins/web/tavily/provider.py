"""Tavily web search + content extraction — plugin form.

Subclasses :class:`agent.web_search_provider.WebSearchProvider`. Two
capabilities advertised:

- ``supports_search()``  -> True (Tavily ``/search``)
- ``supports_extract()`` -> True (Tavily ``/extract``)

Both are sync — the underlying call is ``httpx.post(...)``.

Config keys this provider responds to::

    web:
      search_backend: "tavily"     # explicit per-capability
      extract_backend: "tavily"    # explicit per-capability
      backend: "tavily"            # shared fallback for both

Env vars::

    TAVILY_API_KEY=...           # https://app.tavily.com/home (required)
    TAVILY_BASE_URL=...          # optional override of https://api.tavily.com
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)

# ── Cooldown state ──────────────────────────────────────────────────────────
# After 3 consecutive 4xx failures, Tavily is skipped for 24 hours to stop
# log spam and retry traffic when the API key is rate-limited or expired.

_HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
_COOLDOWN_FILE = _HERMES_HOME / "state" / "tavily_cooldown.json"
_MAX_CONSECUTIVE_FAILURES = 3
_COOLDOWN_SECONDS = 24 * 3600  # 24 hours


def _check_cooldown() -> bool:
    """Return True when Tavily is in cooldown and should be skipped.

    Skips are transparent to the caller — the provider returns a
    fallback-eligible response immediately so the dispatcher routes to
    the next backend without an actual API call.
    """
    try:
        if not _COOLDOWN_FILE.exists():
            return False
        state = json.loads(_COOLDOWN_FILE.read_text(encoding="utf-8"))
        if not state.get("in_cooldown", False):
            return False
        elapsed = time.time() - state.get("cooldown_started", 0)
        if elapsed >= _COOLDOWN_SECONDS:
            # Cooldown expired — reset and let Tavily try again.
            state["in_cooldown"] = False
            state["consecutive_failures"] = 0
            _COOLDOWN_FILE.write_text(json.dumps(state), encoding="utf-8")
            logger.info("Tavily cooldown expired, will try again")
            return False
        remaining_h = (_COOLDOWN_SECONDS - elapsed) / 3600
        logger.info(
            "Tavily in cooldown (%.1f h remaining); skipping to fallback",
            remaining_h,
        )
        return True
    except Exception as exc:
        logger.debug("Tavily cooldown check failed: %s", exc)
        return False


def _record_failure() -> None:
    """Increment the consecutive-failure counter.

    When the counter reaches ``_MAX_CONSECUTIVE_FAILURES`` the 24-hour
    cooldown is activated.
    """
    try:
        _COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        state: dict = {"consecutive_failures": 0, "in_cooldown": False, "cooldown_started": 0}
        if _COOLDOWN_FILE.exists():
            state.update(json.loads(_COOLDOWN_FILE.read_text(encoding="utf-8")))
        state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1
        if state["consecutive_failures"] >= _MAX_CONSECUTIVE_FAILURES:
            state["in_cooldown"] = True
            state["cooldown_started"] = time.time()
            logger.warning(
                "Tavily: %d consecutive failures — entering 24 h cooldown",
                state["consecutive_failures"],
            )
        _COOLDOWN_FILE.write_text(json.dumps(state), encoding="utf-8")
    except Exception as exc:
        logger.debug("Tavily failure-counter update failed: %s", exc)


def _record_success() -> None:
    """Reset the consecutive-failure counter on a successful API call."""
    try:
        if _COOLDOWN_FILE.exists():
            state = json.loads(_COOLDOWN_FILE.read_text(encoding="utf-8"))
            if int(state.get("consecutive_failures", 0)) > 0:
                state["consecutive_failures"] = 0
                _COOLDOWN_FILE.write_text(json.dumps(state), encoding="utf-8")
    except Exception as exc:
        logger.debug("Tavily success-counter reset failed: %s", exc)


# ── Core request helpers (unchanged) ────────────────────────────────────────


def _tavily_request(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST to the Tavily API and return the parsed JSON response.

    Mirrors :func:`tools.web_tools._tavily_request`. Raises ``ValueError``
    when ``TAVILY_API_KEY`` is unset; the caller catches and surfaces as
    a typed error response.
    """
    import httpx

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise ValueError(
            "TAVILY_API_KEY environment variable not set. "
            "Get your API key at https://app.tavily.com/home"
        )

    base_url = os.getenv("TAVILY_BASE_URL", "https://api.tavily.com")
    payload = dict(payload)  # don't mutate caller's dict
    payload["api_key"] = api_key
    url = f"{base_url}/{endpoint.lstrip('/')}"
    logger.info("Tavily %s request to %s", endpoint, url)

    response = httpx.post(url, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def _status_code_from_exception(exc: Exception) -> Optional[int]:
    """Return an HTTP status code from an httpx-style exception, if present."""
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    return None


def _is_4xx(exc: Exception) -> bool:
    """Return True when the exception wraps a 4xx HTTP status."""
    code = _status_code_from_exception(exc)
    return isinstance(code, int) and 400 <= code < 500


def _tavily_error_response(operation: str, exc: Exception) -> Dict[str, Any]:
    """Build a provider error payload that the web dispatcher can fail over."""
    status_code = _status_code_from_exception(exc)
    error = f"Tavily {operation} failed: {exc}"
    payload: Dict[str, Any] = {"success": False, "error": error}
    if status_code is not None:
        payload["status_code"] = status_code
        payload["provider"] = "tavily"
        payload["fallback_eligible"] = 400 <= status_code < 500
    return payload


def _normalize_tavily_search_results(response: Dict[str, Any]) -> Dict[str, Any]:
    """Map Tavily ``/search`` response to ``{success, data: {web: [...]}}``."""
    web_results = []
    for i, result in enumerate(response.get("results", [])):
        web_results.append(
            {
                "title": result.get("title", ""),
                "url": result.get("url", ""),
                "description": result.get("content", ""),
                "position": i + 1,
            }
        )
    return {"success": True, "data": {"web": web_results}}


def _normalize_tavily_documents(
    response: Dict[str, Any], fallback_url: str = ""
) -> List[Dict[str, Any]]:
    """Map Tavily ``/extract`` response to standard documents.

    Documents follow the legacy LLM post-processing shape::

        {"url", "title", "content", "raw_content", "metadata"}

    Failures (``failed_results``, ``failed_urls``) become result entries
    with an ``error`` field rather than raising.
    """
    documents: List[Dict[str, Any]] = []
    for result in response.get("results", []):
        url = result.get("url", fallback_url)
        raw = result.get("raw_content", "") or result.get("content", "")
        documents.append(
            {
                "url": url,
                "title": result.get("title", ""),
                "content": raw,
                "raw_content": raw,
                "metadata": {"sourceURL": url, "title": result.get("title", "")},
            }
        )
    for fail in response.get("failed_results", []):
        documents.append(
            {
                "url": fail.get("url", fallback_url),
                "title": "",
                "content": "",
                "raw_content": "",
                "error": fail.get("error", "extraction failed"),
                "metadata": {"sourceURL": fail.get("url", fallback_url)},
            }
        )
    for fail_url in response.get("failed_urls", []):
        url_str = fail_url if isinstance(fail_url, str) else str(fail_url)
        documents.append(
            {
                "url": url_str,
                "title": "",
                "content": "",
                "raw_content": "",
                "error": "extraction failed",
                "metadata": {"sourceURL": url_str},
            }
        )
    return documents


# ── Provider class ──────────────────────────────────────────────────────────


class TavilyWebSearchProvider(WebSearchProvider):
    """Tavily search + extract provider."""

    @property
    def name(self) -> str:
        return "tavily"

    @property
    def display_name(self) -> str:
        return "Tavily"

    def is_available(self) -> bool:
        """Return True when ``TAVILY_API_KEY`` is set to a non-empty value."""
        return bool(os.getenv("TAVILY_API_KEY", "").strip())

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return True

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Execute a Tavily search."""
        # Short-circuit if we're in cooldown — don't waste an API call.
        if _check_cooldown():
            return {
                "success": False,
                "error": "Tavily rate-limited (cooldown)",
                "status_code": 432,
                "provider": "tavily",
                "fallback_eligible": True,
            }

        try:
            from tools.interrupt import is_interrupted

            if is_interrupted():
                return {"success": False, "error": "Interrupted"}

            logger.info("Tavily search: '%s' (limit=%d)", query, limit)
            raw = _tavily_request(
                "search",
                {
                    "query": query,
                    "max_results": min(limit, 20),
                    "include_raw_content": False,
                    "include_images": False,
                },
            )
            _record_success()
            return _normalize_tavily_search_results(raw)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 — including httpx errors
            logger.warning("Tavily search error: %s", exc)
            if _is_4xx(exc):
                _record_failure()
            return _tavily_error_response("search", exc)

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        """Extract content from one or more URLs via Tavily.

        Sync — the underlying call is httpx.post(...). Returns the legacy
        list-of-results shape; per-URL failures become items with ``error``.
        """
        # Short-circuit if we're in cooldown.
        if _check_cooldown():
            return [
                {
                    "url": u,
                    "title": "",
                    "content": "",
                    "error": "Tavily rate-limited (cooldown)",
                    "status_code": 432,
                    "provider": "tavily",
                    "fallback_eligible": True,
                }
                for u in urls
            ]

        try:
            from tools.interrupt import is_interrupted

            if is_interrupted():
                return [
                    {"url": u, "error": "Interrupted", "title": ""} for u in urls
                ]

            logger.info("Tavily extract: %d URL(s)", len(urls))
            raw = _tavily_request(
                "extract",
                {
                    "urls": urls,
                    "include_images": False,
                },
            )
            _record_success()
            return _normalize_tavily_documents(
                raw, fallback_url=urls[0] if urls else ""
            )
        except ValueError as exc:
            return [{"url": u, "title": "", "content": "", "error": str(exc)} for u in urls]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tavily extract error: %s", exc)
            if _is_4xx(exc):
                _record_failure()
            error = _tavily_error_response("extract", exc)
            return [
                {
                    "url": u,
                    "title": "",
                    "content": "",
                    "error": error["error"],
                    "status_code": error.get("status_code"),
                    "provider": "tavily",
                    "fallback_eligible": error.get("fallback_eligible", False),
                }
                for u in urls
            ]

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Tavily",
            "badge": "paid",
            "tag": "Search + extract in one provider.",
            "env_vars": [
                {
                    "key": "TAVILY_API_KEY",
                    "prompt": "Tavily API key",
                    "url": "https://app.tavily.com/home",
                },
            ],
        }
