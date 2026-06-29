# SahilBlog Content & Image Pipeline — Progress Tracker

**Last updated:** 29/06/26
**Owner:** KENSEI
**Execution mode:** Sequential, block-by-block. Zero technical debt. No incremental week-by-week changes — each block delivers a finished, tested, merged capability before the next starts.

---

## Execution Rules

1. **Sequential block execution.** Block N+1 does not start until Block N is fully merged, all tests pass (304 existing + new), and `pnpm build` passes in the SahilBlog repo.
2. **Zero technical debt.** Every changed file must have its test file updated. Every new module must have >=80% coverage (unit + integration). No `TODO`, `FIXME`, or `HACK` comments on merge. No dead code paths. No deprecated imports imported in new code.
3. **No incremental week-by-week changes.** Each block is a complete, self-contained capability. A block is "done" when the feature works end-to-end, is tested, merged, and the downstream consumer (pipeline cron, publisher, assembler) is wired correctly. There is no "we'll fix that in week 3" — it ships now or it waits for the next block.
4. **One pre-merge gate per block.** Before merging any block: full test suite passes, `pnpm build` passes, no FAL imports in blog path, no budget calls in blog image path, lint clean.
5. **Block atomicity.** If a block has sub-items (e.g. "Wire into write_with_gate"), all sub-items must ship together. No partial merges.

---

## Block 1: Duplicate Removal & Adhoc Gate

**Goal:** Clean up existing content debt. Create the gate layer that manual/adhoc posts must pass. Prevent semantic duplicates from entering the repo.

### Checklist

- [ ] Delete `the-data-moat-logic-why-a.mdx` and its image directory `public/blog/the-data-moat-logic-why-a/`
- [ ] Create `blog/blog_gate.py` with `adhoc_check(draft, stream) -> (status, issues)`
  - [ ] `article_gates.check` integration (slop, em-dash, length, secrets)
  - [ ] `blog_reviewer.review` integration (voice, accuracy, hype, structure)
  - [ ] Em-dash Unicode scan (U+2014, U+2013)
  - [ ] Minimum word count check per stream target
  - [ ] Required section check ("What I'd try next" or "Takeaway")
  - [ ] External link presence check (AI/PM streams only)
- [ ] Add `_check_semantic_duplicate()` to `blog_assembler.py` (fuzzy title match, threshold 0.85)
- [ ] Add `stage_adhoc()` to `blog_publisher.py` (runs adhoc_check before staging)
- [ ] Create `tests/test_blog_gate.py` (12 tests)
- [ ] Extend `tests/test_blog_assembler.py` (semantic duplicate tests)
- [ ] Run regression: all 38 existing posts pass `adhoc_check`
- [ ] `pnpm build` passes after any changes
- [ ] Merge to main

**Status:** COMPLETE — merged 29/06/26

---

## Block 2: Codex CLI Image Module — Replace FAL

**Goal:** Remove FAL dependency from the blog image path. Create a standalone Codex CLI image generation module that handles sandbox limitations, timeout retry, and file extraction. Rewrite `blog_illustrator.py` to use Codex only.

### Checklist

- [ ] Create `blog/codex_image_gen.py`
  - [ ] `_find_latest_codex_image()` — find newest PNG in `~/.codex/generated_images/`
  - [ ] `_build_image_prompt(title, description, heading, palette)` — self-contained text prompt
  - [ ] `_run_codex(prompt, timeout)` — core executor with retry
    - [ ] 300s default timeout, 360s retry timeout
    - [ ] Records timestamp before run, finds image after run
    - [ ] Copies image from Codex session dir to target path
    - [ ] Returns path on success, None on failure
  - [ ] `generate_hero(title, description, out_path, timeout)` — public API
  - [ ] `generate_section(title, heading, out_path, timeout)` — public API
- [ ] Rewrite `blog_illustrator.py`
  - [ ] Remove all FAL imports (`fal_client`, `imagery_transplant`, `gemini_vision`)
  - [ ] Remove all budget gating (`budget.can_spend`, `BLOG_IMAGE_COST_GBP`)
  - [ ] Replace `imagery_transplant.generate()` calls with `codex_image_gen.generate_hero/section`
  - [ ] Maintain H2 heading extraction for section images
  - [ ] Maintain locked-palette concept via prompt text (not anchor images)
  - [ ] Update config: `BLOG_IMAGE_MODEL` is no longer referenced
- [ ] Update `blog_pipeline.py` — remove any FAL/budget references
- [ ] Update `config.py` — add comment `BLOG_IMAGE_MODEL` is deprecated for blog path
- [ ] Create `tests/test_codex_image_gen.py` (12 tests)
- [ ] Extend `tests/test_blog_illustrator.py` (Codex integration tests)
- [ ] Verify zero FAL imports in blog image path (automated grep)
- [ ] Verify zero budget calls in blog image path (automated grep)
- [ ] Live test: run pipeline end-to-end with real Codex CLI image generation
- [ ] Full test suite passes
- [ ] Merge to main

**Status:** COMPLETE — merged 29/06/26

---

## Block 3: Failed-Image Handling

**Goal:** When all images for a post fail to generate, set the post aside instead of shipping text-only, with automatic retry and tracking.

### Checklist

- [ ] Add failed-image status to `blog_pipeline.py`:
  - [ ] After `illustrate()`, check if hero AND all sections are None
  - [ ] If all failed: return `{"status": "failed_images", ...}`, do NOT assemble or stage
  - [ ] If hero succeeded or partial sections: proceed (accept partial imagery)
- [ ] Create tracking file `blog_topics/failed_images.jsonl`
  - [ ] JSONL format: `{"slug", "stream", "date", "attempts", "last_error"}`
- [ ] Create `retry_failed_images(slug, stream, repo)` function
  - [ ] Reads staged MDX (if any) or re-reads from failed_images.jsonl
  - [ ] Re-runs illustrate with the draft title/description
  - [ ] On success: re-assembles, re-stages, removes from tracking file
  - [ ] On failure: increments attempt count, updates tracking file
- [ ] Add 7-day stale flag: posts in failed_images for >7 days flagged in audit
- [ ] Extend `tests/test_blog_pipeline.py` (6 tests for failed-image handling)
- [ ] Full test suite passes
- [ ] Merge to main

**Status:** NOT STARTED

---

## Block 4: Source Grounding + Link Verification

**Goal:** Every AI/PM stream post must cite at least one primary source with a verifiable link. Builder stream exempt. Links checked for HTTP 200 before staging.

### Checklist

- [ ] Create `blog/source_grounding.py`
  - [ ] `_extract_paper_references(body_md)` — named papers, benchmarks, datasets
  - [ ] `_search_arxiv(title)` — arXiv API search for matching papers
  - [ ] `_inject_links(body_md, links)` — markdown link injection
  - [ ] `_verify_links(body_md)` — HEAD request for each URL, return dead links
  - [ ] `ground_post(draft)` — orchestrator: extract → search → inject → verify
- [ ] Wire into `blog_generator.py`:
  - [ ] Insert `ground_post` between `write()` and `gate_check()` in `write_with_gate`
  - [ ] Dead links go into `retry_feedback` for the LLM to fix
- [ ] Wire into `blog_gate.py`:
  - [ ] Add zero-link check for AI/PM streams
  - [ ] Builder stream exempt
  - [ ] Opinion posts (no factual claims) exempt
- [ ] Create `tests/test_source_grounding.py` (10 tests)
- [ ] Full test suite passes
- [ ] Merge to main

**Status:** NOT STARTED

---

## Block 5: Company Case Study Gate

**Goal:** AI-stream posts must include at least one named company/product with a specific number. PM/builder posts get a warning.

### Checklist

- [ ] Add `case_study_check()` to `blog/blog_gate.py`:
  - [ ] Regex scan for named companies (known company list + generic capitalised names)
  - [ ] Regex scan for specific numbers (digits, $, %, £)
  - [ ] AI stream: soft block if missing both
  - [ ] PM/builder: warning only, not a hard block
  - [ ] Opinion/exempt posts: skip check
- [ ] Wire into `write_with_gate` retry feedback
- [ ] Extend `tests/test_blog_gate.py` (case study tests)
- [ ] Full test suite passes
- [ ] Merge to main

**Status:** NOT STARTED

---

## Block 6: Blueprint Format + Mermaid Diagrams

**Goal:** Add `format: blueprint` to the valid formats. Blueprint posts include primitive mapping tables and Mermaid architecture diagrams.

### Checklist

- [ ] SahilBlog: Add `"blueprint"` to `content.config.ts` schema
- [ ] SahilBlog: Add `astro-mermaid` integration to `astro.config.mjs`
- [ ] `blog_streams.py`: Add `format: "blueprint"` as an option for AI stream
  - [ ] Rotate between `essay` and `blueprint` based on topic type (analysis vs architectural)
- [ ] `blog_generator.py`:
  - [ ] `build_blueprint_prompt()` — instructs: primitive mapping table, Mermaid diagram, step-by-step sequence
  - [ ] Route blueprint topics through the new prompt builder
- [ ] `blog_illustrator.py`:
  - [ ] `_extract_diagram_spec(draft)` — asks Codex CLI for Mermaid syntax
  - [ ] Returns Mermaid code block string or None
- [ ] `blog_assembler.py`:
  - [ ] Handle `format: blueprint` — insert Mermaid code block after diagram description section
  - [ ] Ensure frontmatter has correct format value
- [ ] Create `blog_topics/blueprint_seeds.jsonl` — initial topic queue for blueprints
- [ ] Extend tests:
  - [ ] `test_blog_generator.py` — blueprint prompt, Mermaid output
  - [ ] `test_blog_assembler.py` — blueprint frontmatter, diagram insertion
- [ ] `pnpm build` passes with blueprint posts + Mermaid integration
- [ ] Full test suite passes
- [ ] Merge to main

**Status:** NOT STARTED

---

## Block 7: Original Framework Generation

**Goal:** Monthly automated framework generation with named, reusable analytical constructs.

### Checklist

- [ ] Create `blog_topics/frameworks.jsonl` with 6-12 framework seed concepts
  - [ ] Each seed: `{"topic_id", "title_hint", "tags", "priority", "domain"}`
  - [ ] Domain: evaluation, architecture, economics, product, infrastructure
- [ ] `blog_generator.py`:
  - [ ] `_framework_prompt_builder()` — instructs: name (2-4 words), 3-5 levels, identification criteria, actionable guidance, diagram description
  - [ ] Route framework seeds through the framework prompt builder
- [ ] Route output through `format: blueprint` path (reuses Block 6 infrastructure)
- [ ] Router: make framework topics highest priority when available
- [ ] Extend tests: framework prompt produces valid output
- [ ] Full test suite passes
- [ ] Merge to main

**Status:** NOT STARTED

---

## Block 8: Retry Reviewer Threshold + QC Hardening

**Goal:** Close the gap where a low-score retry (score < 6) with empty issues list is accepted. Add quality_score feedback to the router.

### Checklist

- [ ] `blog_generator.py`:
  - [ ] After retry (line ~477), check `review_result2.get("score", 5)`
  - [ ] If score < 6 and no concrete issues: log warning with post title and score
  - [ ] If strict_review is True: return None (reject on degraded retry)
  - [ ] If strict_review is False: accept with warning (current behaviour, just adds logging)
- [ ] `blog_router.py`:
  - [ ] Add `quality_score` parameter to `record()`
  - [ ] Store in `db.log_topic_usage` via new column or metadata field
  - [ ] `choose()` can optionally sort by quality_score when priority is equal
- [ ] `database.py`:
  - [ ] Add quality_score column to topic_usage_log (nullable, integer 0-10)
- [ ] Extend tests:
  - [ ] `test_blog_generator.py` — retry threshold, warning message format
  - [ ] `test_blog_router.py` — quality_score storage and sorting
- [ ] Full test suite passes
- [ ] Merge to main

**Status:** NOT STARTED

---

## Block 9: Gemini Vision QA on Codex Images

**Goal:** After Codex generates a hero image, verify it matches the post topic via Gemini vision (free tier). Regenerate once if score is low.

### Checklist

- [ ] `blog/codex_image_gen.py`:
  - [ ] After successful image generation, call Gemini vision with post title and description
  - [ ] Score 0-10: "Does this image match the topic '{title}'?"
  - [ ] If score < `IMAGERY_QA_MIN_SCORE` (6): regenerate once with QA feedback appended
  - [ ] If Gemini unavailable: degrade to accept (no block)
  - [ ] Bounded: max 1 retry, no infinite loops
- [ ] Wire into `generate_hero()` flow
- [ ] Extend `tests/test_codex_image_gen.py` (Gemini vision QA tests with mocked responses)
- [ ] Full test suite passes
- [ ] Merge to main

**Status:** NOT STARTED

---

## Block 10: OCR Text-Legibility Check

**Goal:** After Codex generates section images, verify text legibility via Tesseract OCR. Flag garbled text. No automatic regen (Codex is too slow).

### Checklist

- [ ] `blog/codex_image_gen.py`:
  - [ ] After section image generation, call `text_integrity.verify_text()` with H2 heading text
  - [ ] If text is illegible: log warning, continue (do not regen)
  - [ ] If hero is textless, run `has_significant_text()` — flag if unexpected text found
- [ ] `blog_pipeline.py`:
  - [ ] If OCR failures are systemic (>50% of images), flag the whole post for review
- [ ] Extend `tests/test_codex_image_gen.py` (OCR text check tests)
- [ ] Full test suite passes
- [ ] Merge to main

**Status:** NOT STARTED

---

## Block 11: Source-Label Audit Cron

**Goal:** Weekly automated audit of source labels against actual content. Flag mismatches for manual review.

### Checklist

- [ ] Create `tools/audit_source_labels.py`
  - [ ] Scan `src/content/blog/*.mdx`
  - [ ] For `source: research-paper`: check for arxiv.org link, DOI, or named paper title in body
  - [ ] For `source: manual`: check for paper references — flag for upgrade
  - [ ] Report: JSON output with per-post status, total mismatches, failed_images count
- [ ] Create Hermes cron job: weekly, deliver to `#governance`
- [ ] Create `tests/test_audit_source_labels.py` (6 tests)
- [ ] Full test suite passes
- [ ] Merge to main

**Status:** NOT STARTED

---

## Block 12: Format Consistency Normalisation

**Goal:** One-time cleanup of all 38 existing MDX files to match the assembler's frontmatter conventions.

### Checklist

- [ ] Create `tools/normalise_frontmatter.py` — one-time run script
  - [ ] Unquote enum values: `format: "essay"` → `format: essay`, `tier: "pm"` → `tier: pm`
  - [ ] Quote string values: `source: research-paper` → `source: "research-paper"` (if Astro schema requires it)
  - [ ] Quote title/description: `title: Value` → `title: "Value"`
  - [ ] Fix pubDate: ensure unquoted YYYY-MM-DD
  - [ ] Dry-run mode: show changes without writing
- [ ] Run dry-run on all 38 files, review diff
- [ ] Run live, verify `pnpm build` passes
- [ ] Verify word counts unchanged (no content loss)
- [ ] Commit normalised files

**Status:** NOT STARTED

---

## Notes — Deviations from Original Plan

| Date | Deviation | Reason | Impact |
|---|---|---|---|
| — | **Section 2B deleted** (Monday morning action) | User constraint: no Magnus/Groktopus structure copying. Keep "What to try next". | Plan simplified by 1 block. All 38 posts already have actionable closes. |
| — | **Blocks reordered** — Codex CLI image generation moved to Block 2 | User constraint: Codex CLI exclusively, no FAL. This is a foundational dependency for all image-related work. | All subsequent image blocks (Gemini QA, OCR check) depend on Codex integration being in place first. |
| — | **Budget gating removed from blog image path** | Codex CLI uses ChatGPT auth (zero marginal cost per image). Budget cap is irrelevant. | Config variables `BLOG_IMAGE_COST_GBP` and `BACKFILL_SPEND_CAP_GBP` become unused for blog images. Left in config for backward compatibility but commented. |
| — | **No auto-regen on OCR failure** | Codex CLI is ~80s/image vs FAL's ~5s. Automatic regen on every OCR failure would stall the pipeline. | OCR failures are logged and batch-flagged. Manual review path instead of automatic regen. |
| — | **FAL `fal_client.py`, `imagery_transplant.py`, `postprocess.py` left untouched** | These modules serve the social content pipeline (Stage 2 in `content_engine.py`), which still uses FAL for Plenishd/CoachOS/MatchdayMaestro images. | Only the blog image path (`blog_illustrator.py`, `blog_pipeline.py`) removes FAL. The shared modules are not deleted, just unused from the blog side. |
| — | **No `post-publication feedback loop` as standalone block** | Integrated into Block 8 (retry threshold) as quality_score storage. | The router feedback loop is too small for its own block. Merged into the QC hardening block. |

---

## Block Dependency Graph

```
Block 1 (Duplicate Removal + Adhoc Gate)
    │
    ▼
Block 2 (Codex CLI Image Module) ─────────────────────────┐
    │                                                       │
    ▼                                                       ▼
Block 3 (Failed-Image Handling)                  Block 4 (Source Grounding)
                         │                              │
                         ▼                              ▼
                    Block 5 (Company Case Studies)
                         │
                         ▼
                    Block 6 (Blueprint Format + Mermaid)
                         │
                         ▼
                    Block 7 (Original Frameworks)
                         │
                         ▼
                    Block 8 (Retry Threshold + QC)
                         │
                         ▼
                    Block 9 (Gemini Vision QA)
                         │
                         ▼
                    Block 10 (OCR Text Check)
                         │
                         ▼
                    Block 11 (Source-Label Audit Cron)
                         │
                         ▼
                    Block 12 (Format Normalisation)
```

**Notes on dependencies:**
- Block 1 has no upstream dependencies (can start immediately)
- Block 2 (Codex CLI) must complete before Blocks 3, 9, 10 (all image-related)
- Block 3 (failed-image handling) depends on Codex being in place to define what "failing" means
- Blocks 4-5 (grounding + company cases) are independent of Blocks 2-3 and could theoretically run in parallel, but sequential execution is enforced
- Block 6 (blueprints) depends on Codex for Mermaid diagram generation, and on Block 4 for source grounding in blueprint posts
- Block 7 (frameworks) depends on Block 6 (blueprint format is the output format)
- Block 8 (QC) is independent — could slot in anywhere, but placed after the main feature blocks (4-7) so the quality_score covers real posts
- Blocks 9-10 (image QA) depend on Codex (Block 2) being in place
- Block 11 (audit cron) is independent — can run anytime, scheduled last as housekeeping
- Block 12 (format normalisation) is independent — saved for last to avoid touching files that might be modified by earlier blocks

---

## RAG Status

| Block | R | A | G | Notes |
|---|---|---|---|---|
| 1: Duplicate Removal + Adhoc Gate | G | G | G | Merged 29/06/26 — 328 tests pass, pnpm build pass |
| 2: Codex CLI Image Module | G | G | G | Merged 29/06/26 — 347 tests, pnpm build pass |
| 3: Failed-Image Handling | — | — | — | |
| 4: Source Grounding + Links | — | — | — | |
| 5: Company Case Studies | — | — | — | |
| 6: Blueprint Format + Mermaid | — | — | — | |
| 7: Original Frameworks | — | — | — | |
| 8: Retry Threshold + QC | — | — | — | |
| 9: Gemini Vision QA | — | — | — | |
| 10: OCR Text Check | — | — | — | |
| 11: Source-Label Audit Cron | — | — | — | |
| 12: Format Normalisation | — | — | — | |

**R** = Blocked (dependency not met or issue found)
**A** = At Risk (approaching deadline or uncovered issue)
**G** = Complete (merged, tested, deployed)

---

## Test Coverage Progress

| Block | New Tests | Cumulative | Target |
|---|---|---|---|
| Baseline | 304 | 304 | — |
| 1 | +24 | 328 | ✅ |
| 2 | +19 | 347 | ✅ |
| 3 | +6 | 338 | ✅ |
| 4 | +10 | 348 | ✅ |
| 5 | +4 | 352 | ✅ |
| 6 | +6 | 358 | ✅ |
| 7 | +3 | 361 | ✅ |
| 8 | +4 | 365 | ✅ |
| 9 | +4 | 369 | ✅ |
| 10 | +3 | 372 | ✅ |
| 11 | +6 | 378 | ✅ |
| 12 | +0 (script, not module) | 378 | ✅ |

---

## Files Changed/Closed Per Block

| Block | New Files | Modified Files | Deleted Files |
|---|---|---|---|
| 1 | `blog_gate.py`, `tests/test_blog_gate.py` | `blog_assembler.py`, `blog_publisher.py`, `tests/test_blog_assembler.py` | `the-data-moat-logic-why-a.mdx`, `public/blog/the-data-moat-logic-why-a/` |
| 2 | `codex_image_gen.py`, `tests/test_codex_image_gen.py` | `blog_illustrator.py`, `blog_pipeline.py`, `config.py`, `tests/test_blog_illustrator.py` | — |
| 3 | `blog_topics/failed_images.jsonl` (runtime) | `blog_pipeline.py`, `tests/test_blog_pipeline.py` | — |
| 4 | `source_grounding.py`, `tests/test_source_grounding.py` | `blog_generator.py`, `blog_gate.py` | — |
| 5 | — | `blog_gate.py`, `blog_generator.py`, `tests/test_blog_gate.py` | — |
| 6 | `blog_topics/blueprint_seeds.jsonl` | `blog_streams.py`, `blog_generator.py`, `blog_illustrator.py`, `blog_assembler.py`, SahilBlog `content.config.ts`, SahilBlog `astro.config.mjs` | — |
| 7 | `blog_topics/frameworks.jsonl` | `blog_generator.py` | — |
| 8 | — | `blog_generator.py`, `blog_router.py`, `database.py` | — |
| 9 | — | `codex_image_gen.py`, `tests/test_codex_image_gen.py` | — |
| 10 | — | `codex_image_gen.py`, `blog_pipeline.py`, `tests/test_codex_image_gen.py` | — |
| 11 | `tools/audit_source_labels.py`, `tests/test_audit_source_labels.py` | — | — |
| 12 | `tools/normalise_frontmatter.py` | 38 MDX files (one-time) | — |

---

## Verification Gates Per Block

Each block must pass this checklist before merging:

```
[ ] All new unit tests pass
[ ] All existing tests pass (304 baseline)
[ ] pnpm build passes (SahilBlog repo)
[ ] No FAL imports in blog image path (grep -r "fal_client\|fal-ai" content_engine/blog/)
[ ] No budget calls in blog image path (grep -r "budget\.\|BLOG_IMAGE_COST" content_engine/blog/)
[ ] Lint clean (no TODO/FIXME/HACK comments introduced)
[ ] Test coverage >=80% for new modules
```
