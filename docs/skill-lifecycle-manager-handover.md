# Skill Access & Lifecycle Manager — Handover

**Date:** 2026-06-03
**Repo:** `~/repos/KenseiAgent` (trunk: `main`)
**Status:** Phases 1-3 of 7 built, tested, quality-gated, committed & pushed. Phases 4-7 outstanding. **Enforcement is currently OFF** (built but not switched on — see "Operational rollout still required").

---

## 1. Goal

Make Sahil's intended skill model real and fully wired, no tech debt:

- One central skill library; per-profile **enabled/disabled** allowlists.
- A worker lacking a skill can **search the library and request access**; the broker grants a **temporary, task-scoped** loan (auto-revoked when the task completes).
- If no suitable skill exists, a lead/Denji/researcher **sources or creates** one — **internal-first** (library + LLM-Wiki → Hermes SkillHub + Hermes Atlas → GitHub). **External skills are a prompt-injection risk and MUST be manually rewritten and stored internally before use.**
- Usage is **tracked per profile**; **Denji** auto-promotes frequently-borrowed skills to permanent enablement during review.
- A **Kensei Dashboard Skills page** gives full visibility + manual overrides.

## 2. Key reframe (discovered during build)

This was **not greenfield**. A half-built `skill-broker` subsystem already existed (`skill-broker` profile, `skill-broker-core` skill, `skill-broker-ledger.py`) plus a dormant central **activity ledger**. The work is consolidating, enforcing, automating and unifying that, not building anew.

## 3. Architecture (target end-state)

```
Discovery (open)      every profile sees the full catalogue → knows what to request
Access (gated)        skill_view loads ONLY if in enabled_skills OR an active grant
                      enabled_skills = the allowlist; always_skills ⊆ enabled_skills
Request               skill_request(skill, task_id, reason) → grant engine (NEVER_GRANT
                      + frequency cap) → temp grant in the ONE ledger
Revoke                on kanban task-completed event → revoke that task's grants;
                      TTL sweep (hourly cron) as fallback
Source/Create         no ≥60-70% match → internal-first (library+llm-wiki → SkillHub+Atlas
                      → GitHub); EXTERNAL = quarantine → manual rewrite → store internal
Promote               Denji reads the ledger; usage ≥ threshold → auto-add to enabled_skills
Curate                grants/loads count as usage so active skills aren't archived
Visibility            Dashboard Skills page reads enabled_skills + ledger
```

**Single source of truth:** the central append-only `~/.hermes/governance/profile-activity-ledger.sqlite` (event types `skill.loaded`, `skill.borrowed`, `skill.denied`, `skill.revoked`, `skill.access.would_block`/`blocked`, plus kanban task events). Read via `query_events()`. Grant logic lives only in `tools/skill_grants.py`.

---

## 4. Phase-by-phase status

### ✅ Phase 1 — Unify the ledger (DONE, committed `e38d7d7a1`)
- Added `query_events()` read API to `hermes_cli/profile_activity_ledger.py`.
- Enabled the activity ledger fleet-wide (`DEFAULT_CONFIG governance.profile_activity_ledger.enabled = True`).
- Refactored `scripts/skill-broker-ledger.py` off its private JSONL onto the central ledger; revocation is a separate append-only `skill.revoked` event. `import-legacy` brought the 4 historical entries across.
- **Conflict resolved:** archived a pre-existing orphaned ledger DB (incompatible older schema, 7,391 rows) to `*.superseded-20260526`.
- Tests: 9.

### ✅ Phase 2 — enabled_skills + shadow-then-enforce (DONE, committed `8143ab993`)
- `agent/skill_utils.py`: `get_enabled_skill_names()` (None = unrestricted/pre-seed; else `enabled_skills ∪ always_skills`), `get_always_skill_names()`, `get_skill_enforcement_mode()` (off|shadow|enforce, fail-open to off).
- `tools/skills_tool.py`: `_skill_access_decision()` wired into `skill_view` after the disabled-check. shadow logs `skill.access.would_block` and still loads; enforce blocks and points to `skill_request`. Profile attribution fixed to resolve from `HERMES_HOME` (gateways don't set `HERMES_PROFILE`).
- `DEFAULT_CONFIG skills.enforcement_mode = "off"`.
- `scripts/seed-enabled-skills.py`: seeds `enabled_skills` from observed `skill.loaded` events.
- Tests: 11.

### ✅ Phase 3 — skill_request + grant engine + auto-revoke (DONE, committed `725c11ca0`)
- `tools/skill_grants.py` (NEW): the single grant engine — `grant_skill` (requires task_id; NEVER_GRANT + frequency cap), `record_deny`, `has_active_grant`, `revoke_by_event_id`, `revoke_grants_for_task`, `sweep_expired_grants`.
- `skill_request` tool added + registered + in the skills toolset; refuses skills not in the library.
- `hermes_cli/kanban_db.py`: auto-revoke a task's grants on completion (non-fatal hook).
- Broker CLI refactored to delegate ALL grant logic to the engine (zero duplication).
- `scripts/sweep-skill-grants.py` + **hourly cron `skill-grant-ttl-sweep`** registered (wrapper at `~/.hermes/scripts/sweep-skill-grants.py`).
- Tests: 9 engine + updated suites. 29 skill tests + 644 regression green.

### ⬜ Phase 4 — Secure sourcing/creation pipeline (NOT STARTED)
Formalise: requirements in → match library + LLM-Wiki for ≥60-70% fit → augment via lead/Denji/skill-research → else source SkillHub + **Hermes Atlas (https://hermesatlas.com/)** → GitHub. **External = quarantine + mandatory manual rewrite by skill-research/Denji before internal storage and grant.** Never load raw external content. Reuse `tools/skills_hub.py` (GitHubSource + `QUARANTINE_DIR`) and the `skill-research` profile.

### ⬜ Phase 5 — Denji auto-promotion (NOT STARTED)
Extend `denji-skill-audit`: query the ledger for per-profile grant/use counts over the window; auto-add to `enabled_skills` above threshold; record a reversible, logged decision. Wire into the weekly audit.

### ⬜ Phase 6 — Curator reconciliation (NOT STARTED)
Ensure grant/load events count as usage so the curator's staleness archival never removes an actively-borrowed skill.

### ⬜ Phase 7 — Kensei Dashboard Skills page (NOT STARTED — task `t_009c287b` on the Apps board)
Columns: name, description, category, enable/disable/delete toggle, per-profile enabled/disabled with override, version + last-review date. Reads `enabled_skills` + ledger; override writes back to profile config (comment-safe) + reload.

---

## 5. ⚠️ Operational rollout still required (even for the built phases)

The code is in place but **enforcement is OFF**. To actually switch the model on:

1. Let the ledger collect `skill.loaded` events for an observation window (a few days of normal fleet operation after the gateways picked up the enabled flag).
2. Seed allowlists: `python3 scripts/seed-enabled-skills.py --days 14 --apply --mode shadow` (writes `enabled_skills` per profile, sets mode to **shadow**).
3. Restart the fleet; watch `skill.access.would_block` events for a window to confirm allowlists are complete (no legitimate load would be blocked).
4. Flip to enforce: re-run seeding with `--mode enforce` (or set `skills.enforcement_mode: enforce`), restart the fleet.

Until step 4, no skill load is gated (full back-compat).

## 6. Conflicts resolved
- Two ledgers → one (broker JSONL retired onto the central SQLite ledger).
- Orphaned incompatible ledger DB → archived.
- Advisory grants → enforced at `skill_view`.
- Manual revoke → auto on task completion (+ TTL).
- Duplicate grant logic (broker vs new) → single engine.
- Open progressive disclosure → discovery-open / load-gated.
- Profile attribution (HERMES_PROFILE unset) → resolved via `get_active_profile_name()`.

## 7. Key files
| File | Purpose |
|---|---|
| `hermes_cli/profile_activity_ledger.py` | central ledger + `query_events` |
| `tools/skill_grants.py` | the grant engine (single source) |
| `tools/skills_tool.py` | `skill_view` enforcement, `skill_request`, `_skill_exists` |
| `agent/skill_utils.py` | enabled/always/mode config helpers |
| `scripts/skill-broker-ledger.py` | broker CLI (thin wrapper over engine) |
| `scripts/seed-enabled-skills.py` | seed allowlists from observed usage |
| `scripts/sweep-skill-grants.py` | TTL grant sweep (hourly cron) |
| `hermes_cli/kanban_db.py` | task-completion auto-revoke hook |

## 8. How to verify
```
# unit + integration
.venv/bin/python -m pytest tests/tools/test_skill_grants_engine.py \
  tests/tools/test_skill_broker_unified_ledger.py \
  tests/tools/test_skill_access_enforcement.py -q       # 29 pass
# broker CLI
python3 scripts/skill-broker-ledger.py status
python3 scripts/skill-broker-ledger.py borrow octacon arxiv t_demo ops   # grant_task_only
python3 scripts/skill-broker-ledger.py borrow octacon governance t_x ops  # denied (NEVER_GRANT)
# ledger
python3 -c "from hermes_cli.profile_activity_ledger import query_events; print(len(query_events()))"
```

## 9. Checklist

**Done**
- [x] Central ledger is the single source of truth (`query_events` API, enabled fleet-wide)
- [x] Orphaned ledger-DB conflict resolved (archived)
- [x] Broker unified onto the central ledger; legacy imported
- [x] `enabled_skills` allowlist model + `always_skills ⊆ enabled_skills`
- [x] `skill_view` enforcement (off/shadow/enforce), defaults off
- [x] Profile attribution fixed (HERMES_HOME-derived)
- [x] Seeding script (observed usage → enabled_skills)
- [x] Single grant engine (`skill_grants.py`); no duplicated logic
- [x] `skill_request` agent tool (registered, in toolset; refuses unknown skills)
- [x] NEVER_GRANT + frequency-cap safety; task_id required
- [x] Auto-revoke on kanban task completion
- [x] TTL sweep + hourly cron
- [x] Phases 1-3 quality-gated, tested (29 skill + 644 regression), committed & pushed

**Not done**
- [ ] **Operational:** seed allowlists, run shadow window, flip to enforce (system is OFF until this)
- [ ] **Phase 4:** secure sourcing/creation pipeline (incl. Hermes Atlas tier + external rewrite gate)
- [ ] **Phase 5:** Denji auto-promotion from the ledger (wire into `denji-skill-audit`)
- [ ] **Phase 6:** curator reconciliation (grants/loads count as usage)
- [ ] **Phase 7:** Kensei Dashboard Skills page (task `t_009c287b`)
- [ ] Update `skill-broker-core` / `skill-research-core` skill docs to reference `skill_request` + the engine
- [ ] Memory/brain note for the new request→grant→revoke→promote flow

## 10. Risks / open items
- Enforcement is off; the model only takes effect after the operational rollout (section 5).
- Frequency cap (6/30d) hard-denies the 7th borrow and forces a Denji decision — confirm the threshold is right for real workloads.
- Sub-profiles with non-standard `HERMES_HOME` resolve to `"custom"`; grants there fail closed (safe but worth noting).
- Phase 4's external-source security gate is the highest-risk piece (prompt injection) and must not be shortcut.

## 11. Commits
- Phase 1: `e38d7d7a1`
- Phase 2: `8143ab993`
- Phase 3: `725c11ca0`
(all on `main`, pushed to `github.com/Sahil-SS9/KenseiAgent`)
