## Recommendation Report

### t_26646ed8 — Discord delivery race: 'cannot schedule new futures after interpreter shutdown'

**What's actually happening:**

The hermes-gateway service (systemd `Restart=always`, `RestartSec=5`) receives SIGTERM and begins shutdown at **08:01:33 BST** on 2026-06-02 (confirmed via journal). The gateway's cron ticker (`_start_cron_ticker` in `gateway/run.py`) runs every **60 seconds** as a daemon thread inside the gateway process. Both affected cron jobs (`mailbox-cleaner-main` and `verify-kensei-fork-patches`) are scheduled at **`0 8 * * *`** — they fire at 08:00:00, within seconds of the gateway restart window.

The delivery chain:
1. Cron agent runs its LLM inference (taking ~4-6 minutes per job)
2. When the agent finishes, `_deliver_result()` in `cron/scheduler.py` tries the **live adapter path** — it calls `safe_schedule_threadsafe(runtime_adapter.send(...), loop)` which invokes `asyncio.run_coroutine_threadsafe(coro, loop)` on the gateway's event loop
3. If the loop is closed/shutting down, `safe_schedule_threadsafe` catches `RuntimeError` and returns `None`
4. Fallback to the **standalone path** — tries `asyncio.run(coro)` in its own thread, which also fails with the same error when the Python interpreter is mid-shutdown
5. The Discord plugin's `_standalone_send` (in `plugins/platforms/discord/adapter.py` line 6330) catches the exception and returns `{"error": "Discord send failed: cannot schedule new futures after interpreter shutdown"}`
6. `_deliver_result` wraps this as `"delivery error: Discord send failed: cannot schedule new futures after interpreter shutdown"` and stores it in `last_delivery_error`

Verified evidence:
- **Mailbox-cleaner-main**: last_run=08:04:30, last_delivery_error recorded, last_status=**ok** (delivery failure is non-fatal)
- **Verify-kensei-fork-patches**: last_run=08:06:32, last_delivery_error recorded, last_status=**ok** (new gateway starts at 08:06:33 — missed by **1 second**)
- **Gateway restart**: SIGTERM at 08:01:33, new process starts at 08:06:33 (a ~5-minute restart window)
- **No retry logic**: `_deliver_result` and `_standalone_send` attempt delivery exactly once and propagate the error
- **No startup grace**: The cron ticker starts immediately when the gateway boots; delivery attempts landing before 08:06:33 hit a dead loop
- **No jitter**: Both crons fire exactly at `0 8 * * *` (minute 0), coinciding with the restart

| # | Option | What happens |
|---|--------|-------------|
| **A** | **Reschedule both crons to `15 8 * * *`** | Move `mailbox-cleaner-main` and `verify-kensei-fork-patches` from `0 8 * * *` to `15 8 * * *` (15 minutes after the hour). This puts a 15-minute buffer between the cron fire time and the ~08:01 restart window, giving the new gateway process 9+ minutes to settle. Zero code changes, 30-second fix via `hermes cron edit` or direct jobs.json edit. Risk: if the restart time ever drifts earlier (before 08:01), the window re-opens. |
| **B** | **Add delivery retry logic to `_deliver_result`** | In `cron/scheduler.py`, catch the "cannot schedule new futures" error in the standalone delivery path and retry once after 30 seconds using a fresh `asyncio.run()` in a new thread. More robust than rescheduling because it handles any future restart-time drift. Requires a ~10-line code change plus a test. Risk: the retry thread could race the new gateway's startup; if the gateway takes >30s extra, the retry also fails. |
| **C** | **Add random jitter to cron fire times** | Add a `fire_jitter_seconds` field to the cron job schema. When set, the scheduler randomly offsets the first run within a window (e.g., `0 8 * * *` with 600s jitter fires at 08:00 + random(0-600s)). Spreads all `0 8 * * *` jobs across the 08:00-08:10 window, so even if a job lands in the restart gap, the others likely don't. Requires schema change, jobs.json migration, and scheduler logic update. Most surgical fix but highest complexity. |

**Default recommendation:** **Option A** — reschedule both affected crons to `15 8 * * *` — because it is a 30-second configuration fix with no code changes, no risk of introducing new bugs, and the 9-minute buffer comfortably clears the observed ~5-minute restart window.