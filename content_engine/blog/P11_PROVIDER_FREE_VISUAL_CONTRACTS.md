# P11 — Provider-free visual contracts

This slice implements the **provider-free** visual contracts for the P11 image
lane. It adds deterministic, testable data contracts that make future local
ComfyUI image work accountable **without activating any image provider**.

## Scope boundary (what this code does NOT do)

- It does **not** call Codex, OpenAI, FAL, ComfyUI, any cloud tool, or any
  browser tool.
- It does **not** generate, publish, schedule, or queue images.
- It does **not** import or merge the frozen legacy P11 branch
  (`p11/media-orchestration-20260722`).
- It does **not** modify `art_director.py`, `blog_illustrator.py`,
  `draft_media.py`, any provider configuration, cron, publishing, queue, or
  approval code.
- Future P10 is local ComfyUI REST on GPU1 only. This slice **intentionally
  does not implement P10**.

## Canonical reference root

The canonical reference root is `/home/kensei/content-references`.

- `manifest.jsonl` — the baseline reference manifest. 262 hash-verified
  reference images. Each row carries `reference_id`, relative `path`,
  `sha256`, `usage_classification`, `collection`, `source`, and
  `provenance_state`.
- `core-pack.jsonl` — 26 visually reviewed core candidates. A core row
  shares its `reference_id` with a baseline row (the same image, visually
  reviewed) and adds `core_role`, `core_tag`, `curation_status`,
  `allowed_roles`, `blocked_roles`, and `visual_rationale`.

### `usage_classification` values

| value             | meaning                                                      | generation-eligible? |
|-------------------|--------------------------------------------------------------|----------------------|
| `permitted`       | Promoted after provenance review.                            | yes                  |
| `review-required`| Visually reviewed but not yet promoted.                       | **no — fail closed** |
| `blocked`         | Explicitly blocked from generation.                          | **no — fail closed** |

Every real `core-pack.jsonl` entry today is `usage_classification =
review-required`. A generation-mode request using any such entry **must fail
closed**. This is enforced by `ReferenceCatalog.references_for_generation`.

## Modules

### `blog/reference_catalog.py`

A stdlib-only catalogue layer.

- `ReferenceRecord` — immutable data object (frozen dataclass).
- `ReferenceCatalog.load(root: Path)` — reads `manifest.jsonl` and the
  optional `core-pack.jsonl`. Strict validation:
  - unique `reference_id` values within each file;
  - safe relative paths (rejects absolute and `..`-escaping paths);
  - the referenced file must exist under `root`;
  - declared `sha256` matches the file content;
  - `usage_classification` is one of the allowed values;
  - every core row must resolve to a baseline row with the same
    `reference_id`, path, and hash (a core row is an enrichment of a baseline
    row, not a new image).
- `records_for_contract()` — returns the visually reviewed core records
  (candidates, not generation-approved input).
- `references_for_generation(ids)` — fails closed if any id is absent, is not
  a core record, or has `usage_classification != "permitted"`.
- No global mutable state. No implicit filesystem root outside the
  caller-provided path.

### `blog/visual_plan.py`

Pure data contracts for the per-article visual plan.

- `VisualPlan` and `VisualAssetPlan` — versioned, immutable data structures.
- `build_visual_plan(article_id, art_brief, assets)` — validates one hero
  plus zero-or-more section assets. Each asset needs a unique role/key,
  exact reference IDs, a selected layout, and the shared
  style/palette/motif. Section assets carry an optional section heading.
- The plan preserves a single shared style, palette, and motif across the
  article while allowing declared layout variants per asset.
- The module never calls an LLM or provider, writes no files, and never
  selects an unreviewed image automatically.
- JSON serialisation is deterministic (sorted keys, compact separators).

### `blog/asset_manifest.py`

Pure output-accountability contracts.

- `AssetManifest` / `GeneratedAssetRecord` — versioned structures.
- A record binds article id, visual-plan digest, prompt digest, selected
  reference IDs, relative output path, output digest, generation timestamp,
  and QA state.
- Rejects absolute/escaping output paths, missing digests, duplicate asset
  keys, and a `published`/`approved`/`rejected` state without explicit QA
  metadata.
- Stores no API key, provider token, or raw private prompt — only a SHA-256
  digest. Any input dict carrying `api_key`, `provider_token`, `token`,
  `secret`, `raw_prompt`, or `prompt` is rejected.
- Deterministic JSON serialisation and parse/round-trip support.

## Promotion path (future P10 owner decision)

A core record is promoted from `review-required` to `permitted` only after a
P10 owner reviews provenance and explicitly upgrades the
`usage_classification` of that individual `reference_id` in
`core-pack.jsonl`. There is no batch promotion, no automatic promotion, and
no promotion path inside this code slice. Until that individual promotion
happens, `references_for_generation` fails closed for that id.

## Tests

- `tests/test_reference_catalog.py` — valid baseline + core load; hash/path/
  ID mismatch rejection; core-set only contract enumeration; fail-closed
  generation for `review-required` and `blocked`; explicit `permitted`
  record succeeds in generation eligibility only.
- `tests/test_visual_plan.py` — deterministic JSON; locked shared
  style/palette/motif; valid hero + section records; reject missing hero,
  duplicate keys, out-of-family style/palette/motif, invalid layout, invalid
  reference IDs.
- `tests/test_asset_manifest.py` — deterministic JSON / parse round trip;
  reject escaping path, missing digests, duplicate key, unapproved published
  state; verify no raw prompt/token-like fields are emitted.

All tests use `tmp_path` fixture data only and never depend on the real
external reference root.
