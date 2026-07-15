#!/usr/bin/env python3
"""Backup retention manager — keeps 14 most recent verified daily archives.

Run after backup-health-check.py passes. Deletes older archives
only when the newest 14 are verified healthy.

Records every deletion in a local audit ledger.
"""
import os, sys, json
from datetime import datetime, timezone
from pathlib import Path

BACKUP_ROOT = Path(os.path.expanduser("~/backups/daily"))
RETENTION_COUNT = 14
LEDGER_PATH = BACKUP_ROOT / "retention-ledger.jsonl"

def _archive_stem(archive: Path) -> str:
    """Extract stem without .tar.gz: kensei-20260714-2240.tar.gz -> kensei-20260714-2240"""
    name = archive.name
    for suffix in [".tar.gz", ".tar"]:
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name

def _manifest_path(archive: Path) -> Path:
    """Manifest for archive: kensei-20260714-2240.tar.gz -> kensei-20260714-2240.manifest.json"""
    return BACKUP_ROOT / f"{_archive_stem(archive)}.manifest.json"

def get_archives() -> list[Path]:
    """Return all backup archives sorted newest first."""
    return sorted(BACKUP_ROOT.glob("kensei-*.tar.gz"), reverse=True)

def get_verified_stems() -> set[str]:
    """Return set of archive stems that have valid, parseable manifests."""
    valid = set()
    for mf in BACKUP_ROOT.glob("kensei-*.manifest.json"):
        try:
            with open(mf) as f:
                json.load(f)
            # Strip .manifest.json to get the archive stem
            stem = mf.name.replace(".manifest.json", "")
            valid.add(stem)
        except json.JSONDecodeError:
            pass
    return valid

def log_deletion(archive: Path, reason: str, size_bytes: int):
    """Record deletion in the audit ledger. Size captured BEFORE deletion."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "archive": archive.name,
        "size_bytes": size_bytes,
        "reason": reason,
    }
    with open(LEDGER_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")

def main():
    archives = get_archives()
    verified_stems = get_verified_stems()
    
    if len(archives) <= RETENTION_COUNT:
        return
    
    keep = archives[:RETENTION_COUNT]
    delete = archives[RETENTION_COUNT:]
    
    # Safety: never delete the last verified archive
    # Use _archive_stem for consistent comparison with verified_stems
    verified_archives = [a for a in archives if _archive_stem(a) in verified_stems]
    if verified_archives:
        last_verified_stem = _archive_stem(verified_archives[0])
        keep_stems = {_archive_stem(a) for a in keep}
        if last_verified_stem not in keep_stems:
            print(f"ALERT: Would delete last verified archive ({verified_archives[0].name}). Aborting.")
            sys.exit(1)
    
    deleted = 0
    for archive in delete:
        try:
            # Capture size BEFORE deletion
            size_bytes = archive.stat().st_size if archive.is_file() else 0
            
            manifest = _manifest_path(archive)
            archive.unlink()
            if manifest.is_file():
                manifest.unlink()
            
            log_deletion(archive, "retention_policy_14_daily", size_bytes)
            deleted += 1
        except OSError as e:
            print(f"ALERT: Failed to delete {archive.name}: {e}")
            sys.exit(1)
    
    if deleted > 0:
        print(f"Retention: removed {deleted} old archive(s), {len(keep)} retained")

if __name__ == "__main__":
    main()
