# NorthStar critical review — 2026-05-01

Purpose: reality-check `/home/kensei/NorthStar.md` against live KENSEI/Hermes state, then cut the MVP down to something shippable instead of another tinkering swamp.

## Executive take

The current North Star doc is useful as a vision document, but it is a bad execution document in its current form.

It mixes three things that should be separate:

1. MVP outcomes Sahil actually wants.
2. Infrastructure hardening and platform plumbing.
3. Nice-to-have future architecture, subagents, Hindsight, Postiz, GitHub MCP, off-VPS backups, voice calls, multi-profile orchestration.

That is why the setup has felt ropey. The document makes the MVP look like a full personal-agent platform migration. It is asking for too much surface area before any daily-use value has landed.

The sane MVP is not “finish every checklist item”. The sane MVP is:

- daily mailbox digest from all 7 inboxes
- daily research digest
- browser/phone command center works enough
- Telegram remains primary mobile interface
- content agent drafts text only, no posting integration yet
- cron/watchdog/backup basics are in place
- everything else is deferred until the above is boringly reliable

## Live state verified

### Working or mostly working

- Hermes installed and running.
- `~/.hermes/config.yaml` exists, mode `600`, size 15477 bytes.
- `~/.hermes/.env` exists, mode `600`, size 19545 bytes.
- `~/.hermes/SOUL.md` exists, mode `600`, size 2795 bytes. The earlier permission issue is fixed.
- `~/.hermes/memories/MEMORY.md` exists, mode `600`, size 1986 bytes.
- `~/.hermes/memories/USER.md` exists, mode `600`, size 3408 bytes.
- Dashboard works locally via `hermes dashboard`, verified at `http://127.0.0.1:9119/`.
- Dashboard API `/api/status` reports Hermes version `0.12.0`, config version `23`, gateway running, Telegram connected, one active session.
- Gmail MCP works for all 3 accounts:
  - `saghir.sahil@gmail.com`
  - `sahilsaghir.ss9@gmail.com`
  - `fusionfirststudios@gmail.com`
- Outlook MCP works for all 4 accounts. Latest-message reads succeeded for:
  - `sahil_ss9@hotmail.com`
  - `sahil_saghir@hotmail.co.uk`
  - `sahil_ss@outlook.com`
  - `matchdaymaestro@outlook.com`
- Env has keys set for GitHub, Ollama, Telegram, Gemini, Google OAuth, Tavily, Mem0, OpenAI, healthchecks.
- Cron system exists and has 5 jobs:
  - `kensei-heartbeat`, every 30m, last ok
  - `memory-curator-run`, daily, last ok
  - `doctor-daily`, daily, last ok
  - `token-health-check`, every 6h, last error
  - `Phase1 Gmail Verifier`, daily, last ok
- Backups exist under `~/.hermes/backups`, including pre-update zips from 2026-04-30 and 2026-05-01.
- Tailscale socket exists, so Tailscale is installed/running enough to expose the dashboard later.
- Installed skills count is 102, not 25. Several useful skills already exist: Google Workspace, Gmail audit, GitHub workflow/review/issues, social voice skills, xurl, blogwatcher, arxiv, etc.

### Not working, missing, or wrongly assumed

- The doc repeatedly says `hermes web`. The actual command is `hermes dashboard`.
- `hermes skills browse --source hub` is wrong. Valid sources are: `all`, `official`, `skills-sh`, `well-known`, `github`, `clawhub`, `lobehub`.
- `hermes skills platforms` is wrong. The real command is `hermes skills config`.
- Current model config is `openai-codex` / `gpt-5.5`, not Ollama Cloud / Kimi-K2.6 primary.
- Memory provider is currently `mem0`, not Hindsight.
- `GITHUB_TOKEN` is already present in `.env`, but GitHub MCP is not configured. `gh` CLI is not installed.
- MCP servers configured: `google_workspace`, `outlook`. No `github`, no `postiz`, no `composio`.
- Postiz API key is not present. Web search found Postiz CLI/Public API docs and third-party MCPs, but no local integration exists yet.
- Firecrawl and Exa keys are not present. Tavily key is present.
- No Hermes profiles directory exists. So the “five specialized subagents as profiles” are not implemented.
- No app repos were found under `/home/kensei` for CoachOS, Plenishd, MatchdayMaestro, Kick-tionary, or Player Portfolio Builder. Only `gbrain` and `brain` appeared as git-ish project dirs.
- App-specific `AGENTS.md` files therefore do not exist locally. Only `/home/kensei/gbrain/AGENTS.md` was found.
- No mailbox daily digest cron exists yet.
- No researcher daily digest cron exists yet.
- No daily local backup cron was found in Hermes cron list. Pre-update backups exist, but that is not the same as scheduled backups.
- No off-VPS backup proof found.
- No error-log alerting cron found.
- Token health cron exists but currently reports `last_status: error`.
- The doc treats Hindsight as MVP-critical, but current working memory stack is Mem0 plus built-in memory/session search. That is a scope trap unless local-first memory is truly non-negotiable.
- The doc treats Postiz posting as MVP-critical. That is another scope trap. Drafting content gives value now. Posting integration can wait.

## Critical issues in the current NorthStar doc

### 1. The MVP is too wide

The checklist tries to ship mailbox, research, content, dashboard, GitHub MCP, Postiz, Hindsight, backup/DR, security hardening, subagent profiles, voice, skills curation, platform filtering, mobile PWA, and audit discipline all at once.

That is not an MVP. That is a platform rebuild.

### 2. It marks too many things as foundational that are actually optional

These should not block MVP:

- Hindsight
- GitHub MCP
- Postiz
- Composio
- five separate Hermes profiles
- off-VPS backups
- Discord interface
- voice call access
- Wondel skills
- Firecrawl/Exa
- Postiz MCP evaluation

Useful later, yes. MVP blockers, no.

### 3. It contains stale or wrong command assumptions

The doc has commands that fail today:

- `hermes web`
- `hermes skills browse --source hub`
- `hermes skills platforms`

That matters because bad runbooks are worse than no runbooks. They burn time and confidence.

### 4. It undercounts what already exists

The checklist says 25 skills and various missing auth bits. Reality is better:

- 102 installed skills
- Gmail verified
- Outlook verified
- GitHub token present
- Tavily present
- dashboard works locally
- cron framework already live

The emotional state of “I’m miles away” is partly because the doc is stale. You are not as far away as it says.

### 5. It hides the actual blocking path

The real blockers are not glamorous:

- write the digest prompts properly
- schedule them
- make delivery reliable
- create a repeatable content-drafting workflow
- fix token-health cron
- make dashboard reachable from phone
- tighten obvious permissions

That is the boring path. Boring is good. Boring ships.

## Recommended MVP cut

### MVP 0: Stabilise KENSEI, 1-2 hours

Goal: stop the feeling that everything is half-broken.

Do these first:

1. Tighten `SOUL.md` permissions to `600`.
2. Fix or disable the failing `token-health-check` cron.
3. Create a concise live-state runbook, not another encyclopedia.
4. Replace stale commands in NorthStar:
   - `hermes web` → `hermes dashboard`
   - `--source hub` → `--source all` or a specific real source
   - `hermes skills platforms` → `hermes skills config`
5. Mark dashboard local access as done.
6. Mark Outlook MCP as done.
7. Mark GitHub token as done, but GitHub MCP as not done.

Done when: the doc no longer lies about the current system.

### MVP 1: Mailbox digest, highest value

Goal: wake up to one useful digest from all 7 inboxes.

Use existing MCP tools. Do not build a separate Mailbox Agent profile yet.

Minimum output:

- urgent / action needed
- job hunt
- money/property/admin
- family/personal
- noise/unsubscribe candidates
- suggested replies, drafted only, never sent

Implementation path:

1. Build one prompt for all 7 inboxes.
2. Create one Hermes cron job, daily morning Europe/London.
3. Deliver to current chat or Telegram origin.
4. Store full markdown under `~/.hermes/runbooks/digests/mailbox/YYYY-MM-DD.md`.
5. Verify one manual run before scheduling.

Done when: one manual run works and one scheduled run works.

### MVP 2: Research digest

Goal: one useful daily AI/Hermes/devtools digest.

Do not overbuild with Firecrawl/Exa. Tavily/web_search is enough for MVP.

Minimum output:

- AI/devtools headlines Sahil should care about
- Hermes Agent updates
- Claude Code/OpenAI Codex/OpenRouter/Ollama changes
- one “try this workflow improvement” recommendation
- links/sources

Done when: one manual run works and one scheduled run works.

### MVP 3: Command Center access

Goal: browser dashboard usable from laptop and phone.

Already verified locally. Next step is not “build a command center”. It is just expose what exists safely.

Path:

1. Run dashboard bound to Tailscale-only address or keep localhost plus SSH tunnel.
2. Verify from phone over Tailscale.
3. Add PWA shortcut if useful.
4. Do not daemonize until the workflow proves useful.

Done when: Sahil can open the dashboard from phone and send one real KENSEI instruction.

### MVP 4: Content drafting, not posting

Goal: ask KENSEI to draft content in the right voice.

Postiz is explicitly post-MVP until drafting is reliable.

Minimum:

- MatchdayMaestro text draft
- Plenishd text draft
- Sahil personal LinkedIn/Twitter draft
- approval stays manual
- no API posting required

Use existing voice skills:

- `matchdaymaestro-voice`
- `plenishd-voice`
- `sahil-twitter-voice`
- `sahil-linkedin-voice`
- `brand-voices`

Done when: three drafts are good enough that Sahil would edit rather than rewrite.

## Revised MVP success criteria

MVP is done when Sahil can do these 6 things:

1. Receive one useful mailbox digest covering all 7 inboxes.
2. Receive one useful research digest.
3. Open the Hermes dashboard from browser, and ideally phone via Tailscale.
4. Ask KENSEI on Telegram to draft MatchdayMaestro content and get a usable text draft.
5. Ask KENSEI to recall prior context using current memory/session search, regardless of whether provider is Mem0 or Hindsight.
6. Confirm no obvious operational fires: dashboard starts, gateway connected, key cron jobs ok, failing token-health cron resolved or disabled.

Everything else is post-MVP.

## Suggested status corrections for `/home/kensei/NorthStar.md`

High-confidence changes:

- SOUL.md: `[🔴]` → `[✅]` because it exists and permissions are now `600`.
- Web UI / Command Center local dashboard: `[🔴]` → `[✅]` for local access via `hermes dashboard`.
- `.env` exists/permissions/inventory: `[🔴]` → `[✅]`.
- GITHUB_TOKEN: `[🔴]` → `[✅]` token present.
- Microsoft Graph tokens: `[🟡]` → `[✅]` all 4 accounts verified by live reads.
- Optional research backend keys: `[🔴]` → `[🟡]` Tavily exists, Firecrawl/Exa absent.
- Outlook MCP active: `[🟡]` → `[✅]`.
- Skills count: update from 25 to 102.
- Postiz: remains `[🔴]`.
- Hindsight: remains `[🔴]`, but should be demoted from MVP blocker unless local-first memory is non-negotiable.
- Subagent profiles: remain `[🔴]`, but move post-MVP.
- App AGENTS.md items: remain `[🔴]`, and add “repos not present locally”.
- Token usage / token health: change to `[🟡]`, because token-health cron exists but is failing.
- Backup: change “some backup exists” to `[🟡]`, because pre-update backups exist but scheduled backups/off-VPS are not verified.

## Immediate next actions I recommend

1. Patch NorthStar to remove stale commands and mark verified items accurately.
2. Fix `SOUL.md` permissions.
3. Inspect `token_health.py` and fix the failing cron.
4. Create Mailbox Digest MVP cron.
5. Create Research Digest MVP cron.
6. Verify dashboard over Tailscale.
7. Defer Postiz, GitHub MCP, Hindsight, Wondel, and subagent profiles until the two daily digests are working.

## Blunt bottom line

You are not failing because this is technically impossible. You are stuck because the checklist became a junk drawer.

The system already has enough working plumbing to deliver value. Stop chasing the full architecture. Ship the daily digests and command access first. Then add shiny integrations only when they remove friction, not because the doc name-dropped them.
