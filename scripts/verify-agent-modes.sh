#!/usr/bin/env bash
# ── KENSEI CUSTOM MODE VERIFICATION ──────────────────────────────────
# Run after any pipx install --force ., git pull upstream, or git merge
# to verify the custom mode system survived.  Exit code 0 = all good.
#
# If this fails, follow /home/kensei/.hermes/skills/devops/agent-modes/SKILL.md
# and /home/kensei/.hermes/skills/governance/SOUL.md "KENSEI CUSTOM MODE — RESTORE"
# ──────────────────────────────────────────────────────────────────────

set -euo pipefail
FAIL=0
REPO="/home/kensei/repos/KenseiAgent"
HUMAN_GATE=1  # Set to 0 after human approves a mode change

# --- TUI TypeScript checks ---
check_ts() {
    local file="$1" pattern="$2" label="$3"
    if grep -q "$pattern" "$REPO/$file" 2>/dev/null; then
        echo "  ✓ $label"
    else
        echo "  ✗ MISSING: $label ($file should contain '$pattern')"
        FAIL=1
    fi
}

echo "── KENSEI agent-mode verification ──"

# 1) TypeScript: interfaces.ts
check_ts "ui-tui/src/app/interfaces.ts" "AGENT_MODES" "AgentMode type + AGENT_MODES array"
check_ts "ui-tui/src/app/interfaces.ts" "agentMode: AgentMode" "UiState.agentMode field"

# 2) TypeScript: uiStore.ts
check_ts "ui-tui/src/app/uiStore.ts" "agentMode: 'auto'" "buildUiState default agentMode='auto'"

# 3) TypeScript: useInputHandlers.ts
check_ts "ui-tui/src/app/useInputHandlers.ts" "KENSEI CUSTOM: shift-tab cycles agent mode" "Shift+Tab mode cycling handler"
check_ts "ui-tui/src/app/useInputHandlers.ts" "config\\.set.*mode" "Shift+Tab sets gateway mode"

# 4) TypeScript: appLayout.tsx
check_ts "ui-tui/src/components/appLayout.tsx" "MODE_BADGE" "Mode badge emoji map"
check_ts "ui-tui/src/components/appLayout.tsx" "displayPrompt" "displayPrompt used in PromptPrefix"

# 5) TypeScript: session.ts (/mode slash command)
check_ts "ui-tui/src/app/slash/commands/session.ts" "KENSEI CUSTOM: agent mode slash command" "/mode slash command"

# 6) Python: tui_gateway/server.py
check_ts "tui_gateway/server.py" "_MODE_PROMPTS" "_MODE_PROMPTS dict in gateway config.set handler"
check_ts "tui_gateway/server.py" "_mode_prompt" "_mode_prompt() function"
check_ts "tui_gateway/server.py" "if key == \"mode\"" "gateway config.set key=mode handler"

# 7) Python: cli.py
check_ts "cli.py" "KENSEI CUSTOM: /mode command" "CLI _handle_mode_command method"

# 8) hermes_cli/commands.py
check_ts "hermes_cli/commands.py" "gods_plan" "CommandDef for /mode with gods_plan subcommand"

echo ""
if [ "$FAIL" -eq 0 ]; then
    echo "  All mode components verified ✓"
else
    echo "  $FAIL component(s) MISSING — mode system is broken. Restore from skill doc."
fi
exit "$FAIL"
