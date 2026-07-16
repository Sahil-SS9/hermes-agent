#!/usr/bin/env python3
"""G3 regression tests for scripts/tier-enforcement-proof.py.

The proof script must DERIVE profile tiers from on-disk config.yaml files
and validate Tier-3 identity/count against the governing registry — not
from a hard-coded source list that can go stale (the G3 defect: the script
hard-coded the 9 real Tier-3 profiles as Tier-2 and falsely reported
Tier-3=0).

These tests use temporary fixture roots (profiles dir + registry fixture)
injected via the script's CLI/API seams. No test reads or mutates the real
~/.hermes.
"""
from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "tier-enforcement-proof.py"


# ── helpers ─────────────────────────────────────────────────────────────────


def _load_script(monkeypatch, profiles_dir: Path, registry: Path):
    """Import the proof script with injected paths via env vars.

    The script must support HERMES_PROOF_PROFILES_DIR and
    HERMES_PROOF_REGISTRY override env vars (test seam). These override
    the default ~/.hermes/... paths only when set.
    """
    monkeypatch.setenv("HERMES_PROOF_PROFILES_DIR", str(profiles_dir))
    monkeypatch.setenv("HERMES_PROOF_REGISTRY", str(registry))
    spec = importlib.util.spec_from_file_location(
        "tier_enforcement_proof_under_test", str(SCRIPT)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_profile(profiles_root: Path, name: str, tier: int) -> None:
    """Create a minimal profile directory + config.yaml with a tier field."""
    d = profiles_root / name
    d.mkdir(parents=True, exist_ok=True)
    cfg = {"tier": tier, "name": name, "model": {"default": "test/m"}}
    (d / "config.yaml").write_text(yaml.safe_dump(cfg))


def _make_registry(
    tmp_path: Path,
    tier1: list[str],
    tier2: list[str],
    tier3: list[str],
) -> Path:
    """Write a minimal registry markdown fixture the script can parse.

    Format mirrors the real registry: markdown tables under tier headers.
    The parser extracts profile names from the first column of each tier
    section.
    """
    lines = ["# Profile Tier Registry", ""]

    lines.append(f"## Tier 1 — Active Gateway Leads ({len(tier1)})")
    lines.append("")
    lines.append("| Profile | Lead domain | Systemd unit |")
    lines.append("|---|---|---|")
    for name in tier1:
        lines.append(f"| {name} | domain | unit |")
    lines.append("")

    lines.append(f"## Tier 2 — Standing Delegation Targets ({len(tier2)})")
    lines.append("")
    lines.append("| Profile | Sub |")
    lines.append("|---|---|")
    for name in tier2:
        lines.append(f"| {name} | sub |")
    lines.append("")

    lines.append(f"## Tier 3 — Dormant / Specialized ({len(tier3)})")
    lines.append("")
    lines.append("| Profile | Reason |")
    lines.append("|---|---|")
    for name in tier3:
        lines.append(f"| {name} | G3: keep disabled |")
    lines.append("")

    reg = tmp_path / "registry.md"
    reg.write_text("\n".join(lines))
    return reg


# ── fixtures ────────────────────────────────────────────────────────────────


T3_NAMES = [
    "denji-monitor",
    "dezzy-image-prompt",
    "dezzy-ux-architect",
    "light-archivist",
    "octacon-architect",
    "octacon-frontend",
    "octacon-techwriter",
    "remii-deep",
    "wesker-backup",
]

T1_NAMES = [
    "kensei", "misa-misa", "remii", "wesker", "gojo", "octacon",
    "ceecee", "mrhermagi", "quan", "denji", "kensei-review", "light",
    "dezzy", "sirvir",
]

# A representative subset of Tier-2 for fixture (we don't need all 39)
T2_NAMES = [
    "ceecee-writer", "ceecee-social", "denji-ledger", "gojo-admin",
    "octacon-backend", "orchestrator", "wesker-ops", "moss",
]


@pytest.fixture
def full_fixture(tmp_path, monkeypatch):
    """Build a full 13/39/9-like fixture mirroring real config."""
    profiles_root = tmp_path / "profiles"
    profiles_root.mkdir()

    # kensei is the default — no config.yaml on disk (expected)
    for n in T1_NAMES:
        if n == "kensei":
            # kensei has no config.yaml by convention
            (profiles_root / n).mkdir(exist_ok=True)
        else:
            _make_profile(profiles_root, n, 1)

    for n in T2_NAMES:
        _make_profile(profiles_root, n, 2)

    for n in T3_NAMES:
        _make_profile(profiles_root, n, 3)

    reg = _make_registry(tmp_path, T1_NAMES, T2_NAMES, T3_NAMES)
    mod = _load_script(monkeypatch, profiles_root, reg)
    return mod, profiles_root, reg


# ── tests ───────────────────────────────────────────────────────────────────


class TestDerivesTiersFromConfig:
    """G3 core: tiers must come from config.yaml, not a hard-coded dict."""

    def test_tier3_detected_from_config(self, full_fixture):
        """9 Tier-3 profiles with tier:3 in config.yaml must be detected."""
        mod, _, _ = full_fixture
        tiers = mod.derive_profile_tiers()
        t3 = {n for n, t in tiers.items() if t == 3}
        assert t3 == set(T3_NAMES), f"Expected 9 Tier-3, got {t3}"

    def test_tier3_count_is_nine(self, full_fixture):
        """Tier-3 count must be 9, not 0."""
        mod, _, _ = full_fixture
        tiers = mod.derive_profile_tiers()
        t3_count = sum(1 for t in tiers.values() if t == 3)
        assert t3_count == 9

    def test_hardcoded_zero_tier3_cannot_occur(self, full_fixture):
        """The bug: a hard-coded roster reporting Tier-3=0 must never happen.

        With 9 profiles having tier:3 in config, derive_profile_tiers() must
        return non-zero Tier-3 count. If the script still used a stale
        CANONICAL dict with no Tier-3 entries, this would fail.
        """
        mod, _, _ = full_fixture
        tiers = mod.derive_profile_tiers()
        assert any(t == 3 for t in tiers.values()), (
            "Tier-3=0 is the G3 defect — tiers must be derived from config"
        )

    def test_tier1_count(self, full_fixture):
        """13 Tier-1 configs on disk (kensei has no config, so 13 with tier
        field, but derive counts only those with config.yaml)."""
        mod, _, _ = full_fixture
        tiers = mod.derive_profile_tiers()
        t1 = {n for n, t in tiers.items() if t == 1}
        # kensei has no config.yaml so won't appear; the other 13 do
        assert len(t1) == 13
        assert "kensei" not in t1  # no config.yaml

    def test_tier2_count(self, full_fixture):
        """All fixture Tier-2 profiles detected."""
        mod, _, _ = full_fixture
        tiers = mod.derive_profile_tiers()
        t2 = {n for n, t in tiers.items() if t == 2}
        assert t2 == set(T2_NAMES)


class TestRegistryValidation:
    """Tier-3 identity must be validated against the governing registry."""

    def test_matching_registry_passes(self, full_fixture):
        """When config tiers match registry tiers exactly, proof passes."""
        mod, _, _ = full_fixture
        result = mod.run_proof()
        assert result.exit_code == 0
        assert "Tier 3: 9" in result.stdout

    def test_registry_mismatch_fails(self, tmp_path, monkeypatch):
        """Registry lists a Tier-3 profile not in config → clear failure."""
        profiles_root = tmp_path / "profiles"
        profiles_root.mkdir()
        for n in T1_NAMES:
            if n != "kensei":
                _make_profile(profiles_root, n, 1)
            else:
                (profiles_root / n).mkdir(exist_ok=True)
        for n in T2_NAMES:
            _make_profile(profiles_root, n, 2)
        for n in T3_NAMES:
            _make_profile(profiles_root, n, 3)

        # Registry claims an extra Tier-3 not in config
        bad_t3 = T3_NAMES + ["nonexistent-profile"]
        reg = _make_registry(tmp_path, T1_NAMES, T2_NAMES, bad_t3)
        mod = _load_script(monkeypatch, profiles_root, reg)

        result = mod.run_proof()
        assert result.exit_code != 0
        assert "mismatch" in result.stdout.lower() or "error" in result.stdout.lower()

    def test_config_tier3_not_in_registry_fails(self, tmp_path, monkeypatch):
        """Config has a Tier-3 profile not in registry → clear failure."""
        profiles_root = tmp_path / "profiles"
        profiles_root.mkdir()
        for n in T1_NAMES:
            if n != "kensei":
                _make_profile(profiles_root, n, 1)
            else:
                (profiles_root / n).mkdir(exist_ok=True)
        for n in T2_NAMES:
            _make_profile(profiles_root, n, 2)
        for n in T3_NAMES:
            _make_profile(profiles_root, n, 3)
        # Add a profile with tier:3 in config but NOT in registry
        _make_profile(profiles_root, "rogue-tier3", 3)

        reg = _make_registry(tmp_path, T1_NAMES, T2_NAMES, T3_NAMES)
        mod = _load_script(monkeypatch, profiles_root, reg)

        result = mod.run_proof()
        assert result.exit_code != 0

    def test_tier3_identity_matches_registry(self, full_fixture):
        """The set of Tier-3 profiles from config must exactly equal the
        Tier-3 set in the registry."""
        mod, _, _ = full_fixture
        config_tiers = mod.derive_profile_tiers()
        config_t3 = {n for n, t in config_tiers.items() if t == 3}
        registry_t3 = mod.parse_registry_t3()
        assert config_t3 == registry_t3


class TestSafetyPolicyPreserved:
    """Tier-3 must remain non-delegatable; script only proves/enforces."""

    def test_tier3_marked_blocked(self, full_fixture):
        """Tier-3 profiles must be reported as BLOCKED in output."""
        mod, _, _ = full_fixture
        result = mod.run_proof()
        assert result.exit_code == 0
        # Each Tier-3 profile should be listed as BLOCKED
        for name in T3_NAMES:
            assert name in result.stdout
        assert "BLOCKED" in result.stdout

    def test_script_does_not_modify_profiles(self, full_fixture):
        """Script must not create/activate/modify any profile config."""
        mod, profiles_root, _ = full_fixture
        # Snapshot all config.yaml contents
        snapshots = {}
        for cfg in profiles_root.rglob("config.yaml"):
            snapshots[cfg] = cfg.read_text()

        mod.run_proof()

        for cfg, original in snapshots.items():
            assert cfg.read_text() == original, f"{cfg} was modified"


class TestDeployedDefaults:
    """Script must work with default real paths when no env vars set."""

    def test_env_override_seam_exists(self, tmp_path, monkeypatch):
        """The script must support HERMES_PROOF_PROFILES_DIR and
        HERMES_PROOF_REGISTRY env vars for test injection."""
        profiles_root = tmp_path / "profiles"
        profiles_root.mkdir()
        _make_profile(profiles_root, "test-t1", 1)
        reg = _make_registry(tmp_path, ["test-t1"], [], [])
        mod = _load_script(monkeypatch, profiles_root, reg)
        tiers = mod.derive_profile_tiers()
        assert "test-t1" in tiers
        assert tiers["test-t1"] == 1
