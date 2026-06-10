"""Hard monthly spend cap for paid image generation.

Free paths (local generation, Pillow finishing) never touch this. Only paid
FAL calls (e.g. gpt-image-2 hero fallback) check can_spend() and record().
Once the month's cap is hit, callers degrade to the free path instead of
spending. Ledger is a small JSON file; rolls over by calendar month.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

_LEDGER = Path(__file__).resolve().parent / "output" / "spend_ledger.json"

# Single source of truth for the monthly cap: config.MONTHLY_BUDGET_GBP,
# overridable per-environment. Previously this module hardcoded £5 while
# config said £10, and generation silently degraded to the cheapest model.
def _default_cap() -> float:
    env = os.getenv("CONTENT_SPEND_CAP_GBP", "").strip()
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    try:
        from config import MONTHLY_BUDGET_GBP
        return float(MONTHLY_BUDGET_GBP)
    except Exception:  # noqa: BLE001
        return 5.0


_CAP_GBP = _default_cap()
_lock = Lock()


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _load() -> dict:
    try:
        data = json.loads(_LEDGER.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    if data.get("month") != _month():
        data = {"month": _month(), "spent_gbp": 0.0, "calls": 0}
    return data


def _save(data: dict) -> None:
    _LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _LEDGER.write_text(json.dumps(data, indent=2))


def can_spend(cost_gbp: float, cap_gbp: float = _CAP_GBP) -> bool:
    """True if a paid call of ``cost_gbp`` keeps the month within the cap."""
    with _lock:
        return _load().get("spent_gbp", 0.0) + cost_gbp <= cap_gbp


def record(cost_gbp: float, label: str = "") -> dict:
    """Record a paid spend. Returns the updated ledger."""
    with _lock:
        data = _load()
        data["spent_gbp"] = round(data.get("spent_gbp", 0.0) + cost_gbp, 4)
        data["calls"] = data.get("calls", 0) + 1
        data.setdefault("log", []).append(
            {"ts": datetime.now(timezone.utc).isoformat(), "gbp": cost_gbp, "label": label}
        )
        data["log"] = data["log"][-200:]
        _save(data)
        return data


def status(cap_gbp: float = _CAP_GBP) -> dict:
    d = _load()
    spent = d.get("spent_gbp", 0.0)
    return {"month": d["month"], "spent_gbp": spent, "remaining_gbp": round(cap_gbp - spent, 4), "calls": d.get("calls", 0)}


if __name__ == "__main__":
    print(json.dumps(status(), indent=2))
