# Manual Tools in ~/.hermes/scripts/

These scripts are retained as manual tools for specific operations. They are not referenced by active cron jobs but are useful for ad-hoc tasks.

## Content Approval Workflow
- `approve_draft.sh` - Approve a content draft
- `reject_draft.sh` - Reject a content draft
- `view_draft.sh` - View a content draft

## Utility Scripts
- `kill_modal.sh` - Kill Modal processes
- `secret-vault.sh` - Interact with secret vault
- `git-fetch-all.sh` - Fetch all git remotes
- `profile-tui.py` - Terminal UI for managing Hermes profiles
- `gateway-health.py` - Diagnostic tool for Hermes gateway health
- `cron-output-lint.py` - Linting tool for cron job prompts (used after prompt changes)

These tools are intended for manual use by the operator (Sahil) or automation that invokes them directly.