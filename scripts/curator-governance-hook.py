#!/usr/bin/env python3
"""
curator-governance-hook.py — Kensei governance validation layer
Runs AFTER each Hermes curator pass. Validates decisions against Kensei rules.

1. Read curator's last run report
2. For each skill the curator proposes to archive:
   - Check if it's in any profile's always_skills or enabled_skills
   - If yes: OVERRIDE — re-pin, log to logboard, flag as blocked
   - If no: allow
3. For each NEW skill the curator discovered:
   - Classify by category path → lead profile
   - If confidence >= 80%: add to profile's enabled_skills, set adoption_status: dynamic
   - If confidence < 80%: flag for Denji manual review
4. Post summary to stdout (cron delivers to #governance)
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import yaml
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(os.environ.get("HOME", str(Path.home()))) / ".hermes"
SKILLS_DIR = BASE / "skills"
PROFILES_DIR = BASE / "profiles"
STATE_FILE = SKILLS_DIR / ".curator_state"
GOVERNANCE_LOG = BASE / "governance" / "logboard"
LOCK_FILE = BASE / ".curator_governance_hook.lock"

# ── Classification rules: category path → lead profile ──
CATEGORY_TO_LEAD = {
    "devops": "wesker",
    "governance": "kensei",
    "security": "wesker",
    "social-media": "ceecee",
    "software-development": "octacon",
    "research": "remii",
    "creative": "dezzy",
    "design": "dezzy",
    "infrastructure": "octacon-infra",
    "productivity": "gojo",
    "dogfood": "quan",
    "autonomous-ai-agents": "octacon",
    "github": "octacon",
    "email": "gojo",
    "training": "remii",
    "media": "ceecee",
    "mcp": "wesker",
    "mlops": "remii",
    "note-taking": "light",
    "red-teaming": "wesker",
    "smart-home": "wesker",
    "skills": "denji",
    "gaming": "gojo",
}

_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def warn(msg: str) -> None:
    """Log a warning to stderr so cron delivery captures it."""
    print(f"[governance-hook] WARNING: {msg}", file=sys.stderr)


def acquire_lock() -> bool:
    """Prevent concurrent hook runs via PID lockfile."""
    if LOCK_FILE.exists():
        try:
            old_pid = int(LOCK_FILE.read_text().strip())
            # Check if the old process is still alive
            os.kill(old_pid, 0)
            warn(f"Another hook instance is running (PID {old_pid}). Exiting.")
            return False
        except (OSError, ValueError):
            # Stale lock — old process is dead
            LOCK_FILE.unlink(missing_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def release_lock() -> None:
    LOCK_FILE.unlink(missing_ok=True)


def _valid_skill_name(skill_name: str) -> bool:
    return bool(_SKILL_NAME_RE.match(str(skill_name)))


def _safe_json_load(raw_val):
    """Try to parse a JSON-encoded string value; return list or fallback."""
    if not isinstance(raw_val, str):
        return raw_val
    try:
        parsed = json.loads(raw_val)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _extract_skills_from_block(skills_block: dict, profile_name: str,
                               profile_skills: dict) -> None:
    """Extract always_skills + enabled_skills from a config block."""
    if not isinstance(skills_block, dict):
        return
    for key in ("always_skills", "enabled_skills"):
        raw = _safe_json_load(skills_block.get(key, []))
        if isinstance(raw, list):
            for s in raw:
                s = str(s).strip()
                if s and s != "None" and not s.startswith("/"):
                    profile_skills.setdefault(s, []).append(profile_name)


def load_profile_skills():
    """Returns {skill_name: [profile_names]} from root + all profile configs."""
    profile_skills = {}

    # Root config
    try:
        with open(BASE / "config.yaml") as f:
            root = yaml.safe_load(f) or {}
        _extract_skills_from_block(root.get("skills", {}), "root", profile_skills)
    except FileNotFoundError:
        warn("Root config.yaml not found — no root skills loaded")
    except (yaml.YAMLError, PermissionError) as e:
        warn(f"Failed to parse root config.yaml: {e}")

    # Profile configs
    if PROFILES_DIR.exists() and PROFILES_DIR.is_dir():
        for profile_dir in sorted(PROFILES_DIR.iterdir()):
            if not profile_dir.is_dir():
                continue
            if profile_dir.name.startswith((".", "_")):
                continue
            cfg = profile_dir / "config.yaml"
            if not cfg.exists():
                continue
            try:
                with open(cfg) as f:
                    data = yaml.safe_load(f) or {}
                _extract_skills_from_block(
                    data.get("skills", {}), profile_dir.name, profile_skills
                )
            except (yaml.YAMLError, PermissionError, FileNotFoundError) as e:
                warn(f"Failed to parse config for profile {profile_dir.name}: {e}")

    return profile_skills


def classify_skill(skill_name: str):
    """Determine suggested lead profile for an unassigned skill."""
    if not _valid_skill_name(skill_name):
        return None, 0
    # Use Path.rglob instead of subprocess find — faster, no injection risk
    # **/ matches at any directory depth (some skills are top-level, some nested)
    matches = [
        p for p in SKILLS_DIR.glob(f"**/{skill_name}/SKILL.md")
        if "_archived" not in str(p)
    ]
    if not matches:
        return None, 0

    # Prefer non-archived; deterministic sort
    matches.sort(key=lambda p: str(p))
    rel = matches[0].relative_to(SKILLS_DIR)
    parts = rel.parts
    category = parts[0] if len(parts) >= 2 else "unknown"

    lead = CATEGORY_TO_LEAD.get(category, "kensei")
    confidence = 80 if category in CATEGORY_TO_LEAD else 0
    return lead, confidence


def read_curator_report():
    """Read the most recent curator run report. Returns dict or None."""
    if not STATE_FILE.is_file():
        return None
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        warn(f"Failed to read curator state file: {e}")
        return None

    report_path = state.get("last_report_path", "")
    if not report_path or not os.path.exists(report_path):
        return None

    run_json = Path(report_path) / "run.json"
    if not run_json.is_file():
        return None
    try:
        with open(run_json) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        warn(f"Failed to read curator run.json: {e}")
        return None


def add_skill_to_enabled(skill_name: str, profile_name: str):
    """Add skill to profile's enabled_skills. Uses atomic write."""
    if not _valid_skill_name(skill_name):
        return False, "invalid skill name"

    if profile_name == "root":
        cfg_path = BASE / "config.yaml"
    else:
        cfg_path = PROFILES_DIR / profile_name / "config.yaml"

    if not cfg_path.exists():
        return False, "config not found"

    try:
        with open(cfg_path) as f:
            data = yaml.safe_load(f) or {}

        skills_block = data.setdefault("skills", {})
        if skills_block is None or not isinstance(skills_block, dict):
            skills_block = {}
            data["skills"] = skills_block

        enabled = skills_block.get("enabled_skills", [])
        if enabled is None or not isinstance(enabled, list):
            enabled = []

        if skill_name in enabled:
            return True, "already in enabled_skills"

        enabled.append(skill_name)
        skills_block["enabled_skills"] = enabled

        # Atomic write: temp file + os.replace
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=cfg_path.parent, prefix=".tmp_", suffix=".yaml"
        )
        try:
            with os.fdopen(tmp_fd, "w") as f:
                yaml.dump(data, f, sort_keys=False, default_flow_style=False)
            os.replace(tmp_path, cfg_path)
        except Exception:
            os.unlink(tmp_path)
            raise

        return True, "added"
    except Exception as e:
        return False, str(e)


def set_adoption_status(skill_name: str, status: str):
    """Set adoption_status in skill's SKILL.md frontmatter. Atomic write."""
    if not _valid_skill_name(skill_name):
        return False, "invalid skill name"

    matches = [
        p for p in SKILLS_DIR.glob(f"**/{skill_name}/SKILL.md")
        if "_archived" not in str(p)
    ]
    if not matches:
        return False, "skill not found on disk"

    skill_path = matches[0]

    try:
        with open(skill_path) as f:
            content = f.read()

        # Proper frontmatter parsing: only match between first two --- delimiters
        if content.startswith("---"):
            end_idx = content.find("---", 3)
            if end_idx == -1:
                return False, "malformed frontmatter — no closing ---"
            frontmatter = content[3:end_idx]
            body = content[end_idx + 3:]

            if "adoption_status:" in frontmatter:
                frontmatter = re.sub(
                    r"^adoption_status:.*",
                    f"adoption_status: {status}",
                    frontmatter,
                    flags=re.MULTILINE
                )
            else:
                frontmatter += f"\nadoption_status: {status}"

            new_content = f"---{frontmatter}---{body}"
        else:
            # No frontmatter at all — prepend one
            new_content = f"---\nadoption_status: {status}\n---\n{content}"

        # Atomic write
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=skill_path.parent, prefix=".tmp_", suffix=".md"
        )
        try:
            with os.fdopen(tmp_fd, "w") as f:
                f.write(new_content)
            os.replace(tmp_path, skill_path)
        except Exception:
            os.unlink(tmp_path)
            raise

        return True, "updated"
    except Exception as e:
        return False, str(e)


def log_event(event_type: str, payload: dict) -> None:
    """Log governance event to the logboard. Best-effort — never crashes."""
    try:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        log_path = GOVERNANCE_LOG / f"curator-governance-{today}.mdl"
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Avoid key collisions with ts/event
        safe_payload = {k: v for k, v in payload.items()
                       if k not in ("ts", "event")}
        entry = {"ts": ts, "event": event_type, **safe_payload}

        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        warn(f"Failed to write governance log: {e}")


def main():
    profile_skills = load_profile_skills()
    print(f"Loaded {len(profile_skills)} skills referenced by profiles")

    report = read_curator_report()

    if report is None:
        print("No curator report found — curator may not have run yet.")
        print("This is expected on first run (curator is seeded, will run after one interval).")
        return

    print(f"\nCurator report: {report.get('started_at', 'unknown')}")
    c = report.get("counts", {}) or {}
    print(f"  Checked: {c.get('checked', 0)}")
    print(f"  Archived: {c.get('archived_this_run', 0)}")
    print(f"  Added: {c.get('added_this_run', 0)}")

    # ── Validate proposed archivals ──
    archival_overrides = []
    proposed = set(report.get("archived", []) or [])
    proposed |= set(report.get("pruned_names", []) or [])

    for skill_name in sorted(proposed):
        if skill_name in profile_skills:
            archival_overrides.append((skill_name, profile_skills[skill_name]))
            # Re-pin with exit code checking
            if _valid_skill_name(skill_name):
                result = subprocess.run(
                    ["hermes", "curator", "pin", skill_name],
                    capture_output=True, text=True
                )
                if result.returncode != 0:
                    warn(f"Re-pin failed for '{skill_name}' (exit {result.returncode}): "
                         f"{result.stderr.strip() if result.stderr else result.stdout.strip()}")
                    log_event("curator.repin_failed", {
                        "skill": skill_name,
                        "exit_code": result.returncode,
                        "error": (result.stderr or result.stdout).strip()[:200]
                    })

    if archival_overrides:
        print(f"\n🚫 ARCHIVAL OVERRIDES ({len(archival_overrides)}):")
        for name, profiles in archival_overrides:
            print(f"  {name} — referenced by: {', '.join(profiles)}")
            log_event("curator.archival_blocked", {
                "skill": name,
                "profiles": profiles,
                "reason": "profile_referenced"
            })

    # ── Handle newly added skills ──
    added_raw = report.get("added", []) or []
    # Backward-compatible: added is now [{"name":..., "created_by":...}] or [str]
    added = [
        entry["name"] if isinstance(entry, dict) else entry
        for entry in added_raw
    ]
    classifications = {}
    if added:
        print(f"\n📦 NEW SKILLS DETECTED ({len(added)}):")
        for skill_name in added:
            lead, confidence = classify_skill(skill_name)
            classifications[skill_name] = (lead, confidence)
            if lead and confidence >= 80:
                ok, msg = add_skill_to_enabled(skill_name, lead)
                status = "auto-assigned" if ok else f"failed: {msg}"
                if ok:
                    ok2, msg2 = set_adoption_status(skill_name, "dynamic")
                    dyn = "✓" if ok2 else msg2
                else:
                    dyn = "skipped (enable failed)"
                print(f"  {skill_name} → {lead} (conf={confidence}%) [{status}] [dynamic={dyn}]")
                log_event("curator.skill_dynamic_assigned", {
                    "skill": skill_name,
                    "profile": lead,
                    "confidence": confidence,
                    "status": status
                })
            else:
                print(f"  {skill_name} → needs manual review (conf={confidence}%)")
                log_event("curator.skill_dynamic_unclassified", {
                    "skill": skill_name,
                    "confidence": confidence
                })

    # ── Summary ──
    print(f"\n✅ Curator governance hook complete")
    print(f"   Archival overrides: {len(archival_overrides)}")
    auto = sum(1 for s in (added or [])
               if classifications.get(s, (None, 0))[1] >= 80)
    pending = sum(1 for s in (added or [])
                  if classifications.get(s, (None, 0))[1] < 80)
    print(f"   New skills auto-assigned: {auto}")
    print(f"   New skills pending review: {pending}")


if __name__ == "__main__":
    if not acquire_lock():
        sys.exit(1)
    try:
        main()
    except Exception as e:
        print(f"[FATAL] Unhandled exception: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        release_lock()
