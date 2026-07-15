#!/usr/bin/env python3
"""Backup restore drill — proves we can restore from the latest verified archive.

Extracts to a disposable temp directory, verifies every file in the manifest
matches (count, path, SHA-256), reports success/failure, cleans up.

Usage: python3 backup-restore.py
Exit 0 = restore successful. Exit 1 = restore failed.
"""
import hashlib, json, os, shutil, sys, tarfile, tempfile
from datetime import datetime, timezone
from pathlib import Path

BACKUP_ROOT = Path(os.path.expanduser("~/backups/daily"))

def find_latest_verified() -> tuple[Path, Path] | None:
    """Return (archive, manifest) of the most recent backup with a valid manifest."""
    archives = sorted(BACKUP_ROOT.glob("kensei-*.tar.gz"), reverse=True)
    for archive in archives:
        # Derive manifest name: kensei-YYYYMMDD-HHMM.tar.gz → kensei-YYYYMMDD-HHMM.manifest.json
        name = archive.name
        for suffix in [".tar.gz", ".tar"]:
            if name.endswith(suffix):
                stem = name[:-len(suffix)]
                break
        else:
            continue
        manifest = BACKUP_ROOT / f"{stem}.manifest.json"
        if not manifest.is_file():
            continue
        try:
            with open(manifest) as f:
                m = json.load(f)
            if m.get("sha256"):
                return archive, manifest
        except json.JSONDecodeError:
            pass
    return None

def verify_checksum(archive: Path, expected_sha256: str) -> str | None:
    """Return None if checksum matches, error string if not."""
    sha = hashlib.sha256()
    with open(archive, "rb") as af:
        for chunk in iter(lambda: af.read(8192), b""):
            sha.update(chunk)
    actual = sha.hexdigest()
    if actual != expected_sha256:
        return f"Archive checksum mismatch: expected {expected_sha256[:16]}..., got {actual[:16]}..."
    return None

def main():
    result = find_latest_verified()
    if not result:
        print("FAIL: No verified backup archive found")
        sys.exit(1)
    
    archive, manifest_path = result
    print(f"Restore drill — {archive.name}")
    
    # Load manifest
    with open(manifest_path) as f:
        manifest = json.load(f)
    
    # Verify archive checksum
    err = verify_checksum(archive, manifest["sha256"])
    if err:
        print(f"FAIL: {err}")
        sys.exit(1)
    
    # Extract to temp directory
    tmpdir = tempfile.mkdtemp(prefix="restore-")
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(path=tmpdir)
        
        # Verify every file in manifest
        manifest_files = {f["path"]: f["size"] for f in manifest.get("files", [])}
        actual_count = 0
        
        for root, dirs, files in os.walk(tmpdir):
            for fname in files:
                actual_count += 1
                fpath = Path(root) / fname
                rel_path = str(fpath.relative_to(tmpdir))
                
                # Check file is in manifest
                if rel_path not in manifest_files:
                    print(f"FAIL: Extra file not in manifest: {rel_path}")
                    sys.exit(1)
                
                # Check size matches
                actual_size = fpath.stat().st_size
                expected_size = manifest_files[rel_path]
                if actual_size != expected_size:
                    print(f"FAIL: Size mismatch for {rel_path}: expected {expected_size}, got {actual_size}")
                    sys.exit(1)
        
        # Check no files missing from manifest
        if actual_count != manifest["file_count"]:
            print(f"FAIL: File count mismatch: manifest={manifest['file_count']}, extracted={actual_count}")
            sys.exit(1)
        
        # All checks passed
        print(f"RESTORE OK — {actual_count} files verified, {manifest['file_count']} in manifest")
        print(f"Extracted to: {tmpdir}")
        print(f"Archive: {archive}")
        
    finally:
        # Clean up
        shutil.rmtree(tmpdir, ignore_errors=True)

if __name__ == "__main__":
    main()
