# KENSEI — North Star Document

**Owner:** Sahil Saghir
**Created:** 2026-04-29
**Purpose:** Single source of truth for what Kensei is, what we're building, and the complete checklist from current state to North Star
**For:** Kensei (the Hermes agent itself) and any future planning instance to refer back to
**Status:** Active build — target completion Sunday 4 May 2026 (MVP)

---

## 1. WHAT KENSEI IS (THE VISION IN ONE PARAGRAPH)

Kensei is Sahil's persistent, self-improving personal AI agent built on Hermes Agent (Nous Research). It runs on a Linux VPS, accessible via CLI, Telegram, Discord, and built-in browser dashboard (`hermes dashboard`). Kensei is structured as an **orchestrator with specialized subagents** — one for research, one for mailbox management, one for content creation, one for coding work, and a general-assist agent with voice call access. Each subagent has its own scope, skills, and tools. The orchestrator coordinates across them based on the task at hand. Kensei is supported by full MCP and tool integrations (Gmail, Outlook, GitHub, Postiz for social media, Composio for everything else), runs scheduled cron jobs autonomously, and has an external memory provider (Hindsight) that gives it cross-session recall. The user controls everything via a unified Command Center accessible from desktop browser or phone, with destructive actions gated behind manual approval and a full audit trail. Kensei is private (data stays on Sahil's VPS unless he explicitly opts in to cloud services), self-hosted, and designed to compound in usefulness over time.

---

## 2. THE ARCHITECTURE

```
                          ┌─────────────────────────┐
                          │   COMMAND CENTER        │
                          │   (browser + mobile)    │
                          └────────────┬────────────┘
                                       │
                          ┌────────────┴────────────┐
                          │                         │
                  ┌───────┴───────┐         ┌───────┴───────┐
                  │   GATEWAY     │         │   CRON        │
                  │  (Telegram,   │         │   SCHEDULER   │
                  │   Discord,    │         │   (autonomous │
                  │   CLI, Email) │         │    workflows) │
                  └───────┬───────┘         └───────┬───────┘
                          │                         │
                          └────────────┬────────────┘
                                       │
                          ┌────────────┴────────────┐
                          │     ORCHESTRATOR        │
                          │   (Kensei main agent)   │
                          └────────────┬────────────┘
                                       │
        ┌──────────────┬───────────────┼──────────────┬───────────────┐
        │              │               │              │               │
   ┌────┴────┐   ┌─────┴─────┐  ┌──────┴──────┐ ┌─────┴─────┐  ┌──────┴──────┐
   │RESEARCH │   │ MAILBOX   │  │   CONTENT   │ │  CODING   │  │  GENERAL    │
   │ AGENT   │   │  AGENT    │  │   AGENT     │ │  AGENT    │  │  ASSIST     │
   │         │   │           │  │             │ │           │  │  AGENT      │
   │ AI/Tech │   │ Gmail x3  │  │ Plenishd    │ │ Project   │  │ + Voice     │
   │ news,   │   │ Outlook x4│  │ MatchdayM.  │ │ portfolio │  │   call      │
   │ Hermes, │   │ Triage,   │  │ Personal    │ │ work      │  │   access    │
   │ Claude  │   │ digest,   │  │ IG/TikTok/  │ │           │  │             │
   │ Code    │   │ search    │  │ FB/Twitter  │ │           │  │             │
   └────┬────┘   └─────┬─────┘  └──────┬──────┘ └─────┬─────┘  └──────┬──────┘
        │              │               │              │               │
        └──────────────┴───────────────┼──────────────┴───────────────┘
                                       │
                          ┌────────────┴────────────┐
                          │   SHARED INFRASTRUCTURE │
                          ├─────────────────────────┤
                          │  Memory: Mem0 now;       │
                          │  Hindsight optional      │
                          │  MCPs: Gmail, Outlook,  │
                          │        GitHub, Postiz,  │
                          │        Composio         │
                          │  Search: web/Tavily;     │
                          │          Exa later       │
                          │  Audit log: JSONL       │
                          │  Backups: daily local + │
                          │           weekly off-VPS│
                          └─────────────────────────┘
```

---

## 3. THE FIVE SPECIALIZED SUBAGENTS

### 3.1 Research Agent
**Purpose:** Daily and on-demand research. AI ecosystem news, Hermes ecosystem updates, Claude Code releases, broader tech intelligence relevant to Sahil's work.

**Capabilities:**
- Scheduled daily digest (cron-driven) covering AI news, Hermes releases, Claude Code updates, recommendations for workflow improvements
- On-demand deep research via current web search/Tavily; Firecrawl/Exa are post-MVP unless needed
- Surfaces new community Hermes/skills/MCPs that cross validation thresholds
- Drafts learning notes, summaries, and "should Sahil care about this?" filters

**Inputs:** RSS feeds, Hermes Atlas, awesome-hermes-agent, NousResearch GitHub Discussions, Anthropic news, Hacker News AI tag, X/Twitter sources

**Outputs:** Daily markdown digest delivered to file + Telegram summary

---

### 3.2 Mailbox Agent
**Purpose:** Triage and digest across all 7 inboxes. Reduce inbox load to "what actually needs Sahil's attention."

**Capabilities:**
- Reads Gmail (3 accounts: sahilsaghir.ss9, fusionfirststudios, saghir.sahil) via Workspace MCP
- Reads Outlook (4 accounts: sahil_ss9@hotmail.com, sahil_saghir@hotmail.co.uk, sahil_ss@outlook.com, matchdaymaestro@outlook.com) via Outlook MCP
- Daily triage cron: categorizes incoming, summarizes, flags urgency
- Special interest filter: job hunt traffic surfaced separately
- Drafts replies for approval (never sends without explicit confirmation)

**Inputs:** All 7 inboxes, sender history, prior labelling patterns

**Outputs:** Daily digest markdown file + Telegram summary; draft replies queued for approval

---

### 3.3 Content Agent
**Purpose:** Social media content generation and posting across platforms for Sahil's three brand contexts.

**Capabilities:**
- Generates text content drafts for Twitter/X, Instagram, TikTok, Facebook and LinkedIn
- Image generation for posts (Hermes native image gen + community skills)
- Carousel and video generation (MVP: text-only by Sunday; image/carousel/video as post-MVP roadmap)
- Multi-brand voice differentiation via per-brand AGENTS.md and voice profiles
- Posting integration via Postiz is post-MVP; MVP is manual approval and copy/paste-ready drafts
- Extends existing Phase 1 football content engine (Supabase + Telegram + Claude API)

**Brand contexts:**
- **Plenishd** — UK pantry/grocery management app marketing
- **MatchdayMaestro** (@MaestroMatchday) — football trivia/predictions content
- **Personal** — Sahil's personal brand, PM career, indie dev journey

**Inputs:** Brand voice guides, content prompts, existing content engine outputs, image/video generation skills

**Outputs:** Drafted posts ready for Sahil approval; manual publishing for MVP, Postiz scheduling later

---

### 3.4 Coding Agent
**Purpose:** Active project work across Sahil's portfolio. Code review, refactoring, draft implementations, PR support.

**Capabilities:**
- Project context via per-repo AGENTS.md (CoachOS, Plenishd, MatchdayMaestro, Kick-tionary, Player Portfolio Builder)
- GitHub MCP for issue/PR/code search and creation
- File ops, terminal access, test running
- Skill-based: uses bundled coding skills + curated hub skills (e.g., wondelai/skills for PM-flavored work)
- Respects project conventions documented in each AGENTS.md

**Inputs:** Project repos, AGENTS.md context, GitHub MCP, file system access

**Outputs:** Code changes, draft PRs, code reviews, refactoring suggestions

---

### 3.5 General Assist Agent (with Voice)
**Purpose:** Daily-driver, conversational, ad-hoc tasks that don't fit a specialized subagent. Includes voice access for hands-free interaction.

**Capabilities:**
- General Q&A, planning, ideation
- Voice call access (incoming or outgoing — exact mechanism TBD; Hermes supports voice memo transcription natively, full voice call requires research)
- Personal admin (calendar awareness, reminders)
- Family/personal logistics
- Falls back to other subagents when task crosses domain

**Inputs:** Direct conversation, voice input, Sahil's calendar (via Workspace MCP)

**Outputs:** Conversational responses, scheduled actions, delegation to specialized subagents

---

## 4. CORE INFRASTRUCTURE COMPONENTS

### 4.1 Configuration
- **`~/.hermes/config.yaml`** — main config (model, approvals, memory, MCPs, gateway settings)
- **`~/.hermes/.env`** — all secrets (API keys, tokens), permissions 600
- **`~/.hermes/SOUL.md`** — global personality, tone, identity (slot #1 in system prompt)
- **`~/.hermes/runbooks/`** — operational runbooks for setup, recovery, common workflows
- **`~/.hermes/memories/`** — persistent memory files (MEMORY.md, USER.md)

### 4.2 Memory & Context
- **MEMORY.md** — Sahil's environment, conventions, hard-won lessons (~2,200 char budget)
- **USER.md** — Sahil's identity, preferences, communication style (~4,000 char raised limit)
- **SOUL.md** — global agent identity, tone, persona
- **Current memory provider** — Mem0 plus Hermes session search. Hindsight local-embedded remains an optional post-MVP upgrade if local-first memory becomes non-negotiable
- **AGENTS.md** — per-project context files in each repo
- **Session DB** — `~/.hermes/state.db` — full session log, FTS5 searchable
- **Context Files** — `.hermes.md` / `CLAUDE.md` / `.cursorrules` also loaded progressively per directory

### 4.3 Authentication & APIs
- **GITHUB_TOKEN** — fine-grained PAT, public repo read, lifts Skills Hub rate limit and powers GitHub MCP
- **Gmail OAuth** — 3 accounts via Workspace MCP
- **Microsoft Graph OAuth** — 4 accounts via Outlook MCP (Softeria's ms-365-mcp-server)
- **Postiz API key** — post-MVP social media scheduling across 30+ platforms
- **Telegram bot token** — primary mobile interface
- **Discord bot token** — secondary interface, server admin only (no scraping of others' servers)
- **healthchecks.io ping URL** — heartbeat monitoring
- **Optional:** Composio Connect API key (1,000+ app integrations), Exa/Firecrawl keys. Tavily is already present

### 4.4 MCP Servers (in `config.yaml` under `mcp_servers`)
- **`google_workspace`** — Gmail/Calendar/Drive/Contacts/Sheets/Docs (already wired)
- **`outlook`** — Microsoft 365 mail across 4 personal accounts (verified)
- **`github`** — `@modelcontextprotocol/server-github` (config block in `config.yaml`, tools subset via `include`/`exclude`)
- **`postiz`** — third-party MCP servers exist (`antoniolg/postiz-mcp`, `cristdulcey/postiz-mcp`) — verify one before use
- **`composio`** (optional, future) — single MCP for 1,000+ app integrations

**Note:** Hermes prefixes MCP tools as `mcp_<server>_<tool>`. Per-server tool filtering is supported via `tools.include` / `tools.exclude` in the `mcp_servers` block (see `mcp_servers.github` example).

### 4.5 Skills (in `~/.hermes/skills/`)
- **Bundled** — google-workspace, web search, file ops, code execution, etc.
- **Custom local** — add-gmail-account (saved), add-outlook-account (to save)
- **Hub-installed** — selective from validated shortlist (Postiz, wondelai/skills selective subset, etc.)
- **Auto-generated** — Hermes writes skills from successful workflows; Sahil reviews before enabling

### 4.6 Cron Jobs (autonomous workflows)
- **Heartbeat** — every 30 min, posts to healthchecks.io (already running)
- **Mailbox triage** — daily morning, reads all 7 inboxes, produces digest
- **Researcher digest** — daily morning, AI/Hermes/Claude Code news + workflow recommendations
- **Backup** — daily local tarball of `~/.hermes/`, 30-day retention
- **Off-VPS backup** — weekly rclone to B2 or equivalent
- **Hermes Atlas weekly check** — weekly, diffs ecosystem repos.json, surfaces newly-validated tools
- **Future:** content scheduling cron, weekly health review, monthly memory consolidation

### 4.7 Operational Interfaces
- **CLI** — primary execution interface, full power
- **Telegram** — mobile primary, restricted skills (no destructive without explicit invocation)
- **Discord** — secondary, only Sahil's own servers (not for scraping others)
- **Email gateway** — receive/reply via IMAP/SMTP (deferred unless valuable)
- **Browser dashboard** — Built-in `hermes dashboard` via SSH tunnel or direct Tailscale IP
- **Mobile access** — `hermes dashboard` via Tailscale or SSH tunnel on phone

### 4.8 Security & Hardening
- Approval mode `manual` for write actions
- `cron_mode: deny` requiring explicit approval for new cron jobs
- All secrets in `.env` with 600 permissions
- VPS hardened: SSH key-only auth, UFW firewall, fail2ban, loopback-only listening for non-public services
- Audit trail via JSONL session logs (all sessions captured)
- Error log alerting to Telegram on new entries
- Token rotation calendar (annual)

### 4.9 Backup & Disaster Recovery
- Daily local tarball of `~/.hermes/`, 30-day retention
- Weekly off-VPS backup (rclone to B2/R2)
- Restore test executed at least once
- Private dotfiles repo for configs (no secrets)
- Disaster recovery runbook: rebuild Kensei in <2 hours

### 4.10 Observability
- Heartbeat → healthchecks.io (live)
- Token usage tracking (cron-based weekly summary)
- Skill usage frequency tracking
- Error log alerts to Telegram
- Weekly health review (10 min Monday)
- Monthly audit trail spot-check

---

## 5. MASTER CHECKLIST (BUILD STATE)

### Status legend
- ✅ Done and verified
- 🟡 Partial / in flight
- 🔴 Missing or unverified
- ⏸️ Deliberately deferred

### A. Foundation Configuration

- [🟡] Hermes Agent installed and running (`v0.12.0`, 2026.4.30); currently 4 commits behind, not MVP-blocking
- [🟡] Model provider configured: live gateway is `openai-codex` / `gpt-5.5`, but all LLM-using crons updated 2026-05-02 to `provider: ollama-cloud`, `model: kimi-k2.6` to avoid 429 rate-limit failures; gateway default still needs switch when user confirms
- [🔴] Fallback chain not verified in live config (`fallback_models` absent in audit output); configure after MVP value loops are working
- [✅] `approvals.mode: manual`
- [✅] `approvals.cron_mode: deny`
- [🟡] Memory/user budgets enforced operationally via memory files, but live config keys were not found in audit output
- [✅] USER.md curated around 4,000 char budget
- [✅] Toolsets configured (`hermes-cli`)
- [✅] Voice config done
- [🟡] Heartbeat cron active (kensei-heartbeat, every 30 min, paused 2026-05-02 due to 429; provider switched, to be resumed)
- [✅] healthchecks.io integration confirmed
- [✅] SOUL.md created in `~/.hermes/SOUL.md` with Kensei's persona and tone; permissions tightened to 600 on 2026-05-01
- [🔴] Full `config.yaml` end-to-end review and annotated reference doc
- [✅] **Built-in dashboard (`hermes dashboard`) verified working locally** at `127.0.0.1:9119`; phone/Tailscale access still pending
- [🟡] Backup-before-edit habit exists in North Star operating principles; MEMORY.md entry still worth tightening
- [🔴] Stale runbook audit (any references to `~/.hermes/.mcp.json` updated to `config.yaml`)

### B. Authentication & Secrets

- [✅] `~/.hermes/.env` exists, permissions 600, contents inventoried without exposing secret values
- [✅] **GITHUB_TOKEN** present in `.env`; GitHub MCP/gh CLI still not configured
- [✅] Gmail OAuth tokens working for 3 accounts
- [✅] Microsoft Graph tokens working for 4 Outlook accounts via Outlook MCP live reads
- [✅] Telegram bot token working (heartbeat delivering)
- [✅] healthchecks.io ping URL configured
- [🟡] OpenRouter API key (set but no credits — Sahil deferred fix; Ollama provides headroom)
- [🔴] Postiz API key (signup + auth flow + integration setup)
- [🟡] Optional research backend keys: Tavily present; Firecrawl/Exa absent and post-MVP unless needed
- [🔴] Secrets inventory document (in password manager, not in repo)
- [🔴] Token rotation calendar reminders set (annual)

### C. Memory & Context

- [✅] MEMORY.md exists (1,986 bytes, mode 600)
- [✅] USER.md exists (3,408 bytes, mode 600)
- [🟡] MEMORY.md is useful but near budget; only add compact, durable facts
- [✅] USER.md curated meaningfully
- [⏸️] **Hindsight memory provider** deferred. Current working stack is Mem0 + Hermes session search
- [🔴] AGENTS.md created in CoachOS repo (repo not present under `/home/kensei` during 2026-05-01 audit)
- [🔴] AGENTS.md created in Plenishd repo (repo not present under `/home/kensei` during 2026-05-01 audit)
- [🔴] AGENTS.md created in MatchdayMaestro repo (repo not present under `/home/kensei` during 2026-05-01 audit)
- [🔴] AGENTS.md created in Kick-tionary repo (repo not present under `/home/kensei` during 2026-05-01 audit)
- [🔴] AGENTS.md created in Player Portfolio Builder (when started)
- [🔴] Profile structure decided (single default vs multi-profile per subagent context)
- [🔴] Memory backup/export tested

### D. MCP Servers

- [✅] `google_workspace` MCP active (3 Gmail accounts)
- [✅] `outlook` MCP active across 4 Outlook accounts
- [🔴] **`github` MCP installed and verified** (config block in `config.yaml`, tools subset chosen)
- [🔴] **Postiz** integrated (skill or MCP path; check Postiz docs)
- [⏸️] Composio Connect (1,000+ app integrations) — deferred until specific need

### E. Skills

- [✅] 102 skills in `~/.hermes/skills/` as of 2026-05-01 audit
- [✅] Custom: `add-gmail-account`, `gmail-inbox-audit`
- [🔴] **Postiz integration** — evaluate MCP server path (`antoniolg/postiz-mcp` or `cristdulcey/postiz-mcp`) vs direct API via curl/web skill; install whichever is stable
- [🔴] **`wondelai/skills`** selective install (jobs-to-be-done, inspired-product, refactoring-ui, cro-methodology, mom-test)
- [🔴] Email triage / mailbox digest skill (search hub for existing or build custom)
- [🔴] Researcher digest skill (search hub for existing or build custom)
- [⏸️] Per-platform skill filtering via `platforms:` frontmatter only where useful; no `hermes skills platforms` CLI exists
- [⏸️] Felo Skills bundle (research-to-delivery toolchain) — research first, install conditionally
- [⏸️] hermes-skill-factory (meta-skill auto-generation) — defer until 30+ days production use
- [⏸️] hermes-life-os, hermes-dojo, hermes-incident-commander — defer indefinitely (low validation)

### F. Subagent Setup

- [🔴] **Research Agent** profile/config created
- [🔴] **Mailbox Agent** profile/config created
- [🔴] **Content Agent** profile/config created
- [🔴] **Coding Agent** profile/config created
- [🔴] **General Assist Agent** profile/config created (including voice access mechanism)
- [🔴] Orchestrator delegation patterns documented (when to invoke which subagent)
- [🔴] Per-subagent skill scoping (each subagent has its own enabled skill set)

### G. Cron Jobs (Autonomous Workflows)

- [🟡] Heartbeat cron (kensei-heartbeat, every 30 min, paused 2026-05-02 due to HTTP 429; provider switched to Ollama Cloud, delivery switched to `telegram:8580807827`, to be resumed)
- [🟡] Token health cron (every 6h, paused 2026-05-02 due to HTTP 429; provider switched to Ollama Cloud, delivery switched to `telegram:8580807827`, to be resumed)
- [🟡] Phase1 Gmail Verifier (daily, paused 2026-05-02 due to HTTP 429; provider switched to Ollama Cloud, delivery switched to `telegram:8580807827`, to be resumed)
- [✅] Memory curator (daily 02:00, delivery `telegram:8580807827`, status ok)
- [✅] Doctor daily (daily 07:00, delivery `telegram:8580807827`, status ok)
- [🔴] **Mailbox triage daily digest cron** (highest-value next build)
- [🔴] **Researcher Agent daily digest cron** (second-highest next build)
- [🟡] Daily local backup cron not found; pre-update backups do exist under `~/.hermes/backups/`
- [🔴] Weekly off-VPS backup cron (rclone to B2 or equivalent)
- [🔴] Hermes Atlas weekly diff cron (surface newly-validated ecosystem repos)
- [🔴] Error log alerting (when `errors.log` gets new entry, post to Telegram)
- [⏸️] Content posting cron (post-MVP; manual approval flow for Sunday)
- [⏸️] Monthly memory consolidation review cron

### H. Command Center

- [✅] **Built-in `hermes dashboard`** accessible locally from browser
- [🔴] **SSH tunnel configured** for browser access from laptop (or firewall rule if desired)
- [🔴] Tailscale/mobile access for `hermes dashboard` verified from phone
- [🔴] At least one full Kensei session driven via `hermes dashboard` (validation)
- [🔴] Telegram topic structure documented (Code, Ops, Personal, Research)
- [🔴] Per-platform skill filtering configured (platform restriction done via `platforms:` frontmatter in SKILL.md for installed skills)

### I. Security & Hardening

- [✅] Approval mode `manual`
- [✅] Cron approval mode `deny`
- [✅] `~/.hermes/.env` permissions verified 600
- [✅] `~/.hermes/` directory permission audit completed 2026-05-02; all `.lock`, `.backup-*`, and sensitive files set to 600; `gateway.json` created with Telegram allowlist (`8580807827`) and pairing required
- [🔴] SSH key-only auth verified
- [🔴] UFW firewall active and minimal
- [🔴] fail2ban active
- [🔴] Loopback-only listening confirmed (no unexpected `0.0.0.0` services)
- [✅] **Gateway systemd service** installed, enabled, active (PID 75435); survives reboot; restart pending after final config edits
- [✅] Telegram bot scope confirmed restricted to `8580807827` only via `gateway.json` (created 2026-05-02)
- [🔴] Discord bot scope confirmed restricted (only Sahil's authorized servers)
- [🔴] Skill audit process documented (review before install)
- [🔴] Monthly audit trail review on calendar

### J. Backup & Disaster Recovery

- [🟡] Daily local backup cron not verified; pre-update backups exist
- [🔴] Weekly off-VPS backup running, verified
- [🔴] Restore test executed at least once, runbook updated
- [🔴] Private dotfiles repo created with configs (no secrets)
- [🔴] Disaster recovery runbook exists and is realistic

### K. Observability

- [✅] Heartbeat → healthchecks.io live
- [✅] Gateway journalctl logs available
- [✅] Session logs (JSONL) `~/.hermes/sessions/`
- [✅] Error log isolated (`errors.log`)
- [🟡] Token health cron exists and was failing with HTTP 429; **paused 2026-05-02**, provider switched to Ollama Cloud, to be resumed after gateway restart
- [🔴] Error log alerting to Telegram on new entries
- [🔴] Weekly health review on calendar
- [🔴] Skill usage tracking enabled
- [🔴] "What to check when something feels off" runbook

### L. Update & Maintenance Discipline

- [✅] Hermes updated to current (382 commits pulled)
- [🔴] Update routine documented (backup → changelog → update → doctor → smoke test → commit)
- [🔴] Pre-update checklist runnable in 5 minutes
- [🔴] Quarterly review on calendar (skills/plugins/MCPs/memory)
- [🔴] Monthly memory review on calendar (MEMORY.md, USER.md)
- [🔴] Stale session cleanup policy decided

### M. Goal-Specific Deliverables (North Star MVP)

- [🔴] Mailbox triage MVP (Gmail + Outlook → daily digest) — Outlook/Gmail access verified, digest cron not built
- [🔴] Content drafting MVP — text drafts for priority brands, manual approval/publishing first
- [🟡] Command Center MVP — `hermes dashboard` verified locally; phone/Tailscale access pending
- [🔴] Researcher Agent MVP — daily digest cron delivering AI/Hermes/Claude Code news to file + Telegram
- [🟡] Core infrastructure — GITHUB_TOKEN present, 102 skills installed, Mem0/session search active; Hindsight/GitHub MCP deferred or pending

---

## 6. EXPLICIT NON-GOALS (DO NOT BUILD THESE BEFORE NORTH STAR MVP)

These are valid future enhancements but not part of the Sunday MVP. Calling them out so they don't creep in:

- ⏸️ Image / carousel / video content generation (post-MVP — text-only by Sunday)
- ⏸️ Multi-platform autonomous posting (Sunday MVP is approval-gated, manual confirmation)
- ⏸️ Trading bot (deferred; if pursued ever, use Freqtrade-as-engine + Kensei-as-advisor only)
- ⏸️ Discord scraping of others' servers (ToS-violating; consume curated digests instead)
- ⏸️ Meta-skills installation (skill-factory, life-os, dojo, incident-commander) — defer 2-4 weeks production use minimum
- ⏸️ RL trajectory export, multi-agent swarm patterns, serverless backends — long-horizon
- ⏸️ Full `hermes dashboard` systemd service (run manually for MVP, daemonize later)
- ⏸️ Mobile PWA polish beyond basic Tailscale access (Sunday MVP is "it works on phone")
- ⏸️ Email gateway as messaging interface (Telegram is enough for MVP)

---

## 7. THE BUILD SEQUENCE (MVP RECOVERY ORDER)

This replaces the old all-at-once build plan. The point is to get useful daily value first, then add architecture. Do not install more shiny plumbing until Stage 1 and Stage 2 are working.

### Stage 0 - Reality alignment, already started
1. Keep `/home/kensei/NorthStar-Review-20260501.md` as the audit note for this reset.
2. Keep this North Star checklist updated with verified state only.
3. Fix stale commands: `hermes dashboard`, real skills sources, no fake `hermes skills platforms` command.
4. Resolve obvious security nits such as file permissions.

Done check: the doc reflects live reality and no longer makes Sahil feel further behind than he is.

### Stage 1 - Mailbox digest MVP
1. Build one daily digest prompt covering all 7 inboxes through existing Google Workspace and Outlook MCP tools.
2. First run manually and inspect output quality.
3. Schedule one Hermes cron job for the morning Europe/London.
4. Deliver a short summary to the current chat or Telegram, and save full markdown under `~/.hermes/runbooks/digests/mailbox/YYYY-MM-DD.md`.

Done check: one manual run works, then one scheduled run works.

### Stage 2 - Research digest MVP
1. Use current web search/Tavily. Do not wait for Firecrawl/Exa.
2. Track AI/devtools/Hermes/Claude Code/OpenAI Codex/Ollama changes.
3. Include one practical workflow recommendation per digest.
4. Schedule one daily cron after manual verification.

Done check: one manual run works, then one scheduled run works.

### Stage 3 - Command Center access
1. Keep local `hermes dashboard` as the baseline.
2. Expose via Tailscale or SSH tunnel only, not public internet.
3. Verify from Sahil's phone.
4. Only daemonize once it proves useful.

Done check: Sahil can open it from phone and run one real Kensei session.

### Stage 4 - Content drafting MVP
1. Use existing voice skills for MatchdayMaestro, Plenishd, Sahil LinkedIn and Sahil Twitter/X.
2. Produce copy/paste-ready drafts only.
3. Keep publishing manual.
4. Defer Postiz until drafts are consistently useful.

Done check: three drafts come back good enough to edit, not rewrite.

### Stage 5 - Stabilise operations
1. Fix or disable the failing `token-health-check` cron.
2. Add a simple local backup cron if still missing.
3. Add error-log alerting only after the two digest jobs are stable.
4. Write a short recovery runbook.

Done check: heartbeat, digest jobs, dashboard and backups have boring green checks.

### Post-MVP architecture
Only after the above is reliable: GitHub MCP, Postiz, Hindsight, subagent profiles, Wondel skills, off-VPS backup, voice calls, Composio, Firecrawl/Exa, richer app AGENTS.md hardening.

---

## 8. SUCCESS CRITERIA (IS NORTH STAR MVP DONE?)

Kensei MVP is done when Sahil can reliably do these 6 things:

1. Receive one useful mailbox digest covering all 7 inboxes.
2. Receive one useful research digest with sources and one practical recommendation.
3. Open the Hermes dashboard from browser, and ideally phone via Tailscale.
4. Ask KENSEI on Telegram to draft MatchdayMaestro or Plenishd content and get usable text back.
5. Ask KENSEI to recall prior context using the current memory/session-search stack, regardless of whether the provider is Mem0 or Hindsight.
6. Confirm no operational fires: gateway connected, heartbeat ok, digest crons ok, dashboard starts, token-health issue resolved or deliberately disabled.

Postiz posting, GitHub MCP PR workflows, Hindsight, off-VPS backups, voice calls and multi-profile subagents are post-MVP unless they become direct blockers.

---

## 9. POST-MVP ROADMAP (FOR REFERENCE, NOT THIS WEEK)

After Sunday's MVP ships, in priority order:

1. **Image generation for content** — research Hermes-native and community options
2. **Carousel generation** for IG/TikTok
3. **Video generation** — Sync.so / Kling / Higgsfield pipeline integration
4. **Voice call mechanism** for General Assist Agent (full duplex, not just transcription)
5. **Composio Connect** for broader app coverage (Slack, Notion, Linear, etc. — only if specific need)
6. **Per-subagent profiles** (multi-profile structure if single-profile is constraining)
7. **Self-improvement meta-skills** (after 30+ days of production use, reconsider skill-factory/dojo/life-os)
8. **Trading research advisor** — Freqtrade engine + Kensei advisor pattern (separate workstream)
9. **AGENTS.md hardening** — full per-project context
10. **Plugin curation pass** — quarterly review and prune

---

## 10. REFERENCE DOCS (RELATED)

For deeper reference on specific topics, Kensei should refer to:

- **`KENSEI-FOUNDATION-AUDIT.md`** — comprehensive ecosystem encyclopedia (1,396 lines)
- **`KENSEI-VALIDATED-SHORTLIST.md`** — vetted community candidates with stars/forks/maturity (461 lines)
- **`KENSEI-FOUNDATION-BUILD-SPEC.md`** — earlier 8-pillar foundation spec (497 lines, partially superseded by this doc)
- **`KENSEI-POA-NEXT-STEPS.md`** — earlier POA, mostly stale, kept for historical reference

This doc supersedes all of the above where they conflict. When in doubt, **this North Star doc is canonical.**

---

## 11. OPERATING PRINCIPLES (FOR KENSEI ITSELF TO FOLLOW)

When Kensei is working on items in this doc:

1. **Verify the existing solution before building.** Always check Skills Hub, Hermes Atlas, awesome-hermes-agent first. If it exists, install it. Build only what isn't there.
2. **Validation gates: ≥500 stars OR Nous-endorsed OR Hermes Atlas security-reviewed; last commit ≤60 days; permissive license; identifiable maintainer.** Don't install community packages that fail these.
3. **Manual approval for destructive actions.** Never delete, send, or post without explicit Sahil approval through the messaging gateway.
4. **Backup before any structural change** to `~/.hermes/`. `cp ~/.hermes/config.yaml ~/.hermes/config.yaml.backup-$(date +%Y%m%d-%H%M%S)` before edits.
5. **Document install reasons in MEMORY.md.** Future-Sahil and future-Kensei need context.
6. **Halt and ask** if any step in this doc fails or behaves unexpectedly. Don't power through ambiguity.
7. **Privacy default.** No data leaves the VPS unless Sahil explicitly opts in (e.g., for cloud memory providers, paid LLM APIs).
8. **No em-dashes in Sahil-facing output.** Sahil's writing preference (per USER.md).
9. **No AI-sounding phrasing.** Short, punchy, authentic.
10. **Update this North Star doc** when state changes meaningfully (new ✅ on checklist items, new infrastructure added, deferred items revisited).

---

## 12. CHANGELOG

### 2026-05-02 — Points 2, 4, 6, 7, 8 Execution

**Security (Point 2):**
- `chmod 600` applied to all `.lock`, `.backup-*`, and sensitive files in `~/.hermes/`
- `~/.hermes/gateway.json` created with Telegram allowlist (`8580807827`) and `require_pairing: true`
- Discord bot token not present; no Discord security surface to harden
- Gateway restarted 2026-05-02 01:00 BST to pick up provider changes
- All three paused crons resumed after restart (heartbeat next run ~01:26, token health next run 06:00, Gmail verifier next run 00:00 tomorrow)

**Skills Hub (Point 4):**
- Investigated: 85 builtin + 13 local + ~7 uncategorized = ~105 skills
- `.hub/lock.json` is empty (skills installed manually, not via hub)
- No action required; skills work fine, hub tracking just lacks metadata

**Gateway systemd (Point 6):**
- `hermes-gateway.service` already active, enabled, survives reboot (PID 75435)
- No changes needed

**Cron Fixes (Point 7):**
- Three failing crons paused: `kensei-heartbeat`, `token-health-check`, `Phase1 Gmail Verifier`
- Root cause: all used default provider (`openai-codex`) which hit HTTP 429 rate limits
- All three updated to `provider: ollama-cloud`, `model: kimi-k2.6`
- Delivery target updated to `telegram:8580807827` (Sahil's personal DM)
- Two active crons (`memory-curator-run`, `doctor-daily`) also updated to deliver to DM for consistency
- Gateway restart pending (last step per user instruction)

**Delivery Audit (Point 8):**
- `TELEGRAM_HOME_CHANNEL` conflict documented: `.env` has `8580807827`, `config.yaml` has `-1003922682700`
- All cron delivery targets standardized to `telegram:8580807827` (Sahil's personal DM)
- Recommendation: for future digest crons, explicitly set `deliver: "telegram"` or `deliver: "telegram:8580807827"`

---

**END OF NORTH STAR DOCUMENT**

This is the complete vision and checklist. Refer back to this whenever direction is unclear. When this doc and any other doc conflict, this one wins. Update it as state changes.
