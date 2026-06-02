#!/usr/bin/env python3
"""KENSEI System Report — single operational pulse.

Consolidates doctor, token health, system stats, service status,
and cron health into one clean digest. Replaces the scattered
doctor-daily, token-health-check, and Phase1 Gmail Verifier cron jobs.
"""

from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

OUTPUT_BASE = Path.home() / ".hermes" / "runbooks" / "system-report"
TOKEN_HEALTH_SCRIPT = Path.home() / ".hermes" / "scripts" / "token_health.py"

HERMES_SERVICES = [
    "hermes-gateway",
    "hermes-dashboard",
    "hermes-workspace",
    "tailscaled",
]


@dataclass
class OutputPaths:
    directory: Path
    json_path: Path
    html_path: Path
    telegram_path: Path


def output_paths(out_dir: Path) -> OutputPaths:
    return OutputPaths(
        directory=out_dir,
        json_path=out_dir / "system-report.json",
        html_path=out_dir / "system-report.html",
        telegram_path=out_dir / "system-report-telegram.txt",
    )


def default_output_dir(now: datetime) -> Path:
    return OUTPUT_BASE / now.strftime("%d-%m-%y")


# ── collectors ──────────────────────────────────────────


def run(cmd: list[str], timeout: int = 30) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.CalledProcessError as e:
        return e.output or ""
    except Exception as e:
        return f"[ERROR: {e}]"


def token_health() -> dict:
    raw = run(["python3", str(TOKEN_HEALTH_SCRIPT)])
    try:
        return json.loads(raw)
    except Exception:
        return {"error": "token_health.py returned invalid JSON", "raw": raw[:500]}


def _is_error_sentinel(s: str) -> bool:
    """run() returns '[ERROR: ...]' on subprocess exceptions; treat as missing data."""
    return s.startswith("[ERROR:")


def system_stats() -> dict:
    disk_raw = run(["df", "-h", "/"]).strip()
    mem_raw = run(["free", "-h"]).strip()
    up = run(["uptime"]).strip()
    tailscale_status = run(["tailscale", "status"], timeout=10)

    # Guard each parse against the error sentinel so disk/mem fields don't
    # silently surface garbage tokens from the error message.
    disk_parts = disk_raw.split("\n")[-1].split() if not _is_error_sentinel(disk_raw) else []
    mem_parts = mem_raw.split("\n")[1].split() if (not _is_error_sentinel(mem_raw) and "\n" in mem_raw) else []

    return {
        "disk_total": disk_parts[1] if len(disk_parts) > 1 else "?",
        "disk_used": disk_parts[2] if len(disk_parts) > 2 else "?",
        "disk_avail": disk_parts[3] if len(disk_parts) > 3 else "?",
        "disk_pct": disk_parts[4] if len(disk_parts) > 4 else "?",
        "mem_total": mem_parts[1] if len(mem_parts) > 1 else "?",
        "mem_used": mem_parts[2] if len(mem_parts) > 2 else "?",
        "mem_avail": mem_parts[6] if len(mem_parts) > 6 else "?",
        "uptime": up.replace("up", "").strip() if up and not _is_error_sentinel(up) else "?",
        "tailscale": "connected" if "Tailscale" in tailscale_status and not _is_error_sentinel(tailscale_status) else "check",
    }


def service_status() -> dict[str, str]:
    result = {}
    for svc in HERMES_SERVICES:
        out = run(["systemctl", "is-active", svc]).strip()
        result[svc.replace("hermes-", "")] = out
    return result


def hermes_version() -> str:
    out = run(["hermes", "--version"]).strip()
    for line in out.split("\n"):
        if line.startswith("v") or "version" in line.lower():
            return line.strip()
    return out or "unknown"


def cron_health() -> dict:
    out = run(["hermes", "cron", "list"])
    total = 0
    ok = 0
    error = 0
    degraded = []

    for line in out.split("\n"):
        if "ok" in line.lower():
            ok += 1
            total += 1
        elif "error" in line.lower() or "fail" in line.lower():
            error += 1
            total += 1
            degraded.append(line.strip())

    if total == 0:
        raw = run(["hermes", "cronjob", "list"])

    return {
        "total": total,
        "ok": ok,
        "error": error,
        "degraded": degraded,
    }


def doctor_highlights() -> dict:
    out = run(["hermes", "doctor"])
    warnings = []
    failures = []

    for line in out.split("\n"):
        stripped = line.strip()
        if stripped.startswith("⚠"):
            # Skip known optional/low-priority/false-positive warnings
            skip_terms = [
                "Nous Portal", "OpenRouter", "docker", "Gemini OAuth", "MiniMax OAuth",
                "codex CLI", "tinker-atropos", "browser-cdp", "discord",
                "DISCORD_BOT_TOKEN", "homeassistant", "kanban", "moa",
                "rl (", "TINKER_API_KEY", "WANDB_API_KEY", "hermes-yuanbao",
                "spotify", "OPENROUTER_API_KEY",
                # 2026-06-02 audit — false positives confirmed via live probes:
                "python-telegram-bot (optional, not installed)",  # optional dep
                "mnemosyne plugin not found",                      # plugin IS active; doctor line is stale
                "xAI OAuth (not logged in)",                       # XAI_API_KEY works (HTTP 200)
                # 2026-06-02 audit — known optional tools:
                "browser-cdp (system dependency not met)",
                "browser (system dependency not met)",
                "computer_use (system dependency not met)",
                "feishu_doc (system dependency not met)",
                "feishu_drive (system dependency not met)",
                "hermes-yuanbao (system dependency not met)",
                "homeassistant (system dependency not met)",
            ]
            if not any(t in stripped for t in skip_terms):
                warnings.append(stripped)
        elif stripped.startswith("✗") or stripped.startswith("❌"):
            failures.append(stripped)

    return {"warnings": warnings, "failures": failures}


# ── classification ─────────────────────────────────────


def classify(payload: dict) -> tuple[str, list[str], list[str], list[str]]:
    """Return (overall, fires, watchlist, healthy)."""
    fires: list[str] = []
    watchlist: list[str] = []
    healthy: list[str] = []

    # services
    svc = payload.get("services", {})
    for name, status in svc.items():
        if status == "active":
            healthy.append(f"Service {name} active")
        else:
            fires.append(f"Service {name} is {status}")

    # cron
    cron = payload.get("cron", {})
    if cron.get("error", 0) > 0:
        watchlist.append(f"{cron['error']} cron job(s) with errors — see attached report")
    if cron.get("total", 0) > 0:
        healthy.append(f"{cron['ok']}/{cron['total']} cron jobs ok")

    # token health
    tokens = payload.get("token_health", {})
    for account in tokens.get("accounts", []):
        email = account.get("email", "unknown")
        if "@" not in email:
            continue  # skip non-email entries like oauth_states
        status = account.get("status", "unknown")
        if status == "expired":
            watchlist.append(f"Token expired: {email}")
        elif status in ("warning", "unknown"):
            watchlist.append(f"Token {status}: {email}")
        elif status == "healthy":
            healthy.append(f"Token ok: {email}")

    # system
    stats = payload.get("system", {})
    try:
        disk_pct = int(stats.get("disk_pct", "0%").replace("%", ""))
        if disk_pct > 90:
            fires.append(f"Disk at {disk_pct}%")
        elif disk_pct > 75:
            watchlist.append(f"Disk at {disk_pct}%")
        else:
            healthy.append(f"Disk {disk_pct}% used ({stats.get('disk_avail', '?')} free)")
    except ValueError:
        pass

    mem_avail = stats.get("mem_avail", "")
    healthy.append(f"Memory {mem_avail} available")

    # doctor
    doc = payload.get("doctor", {})
    for w in doc.get("warnings", []):
        watchlist.append(w)
    for f in doc.get("failures", []):
        watchlist.append(f)

    if fires:
        overall = "degraded"
    elif watchlist:
        overall = "attention"
    else:
        overall = "healthy"

    return overall, fires, watchlist, healthy


# ── recommendation ─────────────────────────────────────


def recommendation(overall: str, fires: list[str], watchlist: list[str]) -> str:
    if fires:
        return f"Fix top fire first: {fires[0]}"
    if watchlist:
        return f"Watch: {watchlist[0]}"
    return "All systems green. No action needed."


# ── renderers ──────────────────────────────────────────


def telegram_text(payload: dict, html_path: Path, include_media_tag: bool = False) -> str:
    """Legacy function name; output is now Discord-safe plain text."""
    now = datetime.fromisoformat(payload["generated_at"])
    overall, fires, watchlist, healthy = classify(payload)

    status_emoji = {"healthy": "✅", "attention": "⚠️", "degraded": "🚨"}
    top_items = fires or watchlist or healthy
    cron = payload.get("cron", {})
    stats = payload.get("system", {})
    signal = recommendation(overall, fires, watchlist)

    lines = [
        f"{status_emoji.get(overall, '⚪')} System report · {now.strftime('%d/%m/%Y %H:%M:%S')}",
        f"checked · {cron.get('ok', 0)}/{cron.get('total', 0)} crons ok · disk {stats.get('disk_pct', '?')}",
        "",
    ]

    section = "Fires" if fires else ("Watchlist" if watchlist else "Healthy")
    if top_items:
        lines.append(section)
        for item in top_items[:5]:
            lines.append(f"• {item}")

    lines.extend(["", f"Action · {signal}"])

    if include_media_tag:
        lines.extend(["", f"MEDIA:{html_path}"])
    else:
        lines.extend(["", f"HTML report: {html_path}"])

    return "\n".join(lines)


def html_text(payload: dict) -> str:
    overall, fires, watchlist, healthy = classify(payload)
    now = datetime.fromisoformat(payload["generated_at"])
    date_label = now.strftime("%A, %B %-d, %Y")
    time_label = now.strftime("%-I:%M %p")

    status_colors = {"healthy": "#22c55e", "attention": "#fbbf24", "degraded": "#ef4444"}
    status_color = status_colors.get(overall, "#a8a29e")

    def section_rows(items: list[str], emoji: str) -> str:
        if not items:
            return ""
        rows = ""
        for i in items:
            rows += f"<tr><td class=\"bullet\">{emoji}</td><td>{html.escape(i)}</td></tr>\n"
        return rows

    fires_rows = section_rows(fires, "🚨")
    watch_rows = section_rows(watchlist, "⚠️")
    healthy_rows = section_rows(healthy, "✅")

    # token health section
    token_rows = ""
    tokens = payload.get("token_health", {}).get("accounts", [])
    for acc in tokens:
        email = acc.get("email", "?")
        status = acc.get("status", "?")
        age = acc.get("age_days", "?")
        color = {"healthy": "#22c55e", "warning": "#fbbf24", "expired": "#ef4444", "unknown": "#a8a29e"}.get(status, "#a8a29e")
        name = email.split("@")[0] if "@" in email else email
        domain = email.split("@")[1] if "@" in email else ""
        token_rows += (
            f"<tr>"
            f"<td style=\"color:{color}; font-weight:600;\">{html.escape(name)}</td>"
            f"<td style=\"color:var(--muted);\">@{html.escape(domain)}</td>"
            f"<td style=\"color:{color};\">{status}</td>"
            f"<td style=\"color:var(--muted);\">{age}d</td>"
            f"</tr>\n"
        )

    # services section
    service_rows = ""
    svc = payload.get("services", {})
    for name, status in svc.items():
        color = "#22c55e" if status == "active" else "#ef4444"
        service_rows += (
            f"<tr>"
            f"<td style=\"font-weight:600;\">{html.escape(name)}</td>"
            f"<td style=\"color:{color};\">{status}</td>"
            f"</tr>\n"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>System Report, {html.escape(date_label)}</title>
<style>
  :root {{ color-scheme: dark; --bg: #11100f; --card: #1c1a18; --muted: #a8a29e; --text: #f5f5f4; --accent: #fbbf24; --line: #34302c; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--text); font: 16px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
  main {{ width: min(720px, calc(100% - 24px)); margin: 0 auto; padding: 28px 0 48px; }}
  header {{ margin-bottom: 20px; }}
  .eyebrow {{ color: var(--accent); font-weight: 700; letter-spacing: .06em; text-transform: uppercase; font-size: 13px; }}
  h1 {{ font-size: 28px; margin: 6px 0 6px; }}
  .summary {{ color: var(--muted); font-size: 14px; margin-top: 4px; }}

  section {{ background: var(--card); border-radius: 12px; margin-bottom: 18px; overflow: hidden; border: 1px solid var(--line); }}

  .section-header {{ padding: 14px 20px; font-weight: 700; font-size: 15px; letter-spacing: .04em; text-transform: uppercase; }}
  .fires    .section-header {{ background: #3b1a1a; color: #fca5a5; }}
  .watch    .section-header {{ background: #3b2e1a; color: #fde68a; }}
  .healthy  .section-header {{ background: #1a2e1a; color: #86efac; }}
  .tokens   .section-header {{ background: #1a2328; color: #67e8f9; }}
  .services .section-header {{ background: #1a1e2e; color: #a5b4fc; }}

  .section-body {{ padding: 14px 20px 18px; }}

  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }}
  tr:last-child td {{ border-bottom: none; }}
  td.bullet {{ width: 32px; text-align: center; font-size: 16px; }}

  footer {{ background: var(--card); border: 1px solid color-mix(in srgb, var(--accent) 40%, var(--line)); border-radius: 12px; padding: 16px 20px; }}
  footer .label {{ color: var(--accent); font-weight: 700; font-size: 13px; text-transform: uppercase; letter-spacing: .04em; margin-bottom: 4px; }}
</style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">KENSEI System Report</div>
    <h1>{html.escape(date_label)}</h1>
    <div class="summary">Generated at {html.escape(time_label)} — {overall}</div>
  </header>

  <section class="services">
    <div class="section-header">Services</div>
    <div class="section-body">
      <table><tbody>{service_rows}</tbody></table>
    </div>
  </section>

  <section class="tokens">
    <div class="section-header">Token Health</div>
    <div class="section-body">
      <table><thead><tr><th>Account</th><th>Provider</th><th>Status</th><th>Age</th></tr></thead><tbody>{token_rows}</tbody></table>
    </div>
  </section>
{f'''  <section class="fires">
    <div class="section-header">Fires</div>
    <div class="section-body"><table><tbody>{fires_rows}</tbody></table></div>
  </section>
|''' if fires else ""}\
{f'''  <section class="watch">
    <div class="section-header">Watchlist</div>
    <div class="section-body"><table><tbody>{watch_rows}</tbody></table></div>
  </section>
|''' if watchlist else ""}\
{f'''  <section class="healthy">
    <div class="section-header">Healthy</div>
    <div class="section-body"><table><tbody>{healthy_rows}</tbody></table></div>
  </section>
|''' if healthy else ""}\
  <footer>
    <div class="label">Recommended Action</div>
    <div style="font-size: 14px; margin-top: 4px;">→ {html.escape(recommendation(overall, fires, watchlist))}</div>
  </footer>
</main>
</body>
</html>"""


def render_report(payload: dict, out_dir: Path, include_media_tag: bool = False) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = output_paths(out_dir)
    html_doc = html_text(payload)
    telegram = telegram_text(payload, paths.html_path, include_media_tag=include_media_tag)

    paths.json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    paths.html_path.write_text(html_doc, encoding="utf-8")
    paths.telegram_path.write_text(telegram, encoding="utf-8")

    return {"telegram": telegram, "html": html_doc}


# ── main ────────────────────────────────────────────────


def build_payload(now: datetime) -> dict:
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "services": service_status(),
        "system": system_stats(),
        "token_health": token_health(),
        "cron": cron_health(),
        "doctor": doctor_highlights(),
        "version": hermes_version(),
    }


def run_report(
    out_dir: Path | None = None,
    include_media_tag: bool = False,
) -> tuple[dict, OutputPaths, dict[str, str]]:
    now = datetime.now(ZoneInfo("Europe/London"))
    out_dir = out_dir or default_output_dir(now)
    payload = build_payload(now)
    rendered = render_report(payload, out_dir, include_media_tag=include_media_tag)
    return payload, output_paths(out_dir), rendered


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate KENSEI System Report")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--print-telegram", action="store_true")
    parser.add_argument("--include-media-tag", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    payload, paths, rendered = run_report(
        out_dir=args.out_dir,
        include_media_tag=args.include_media_tag,
    )
    if args.print_telegram:
        print(rendered["telegram"])
    else:
        print(f"System Report generated: {paths.directory}")
        print(f"JSON: {paths.json_path}")
        print(f"HTML: {paths.html_path}")
        print(f"Telegram: {paths.telegram_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
