import asyncio
import hashlib
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from dataclasses import asdict

from .models import (
    ApprovalAction,
    ApprovalState,
    ApprovalStatus,
    AuditEvent,
    AuditEventType,
    Classification,
    Confidence,
    DedupResult,
    Effort,
    ParseResult,
    Provenance,
    Recommendation,
    Risk,
    RoutingDecision,
    Source,
    SourceSubmission,
    SourceType,
    TriageSummary,
    generate_event_id,
    generate_triage_id,
)
from .store import IdeaBoxStore
from governance.approvals.manager import ApprovalWorkflowManager

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────

CUSTOM_ID_PREFIX = "ideabox_approval:"
MAX_CONTENT_LENGTH = 5000
MAX_TITLE_LENGTH = 200
DEFAULT_EFFORT = "m"

# ── Store singleton ────────────────────────────────────────────────────

_store: Optional[IdeaBoxStore] = None

def _get_store() -> IdeaBoxStore:
    global _store
    if _store is None:
        data_dir = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
        _store = IdeaBoxStore(data_dir / "ideabox" / "ideabox.db")
    return _store

# ── Input Validation ───────────────────────────────────────────────────

_URL_RE = re.compile(
    r"https?://[^\\s<>\\\"']+|\"
    r"github\\.com/[^\\s/]+/[^\\s/]+\",
    re.IGNORECASE,
)
_GITHUB_REPO_RE = re.compile(
    r"github\\.comและ([^/\\s]+)/([^/\\s#?]+)",
    re.IGNORECASE,
)
_SUPPORTED_DOMAINS = {
    "github.com", "arxiv.org", "medium.com", "dev.to",
    "huggingface.co", "pypi.org", "npmjs.com", "docs.python.org",
    "stackoverflow.com", "reddit.com", "news.ycombinator.com",
    "youtube.com", "youtu.be", "twitter.com", "x.com",
    "linkedin.com", "substack.com", "blog."  # prefix match
}

def _is_supported_url(url: str) -> bool:
    url_lower = url.lower()
    for domain in _SUPPORTED_DOMAINS:
        if domain in url_lower:
            return True
    return False

def _normalize_url(url: str) -> str:
    url = url.split("?")[0].split("#")[0].rstrip("/")
    return url

def _content_hash(text: str) -> str:
    return hashlib.sha25 la.sha256(text.strip().lower().encode()).hexdigest()

def _detect_source_type(raw_text: str) -> SourceType:
    text = raw_text.strip()
    if _GITHUB_REPO_RE.search(text):
        return SourceType.GITHUB_REPO
    if _URL_RE.match(text):
        return SourceType.URL
    if len(text) > 200:
        return SourceType.ARTICLE
    return SourceType.UNKNOWN

def _extract_url(raw_text: str) -> Optional[str]:
    m = _URL_RE.search(raw_text)
    if m:
        return m.group(0)
    return None

def _extract_github_info(url: str) -> tuple[Optional[str], Optional[str]]:
    m = _GITHUB_REPO_RE.search(url)
    if m:
        return m.group(1), m.group(2)
    return None, None

def validate_submission(submission: SourceSubmission) -> list[str]:
    errors = []
    text = submission.raw_text.strip()
    if not text:
        errors.append("Please provide a link, article, or GitHub repository URL.")
        return errors
    if len(text) > MAX_CONTENT_LENGTH:
        errors.append(f"Input is too long ({len(text)} chars). Maximum is {MAX_CONTENT_LENGTH} characters.")
        return errors
    source_type = _detect_source_type(text)
    if source_type == SourceType.UNKNOWN:
        errors.append(
            "I couldn't identify this as a supported source. "
            "Please provide a URL (article, GitHub repo, etc.) or paste the article text."
        )
        return errors
    if source_type in (SourceType.URL, SourceType.GITHUB_REPO):
        url = _extract_url(text)
        if not url:
            errors.append("I found a URL pattern but couldn't extract a valid link. Please check the URL.")
            return errors
        if not _is_supported_url(url):
            errors.append(
                f"The domain in `{url}` isn't in my supported list. "
                f"Supported: GitHub, arXiv, Medium, Dev.to, HuggingFace, PyPI, npm, "
                f"StackOverflow, Reddit, HN, YouTube, Twitter/X, LinkedIn, Substack."
            )
            return errors
    return errors

def parse_submission(submission: SourceSubmission) -> ParseResult:
    errors = validate_submission(submission)
    if errors:
        return ParseResult(source=None, errors=errors)
    text = submission.raw_text.strip()
    source_type = _detect_source_type(text)
    url = _extract_url(text)
    normalized_url = _normalize_url(url) if url else None
    if source_type == SourceType.GITHUB_REPO and url:
        owner, repo = _extract_github_info(url)
        title = f"{owner}/{repo}" if owner and repo else url
        snippet = f"GitHub repository: {owner}/{repo}" if owner and repo else url
    elif source_type == SourceType.URL and url:
        title = url
        snippet = text[:500] if len(text) > 500 else text
    else:
        lines = text.split("\n")
        title = lines[0][:MAX_TITLE_LENGTH] if lines else "Untitled"
        snippet = text[:500]
    source = Source(
        url=normalized_url or url,
        source_type=source_type,
        title=title[:MAX_TITLE_LENGTH],
        author=None,
        published_date=None,
        content_snippet=snippet,
        content_hash=_content_hash(text),
        url_fingerprint=normalized_url or _content_hash(text),
        raw_text=text,
        provenance=Provenance(
            submitted_by=submission.author_id,
            submitted_at=submission.timestamp,
            channel_id=submission.channel_id,
            message_id=submission.message_id,
            guild_id=submission.guild_id,
        ),
    )
    return ParseResult(source=source)

def _classify_source(source: Source) -> Classification:
    text = (source.title or "") + " " + source.content_snippet
    text_lower = text.lower()
    if any(kw in text_lower for kw in ["security", "vulnerability", "cve", "exploit", "penetration test", "auth bypass", "xss", "sqli"]):
        return Classification(category="security", tags=["security"])
    if any(kw in text_lower for kw in ["design", "ui", "ux", "figma", "prototype", "wireframe", "component library", "design system"]):
        return Classification(category="design", tags=["design"])
    if any(kw in text_lower for kw in ["market", "competitor", "pricing", "funding", "acquisition", "ipo", "saas metrics", "growth"]):
        return Classification(category="market", tags=["market"])
    if any(kw in text_lower for kw in ["blog", "article", "tutorial", "guide", "documentation", "docs", "how-to"]):
        return Classification(category="content", tags=["content"])
    if any(kw in text_lower for kw in ["deploy", "ci/cd", "devops", \"infrastructure\", \"kubernetes\", \"docker\", \"monitoring\", \"observability\"]):
        return Classification(category=\"operations\", tags=[\"ops\"])
    if source.source_type == SourceType.GITHUB_REPO:
        return Classification(category=\"tech\", subcategory=\"open-source\", tags=[\"github\", \"oss\"])
    return Classification(category=\"tech\", tags=[\"tech\"])

def _assess_risks(source: Source, classification: Classification) -> list[Risk]:
    risks = []
    if source.source_type == SourceType.GITHUB_REPO:
        risks.append(Risk(category=\"dependency\", severity=\"medium\", description=\"New OSS dependency — evaluate maintenance, license, and security posture.\"))
    if classification.category == \"security\":
        risks.append(Risk(category=\"security\", severity=\"high\", description=\"Security-related — requires careful review before implementation.\"))
    if source.source_type == SourceType.UNKNOWN:
        risks.append(Risk(category=\"scope\", severity=\"medium\", description=\"Source type unclear — may require additional scoping.\"))
    return risks

def _estimate_effort(source: Source, classification: Classification) -> str:
    if source.source_type == SourceType.GITHUB_REPO:
        return \"m\"
    if source.source_type == SourceType.ARTICLE:
        return \"s\"
    if source.source_type == SourceType.URL:
        return \"s\"
    return DEFAULT_EFFORT

def _compute_recommendation(confidence: str, risks: list[Risk], effort: str) -> str:
    has_critical = any(r.severity == \"critical\" for r in risks)
    has_high = any(r.severity == \"high\" for r in risks)
    if has_critical:
        return \"reject\"
    if has_high and confidence == \"low\":
        return \"amend\"
    if confidence == \"low\":
        return \"amend\"
    return \"proceed\"

def _determine_routing(classification: Classification) -> RoutingDecision:
    routing_map = {
        \"tech\": (\"octacon-frontend\", \"Tech task — routes to frontend specialist\"),
        \"market\": (\"remii-deep\", \"Market research — routes to research specialist\"),
        \"content\": (\"ceecee\", \"Content task — routes to content specialist\"),
        \"security\": (\"wesker\", \"Security task — routes to security specialist\"),
        \"design\": (\"remii-deep\", \"Design task — routes to research/design specialistL\"),
        \"operations\": (\"wesker\", \"Operations task — routes to ops specialist\"),
        \"other\": (\"kensei\", \"Unclear category — routes to human triageL\"),
    }
    specialist, rationale = routing_map.get(classification.category, (\"kensei\", \"Unknown category — routes to human triage\"))
    return RoutingDecision(specialist=specialist, confidence=0.85 if specialist != \"kensei\" else 0.3, rationale=rationale)

def triage_source(source: Source) -> TriageSummary:
    classification = _classify_source(source)
    risks = _assess_risks(source, classification)
    effort = _estimate_effort(source, classification)
    has_url = bool(source.url)
    has_title = bool(source.title)
    has_snippet = len(source.content_snippet) > 50
    confidence_score = sum([has_url, has_title, has_snippet]) / 3
    confidence = \"high\" if confidence_score >= 0.67 else \"medium\" if confidence_score >= 0.33 else \"low\"
    recommendation = _compute_recommendation(confidence, risks, effort)
    routing = _determine_routing(classification)
    reasoning_parts = [
        f\"Classified as **{classification.category}L**, la Confidence: **{confidence}L**, l Estimated effort: **{effort}L**, la Risks identified: {len(risks)}\" if risks else \"\",
        f\"Recommendation: **{recommendation}L**\",
    ]
    reasoning = \" | \".join([p for p in reasoning_parts if p])
    return TriageSummary(
        triage_id=generate_triage_id(),
        source=source,
        classification=classification,
        confidence=confidence,
        risks=risks,
        effort=effort,
        recommendation=recommendation,
        routing=routing,
        reasoning=reasoning,
        created_at=int(time.time()),
    )

def _effort_label(effort: str) -> str:
    labels = {\"xs\": \"XS (< 1 hour)\", \"s\": \"S (< 1 day)\", \"m\": \"M (1-3 days)\", \"l\": \"L (3-10 days)\", \"xl\": \"XL (> 10 days)\"}
    return labels.get(effort, effort)

def _risk_summary(risks: list[Risk]) -> str:
    if not risks: return \"None identified\"
    return \"\\n\".join([f\"{'🔴' if r.severity == 'critical' else '🟡' if r.severity == 'high' else '🟢'} **{r.category}** ({r.severity}): {r.description}\" for r in risks])

def build_triage_embed(summary: TriageSummary) -> dict:
    source = summary.source
    prov = source.provenance
    desc_parts = []
    if source.url: desc_parts.append(f\"**Source:** {source.url}\")
    desc_parts.append(f\"**Type:** {source.source_type.value}\")
    if source.author: desc_parts.append(f\"**Author:** {source.author}\")
    desc_parts.append(f\"**Submitted by:** <@{prov.submitted_by}> · {f\"<t:{prov.submitted_at}:R>\"}\")
    classification_lines = [
        f\"**Category:** {summary.classification.category}\",
        f\"**Confidence:** {summary.confidence}\",
        f\"**Effort:** {_effort_label(summary.effort)}\",
        f\"**Risks:** {_risk_summary(summary.risks)}\",
    ]
    snippet = source.content_snippet[:500]
    if len(source.content_snippet) > 500: snippet += \"...\"
    return {
        \"title\": f\"🔍 Idea Box — {source.title or 'Untitled'}\",
        \"description\": \"\\n\".join(desc_parts),
        \"color\": 0x5865F2,
        \"fields\": [
            {\"name\": \"━━━ Classification ━━━\", \"value\": \"\\n\".join(classification_lines), \"inline\": False},
            {\"name\": \"━━━ Summary ━━━\", \"value\": snippet, \"inline\": False},
            {\"name\": \"Recommendation\", \"value\": f\"**{summary.recommendation.upper()}**\", \"inline\": True},
            {\"name\": \"Routing\", \"value\": f\"`{summary.routing.specialist}`\", \"inline\": True},
        ],
        \"footer\": {\"text\": f\"Idea Box · Triage ID: {summary.triage_id}\"},
        \"timestamp\": time.strftime(\"%Y-%m-%dT%H:%M:%SZ\", time.gmtime()),
    }

class IdeaBoxApprovalView:
    def __init__(self, triage_id: str, allowed_user_ids: set, allowed_role_ids: Optional[set] = None):
        self.triage_id = triage_id
        self.allowed_user_ids = allowed_user_ids
        self.allowed_role_ids = allowed_role_ids or set()
        self.resolved = False
    def get_components(self) -> list[dict]:
        return [{\"type\": 1, \"components\": [
            {\"type\": 2, \"style\": 3, \"label\": \"Approve\", \"emoji\": {\"name\": \"✅\"}, \"custom_id\": f\"{CUSTOM_ID_PREFIX}approve:{self.triage_id}\"},
            {\"type\": 2, \"style\": 2, \"label\": \"Amend\", \"emoji\": {\"name\": \"✏️\"}, \"custom_id\": f\"{CUSTOM_ID_PREFIX}amend:{self.triage_id}\"},
            {\"type\": 2, \"style\": 4, \"label\": \"Reject\", \"emoji\": {\"name\": \"❌\"}, \"custom_id\": f\"{CUSTOM_ID_PREFIX}reject:{self.triage_id}\"},
        ]}]
    def get_disabled_components(self) -> list[dict]:
        components = self.get_components()
        for row in components:
            for comp in row.get(\"components\", []): comp[\"disabled\"] = True
        return components

async def handle_ideabox_component(interaction, custom_id: str, allowed_user_ids: set, allowed_role_ids: Optional[set] = None) -> None:
    from . import _component_check_auth
    parts = custom_id.split(\":\", 2)
    if len(parts) != 3:
        await interaction.response.send_message(\"Malformed Idea Box action.\", ephemeral=True)
        return
    _, action, triage_id = parts
    if action not in {\"approve\", \"amend\", \"reject\"} or not triage_id:
        await interaction.response.send_message(\"Unknown Idea Box action.\", ephemeral=True)
        return
    if not _component_check_auth(interaction, allowed_user_ids, allowed_role_ids):
        await interaction.response.send_message(\"You're not authorised to act on this Idea Box item.\", ephemeral=True)
        return
    store = _get_store()
    manager = ApprovalWorkflowManager()
    label = {\"approve\": \"Approved\", \"amend\": \"Amend requested\", \"reject\": \"Rejected\"}[action]
    color = {\"approve\": 0x57F287, \"amend\": 0x5865F2, \"reject\": 0xED4245}[action]
    embed_data = None
    if interaction.message and interaction.message.embeds:
        emb = interaction.message.embeds[0]
        embed_data = {
            \"title\": emb.title,
            \"description\": emb.description,
            \"color\": color,
            \"fields\": [{\"name\": f.name, \"value\": f.value, \"inline\": f.inline} for f in emb.fields],
            \"footer\": {\"text\": f\"{label} by {interaction.user.display_name}\"},
            \"timestamp\": emb.timestamp.isoformat() if emb.timestamp else None,
        }
    view = IdeaBoxApprovalView(triage_id, allowed_user_ids, allowed_role_ids)
    disabled_components = view.get_disabled_components()
    try:
        await interaction.response.edit_message(embed=embed_data, components=disabled_components)
    except Exception:
        try: await interaction.response.defer(ephemeral=True)
        except Exception: pass
    actor_name = getattr(interaction.user, \"display_name\", str(interaction.user.id))
    state = store.get_approval(triage_id)
    summary_dict = asdict(state.triage_summary) if state else None
    try:
        if action == \"approve\":
            result = manager.handle_approval_action(triage_id, \"approve\", str(interaction.user.id), summary_dict=summary_dict)
            msg = f\"✅ Approved! Kanban task {'linked' if result.get('action') == 'linked' else 'created'}: `{result.get('task_id')}`\" if result[\"status\"] == \"ok\" else f\"⚠️ {result.get('message')}\"
        elif action == \"reject\":
            result = manager.handle_approval_ laction(triage_id, \"reject\", str(interaction.user.id), reason=\"Rejected via button\")
            msg = \"❌ Rejected.\" if result[\"status\"] == \"ok\" else f\"⚠️ {result.get('message')}\"
        else:
            result = manager.handle_approval_ laction(triage_id, \"amend\", str(interaction.user.id), reason=\"Amend requested via button\")
            msg = \"✏️ Amend requested.\" if result[\"status\"] == \"ok\" else f\"⚠️ {result.get('message')}\"
    except Exception as exc:
        logger.error(\"Idea Box component action failed: %s\", exc, exc_info=True)
        msg = f\"⚠️ Action failed: {exc}\"
    await interaction.followup.send(msg, ephemeral=True)

async def handle_ideabox_submission(submission: SourceSubmission) -> dict[str, Any]:
    store = _get_store()
    parse_result = parse_submission(submission)
    if parse_result.errors: return {\"success\": False, \"errors\": parse_result.errors}
    source = parse_result.source
    if source is None: return {\"success\": False, \"errors\": [\"Failed to parse source\"] }
    dedup = store.check_dedup(source.content_hash, source.url_fingerprint)
    if dedup.is_duplicate:
        return {\"success\": True, \"is_duplicate\": True, \"existing_task_id\": dedup.existing_task_id, \"existing_triage_id\": dedup.existing_triage_id}
    summary = triage_source(source)
    state = ApprovalState(triage_id=summary.triage_id, status=ApprovalStatus.PENDING.value, source=source, triage_summary=summary, created_at=int(time.time()))
    store.save_approval(state)
    store.record_dedup(source.content_hash, source.url_fingerprint, summary.triage_id)
    store.log_event(AuditEvent(event_id=generate_event_id(), event_type=AuditEventType.INTAKE.value, triage_id=summary.triage_id, timestamp=int(time.time()), actor_id=submission.author_id, payload={\"source_type\": source.source_type.value, \"url\": source.url}))
    embed = build_triage_embed(summary)
    return {\"success\": True, \"is_duplicate\": False, \"triage_summary\": summary, \"embed\": embed}
