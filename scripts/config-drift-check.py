"""Check enabled_skills count vs expected. Silent when healthy."""
import yaml, sys

MIN_SKILLS = 45
expected = {
    "hermes-update", "kanban-ops", "kensei-triage-processor",
    "kensei-triage-investigator", "kanban-router", "feature-pipeline",
    "kensei-coordinator", "skill-broker-core", "skill-reroute",
    "denji-triage", "denji-skill-audit", "denji-write-skill", "sdlc-review",
    "kanban-blocked-task-resolution", "arxiv", "audit-engine",
    "avoid-ai-writing", "brand-voices", "coachos-voice", "content-pipeline",
    "content-pipeline-standards", "content-review", "cron-output-contract",
    "design-cron-output-format", "design-system-review", "dezzy-design-systems",
    "github-pr-workflow", "hermes-cron-operations", "lesson-delivery",
    "llm-wiki", "mailbox-agent", "mailbox-cleaner", "market-research",
    "matchdaymaestro-voice", "mnemosyne-health-check", "plenishd-voice",
    "remii-triage", "research-digest", "research-paper-synthesis",
    "sahil-linkedin-voice", "sahil-twitter-voice", "social-content",
    "system-script-patterns", "ui-pattern-library-research",
    "upstream-contribution-gate", "weekly-ideas-scan"
}

try:
    with open('/home/kensei/.hermes/config.yaml') as f:
        cfg = yaml.safe_load(f)
    skills = set(cfg.get('skills', {}).get('enabled_skills', []))
    if len(skills) < MIN_SKILLS:
        print(f"[DRIFT] enabled_skills dropped to {len(skills)} (expected >= {MIN_SKILLS})")
        sys.exit(1)
    if skills != expected:
        missing = expected - skills
        extra = skills - expected
        if missing:
            print(f"[DRIFT] Missing skills: {', '.join(sorted(missing))}")
        if extra:
            print(f"[DRIFT] Unexpected skills: {', '.join(sorted(extra))}")
        if missing or extra:
            sys.exit(1)
    # silent on success
except Exception as e:
    print(f"[DRIFT] Check failed: {e}")
    sys.exit(2)
