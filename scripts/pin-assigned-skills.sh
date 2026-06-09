#!/bin/bash
# pin-assigned-skills.sh — Ring-fence all Kensei-assigned skills via curator pin
# Extracts every skill from all profile configs (root + profiles/*/config.yaml)
# and pins them so the Hermes curator never archives without governance review.
#
# Idempotent — pinning an already-pinned skill is a no-op.
# Cron: daily 06:00, no_agent=true, delivers to #governance

set -euo pipefail

# ── Safety: require Bash 4+ for associative arrays ──
if [ -z "${BASH_VERSINFO:-}" ] || [ "${BASH_VERSINFO:-0}" -lt 4 ]; then
    echo "ERROR: Requires Bash 4+ for associative arrays" >&2
    exit 1
fi

# ── PID lockfile to prevent concurrent runs ──
LOCKFILE="$HOME/.hermes/.pin_assigned_skills.lock"
if [ -f "$LOCKFILE" ]; then
    OLD_PID=$(cat "$LOCKFILE" 2>/dev/null)
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "WARNING: Another pin instance is running (PID $OLD_PID). Exiting." >&2
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
echo $$ > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

BASE="$HOME/.hermes"
SKILL_NAME_RE='^[A-Za-z0-9._-]+$'

echo "=== Kensei Skill Pinning — $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
echo ""

# ── Helper: extract skill names from a config YAML via Python ──
# Prints one skill per line to stdout; errors to stderr (not mixed)
extract_skills() {
    local cfg_path="$1"
    local label="${2:-root}"
    python3 -c "
import yaml, json, sys
try:
    with open('$cfg_path') as f:
        c = yaml.safe_load(f) or {}
    sb = c.get('skills', {}) or {}
    for key in ['always_skills', 'enabled_skills']:
        val = sb.get(key, [])
        if isinstance(val, str):
            try: val = json.loads(val)
            except: val = []
        for s in (val or []):
            s = str(s).strip()
            if s and not s.startswith('/'):
                print(s)
except Exception as e:
    print(f'ERROR:{label}: {e}', file=sys.stderr)
" 2>/dev/null  # stderr kept separate, not merged
}

# ── Collect all skill names ──
declare -A ALL_SKILLS
TOTAL=0

# Root config
while IFS= read -r s; do
    [ -n "$s" ] || continue
    ALL_SKILLS["$s"]=1
    TOTAL=$((TOTAL + 1))
done < <(extract_skills "$BASE/config.yaml" "root")

# Profile configs
shopt -s nullglob
for PROFILE_DIR in "$BASE"/profiles/*/; do
    PROFILE=$(basename "$PROFILE_DIR")
    [[ "$PROFILE" == _* || "$PROFILE" == .* ]] && continue
    CFG="$PROFILE_DIR/config.yaml"
    [ -f "$CFG" ] || continue

    while IFS= read -r s; do
        [ -n "$s" ] || continue
        ALL_SKILLS["$s"]=1
        TOTAL=$((TOTAL + 1))
    done < <(extract_skills "$CFG" "$PROFILE")
done
shopt -u nullglob

UNIQUE=${#ALL_SKILLS[@]}
echo "Collected $UNIQUE unique skills ($TOTAL references)"
echo ""

# ── Pin each skill ──
PINNED=0
SKIPPED=0
FAILED=0

for SKILL in "${!ALL_SKILLS[@]}"; do
    # Validate skill name format
    if ! [[ "$SKILL" =~ $SKILL_NAME_RE ]]; then
        echo "  ⚠️  $SKILL — invalid characters, skipping"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    # Verify skill exists on disk
    SKILL_PATH=$(find "$BASE/skills" -path "*/${SKILL}/SKILL.md" \
        -not -path '*/_archived/*' 2>/dev/null | head -1)
    if [ -z "$SKILL_PATH" ]; then
        echo "  ⚠️  $SKILL — not found on disk (stale reference)"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    # Pin via hermes curator — check exit code, not output text
    if hermes curator pin "$SKILL" > /dev/null 2>&1; then
        PINNED=$((PINNED + 1))
        echo "  ✅ $SKILL"
    else
        FAILED=$((FAILED + 1))
        echo "  ❌ $SKILL — pin failed (exit code non-zero)"
    fi
done

echo ""
echo "=== Summary ==="
echo "Pinned:   $PINNED"
echo "Skipped:  $SKIPPED (stale or invalid)"
echo "Failed:   $FAILED"
echo "Total unique: $UNIQUE"
