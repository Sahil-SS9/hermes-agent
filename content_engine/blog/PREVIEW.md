# SahilBlog Back-Population: Local Preview Workflow

## Generating drafts

From `content_engine/`:

```bash
cd /home/kensei/repos/KenseiAgent/content_engine
set -a; . ~/.hermes/.env; set +a

# Generate one post per stream for validation
PYTHONPATH=. ../.venv/bin/python -m blog.backfill --stream ai --limit 1
PYTHONPATH=. ../.venv/bin/python -m blog.backfill --stream pm --limit 1
PYTHONPATH=. ../.venv/bin/python -m blog.backfill --stream builder --limit 1

# Full run (all streams, all topics)
PYTHONPATH=. ../.venv/bin/python -m blog.backfill

# Dry run (text only, no images)
PYTHONPATH=. ../.venv/bin/python -m blog.backfill --dry-run --limit 3
```

## Reviewing drafts locally

Drafts land as `approved: false` MDX in `~/repos/SahilBlog/src/content/blog/`.
They are visible in dev mode but hidden from production builds.

```bash
cd ~/repos/SahilBlog
pnpm install   # first time only
pnpm dev
```

Open the printed localhost URL (usually http://localhost:4321).

Pages to check:
- `/` — home (featured + recent)
- `/ai` — AI essays
- `/blog/pm` — PM insights
- `/blog/builder` — Builder's Log
- `/blog/<slug>` — individual post

Drafts show alongside approved posts in dev. No visual distinction is applied
yet; check `approved: false` in the MDX frontmatter to identify drafts.

## Approving a post

Flip `approved: false` to `approved: true` in the MDX frontmatter, or use:

```python
PYTHONPATH=. ../.venv/bin/python -c "
from blog.blog_publisher import approve
approve('your-post-slug')
"
```

The `approve()` function flips the flag, builds, commits, and pushes.
Only use it when ready to publish.

## Budget tracking

Back-population spend is tracked separately from the monthly cap:

```bash
PYTHONPATH=. ../.venv/bin/python -c "import budget; print(budget.status())"
```

Backfill entries are labelled `backfill:<stream>:<slug>:<image>` in the ledger.
The cap is `BACKFILL_SPEND_CAP_GBP` (default £9), set in `config.py`.

## Re-running

The backfill is idempotent. Re-running skips topics whose slug MDX already
exists in the repo. Safe to interrupt and resume.
