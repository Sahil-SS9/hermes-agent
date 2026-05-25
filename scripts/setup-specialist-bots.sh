#!/usr/bin/env bash
# ============================================================================
# KENSEI Specialist Bot Setup
# Creates 6 systemd gateway services: misa-misa, remii, wesker, gojo, octacon, ceecee
# Each runs in its own profile's HERMES_HOME with full context isolation.
#
# USAGE:
#   1. Create 6 Discord apps at https://discord.com/developers/applications
#   2. For each: Bot tab -> Reset Token -> copy token
#   3. Run: echo "TOKEN" > /tmp/setup-tokens/misa-misa
#           echo "TOKEN" > /tmp/setup-tokens/remii
#           ... etc for all 6
#   4. Run: bash /home/kensei/.hermes/scripts/setup-specialist-bots.sh
#
# SAFETY:
#   - Tokens are read from /tmp/setup-tokens/ and wiped after use
#   - Token values never appear in logs (env file only)
#   - Backs up existing config before modifying
# ============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== KENSEI Specialist Bot Setup ===${NC}"

# ─── Configuration ───────────────────────────────────────────────────────────
HERMES_VENV=/home/kensei/.hermes/hermes-agent/venv
HERMES_ROOT=/home/kensei/.hermes
PROFILES_DIR=$HERMES_ROOT/profiles
TOKEN_DIR=/tmp/setup-tokens
SYSTEMD_DIR=/etc/systemd/system
SAHIL_USER_ID=797682085224513547

# ─── Bot definitions ─────────────────────────────────────────────────────────
# name        profile_dir    discord_home_channel              description
declare -A BOTS
BOTS=(
    [misa-misa]="misa-misa||Voice intake, STT/TTS, spoken commands"
    [remii]="remii||Research, signals, market scanning, deep dives"
    [wesker]="wesker||Ops, security, infra, gateway health"
    [gojo]="gojo||Admin, mailbox, calendar, job-hunt"
    [octacon]="octacon||Coding, build, debugging, PRs"
    [ceecee]="ceecee||Content drafting, brand, social scheduling"
)

# ─── Pre-flight checks ──────────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}Must run as root (sudo). Needed for systemd service creation.${NC}"
    exit 1
fi

if [ ! -d "$TOKEN_DIR" ]; then
    echo -e "${RED}Token directory $TOKEN_DIR not found.${NC}"
    echo "Create it and drop one token file per bot:"
    for bot in "${!BOTS[@]}"; do
        echo "  echo 'TOKEN_HERE' > $TOKEN_DIR/$bot"
    done
    exit 1
fi

for bot in "${!BOTS[@]}"; do
    if [ ! -f "$TOKEN_DIR/$bot" ]; then
        echo -e "${RED}Missing token file: $TOKEN_DIR/$bot${NC}"
        exit 1
    fi
    TOKEN=$(cat "$TOKEN_DIR/$bot" | tr -d '\n\r ')
    if [ -z "$TOKEN" ] || [ ${#TOKEN} -lt 50 ]; then
        echo -e "${RED}Token for $bot looks invalid (too short)${NC}"
        exit 1
    fi
done

echo -e "${GREEN}All 6 tokens found and look valid.${NC}"

# ─── Create backups ──────────────────────────────────────────────────────────
BACKUP_DIR=/home/kensei/backups/specialist-bots-$(date +%Y%m%d-%H%M%S)
mkdir -p "$BACKUP_DIR"
echo "Backups: $BACKUP_DIR"

# Backup profile configs before modifying
for bot in "${!BOTS[@]}"; do
    IFS='|' read -r profile_dir home_channel desc <<< "${BOTS[$bot]}"
    PROFILE=$PROFILES_DIR/$profile_dir
    if [ -f "$PROFILE/config.yaml" ]; then
        cp "$PROFILE/config.yaml" "$BACKUP_DIR/${profile_dir}-config.yaml.bak"
    fi
    if [ -f "$PROFILE/.env" ]; then
        cp "$PROFILE/.env" "$BACKUP_DIR/${profile_dir}-env.bak"
    fi
done

# Backup Kensei main config
cp "$HERMES_ROOT/config.yaml" "$BACKUP_DIR/kensei-config.yaml.bak" 2>/dev/null || true

# ─── Create .env files for each specialist profile ───────────────────────────
echo ""
echo -e "${YELLOW}Creating .env files...${NC}"

for bot in "${!BOTS[@]}"; do
    IFS='|' read -r profile_dir home_channel desc <<< "${BOTS[$bot]}"
    PROFILE=$PROFILES_DIR/$profile_dir
    TOKEN=$(cat "$TOKEN_DIR/$bot" | tr -d '\n\r ')

    mkdir -p "$PROFILE"

    cat > "$PROFILE/.env" << ENVEOF
# Specialist bot: $bot ($desc)
# Auto-generated $(date)
DISCORD_BOT_TOKEN=$TOKEN
DISCORD_ALLOWED_USERS=$SAHIL_USER_ID
DISCORD_HOME_CHANNEL=$home_channel
ENVEOF

    chmod 600 "$PROFILE/.env"
    chown kensei:kensei "$PROFILE/.env"
    echo "  $bot -> $PROFILE/.env"
done

# ─── Strip MCP servers from specialist profiles ──────────────────────────────
# Specialist gateways should NOT spawn MCP processes.
# MCP servers live only on Kensei's main gateway.
echo ""
echo -e "${YELLOW}Removing MCP servers from specialist profile configs...${NC}"

for bot in "${!BOTS[@]}"; do
    IFS='|' read -r profile_dir home_channel desc <<< "${BOTS[$bot]}"
    PROFILE=$PROFILES_DIR/$profile_dir
    CONFIG=$PROFILE/config.yaml

    if [ -f "$CONFIG" ]; then
        # Use Python to strip mcp_servers key
        sudo -u kensei "$HERMES_VENV/bin/python3" -c "
import yaml, pathlib
p = pathlib.Path('$CONFIG')
cfg = yaml.safe_load(p.read_text()) or {}
if 'mcp_servers' in cfg:
    del cfg['mcp_servers']
    p.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    print('  $bot: removed mcp_servers')
else:
    print('  $bot: no mcp_servers to remove')
"
    fi
done

# ─── Create systemd service files ────────────────────────────────────────────
echo ""
echo -e "${YELLOW}Creating systemd services...${NC}"

for bot in "${!BOTS[@]}"; do
    IFS='|' read -r profile_dir home_channel desc <<< "${BOTS[$bot]}"
    PROFILE=$PROFILES_DIR/$profile_dir
    SERVICE="hermes-gateway-$bot"

    cat > "$SYSTEMD_DIR/$SERVICE.service" << SERVICEEOF
[Unit]
Description=Hermes Gateway – $bot ($desc)
After=network-online.target hermes-gateway.service
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=kensei
Group=kensei
Environment="HOME=/home/kensei"
Environment="USER=kensei"
Environment="LOGNAME=kensei"
Environment="HERMES_HOME=$PROFILE"
Environment="PATH=$HERMES_VENV/bin:/home/kensei/.hermes/hermes-agent/node_modules/.bin:/home/kensei/.hermes/node/bin:/home/kensei/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="VIRTUAL_ENV=$HERMES_VENV"
ExecStart=$HERMES_VENV/bin/python -m hermes_cli.main gateway run --replace
WorkingDirectory=$HERMES_ROOT/hermes-agent
Restart=always
RestartSec=10
RestartMaxDelaySec=120
RestartSteps=5
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=90
StandardOutput=journal
StandardError=journal

# Memory: ~150-250MB per specialist gateway
MemoryMax=1G
MemoryHigh=800M

[Install]
WantedBy=multi-user.target
SERVICEEOF

    echo "  $SERVICE.service created"
done

# ─── Disable cron ticker on specialist profiles ──────────────────────────────
# Cron jobs live only on Kensei's main gateway.
# Specialist profiles may have existing cron jobs — disable them.
echo ""
echo -e "${YELLOW}Disabling profile-local cron jobs...${NC}"

for bot in "${!BOTS[@]}"; do
    IFS='|' read -r profile_dir home_channel desc <<< "${BOTS[$bot]}"
    PROFILE=$PROFILES_DIR/$profile_dir
    CRONFILE=$PROFILE/cron/jobs.json

    if [ -f "$CRONFILE" ]; then
        sudo -u kensei "$HERMES_VENV/bin/python3" -c "
import json, pathlib
p = pathlib.Path('$CRONFILE')
data = json.loads(p.read_text())
disabled = 0
for j in data.get('jobs', []):
    if j.get('enabled'):
        j['enabled'] = False
        disabled += 1
p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
print(f'  $bot: disabled {disabled} cron jobs')
"
    else
        echo "  $bot: no cron jobs file"
    fi
done

# ─── Reload systemd ──────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}Reloading systemd...${NC}"
systemctl daemon-reload

# ─── Enable and start services ───────────────────────────────────────────────
echo ""
echo -e "${GREEN}Starting specialist gateways...${NC}"

for bot in "${!BOTS[@]}"; do
    SERVICE="hermes-gateway-$bot"
    echo "  $SERVICE..."
    systemctl enable "$SERVICE" 2>&1 | tail -1
    systemctl start "$SERVICE" 2>&1 | tail -1
done

# ─── Wait and verify ─────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}Waiting 5s for gateways to initialise...${NC}"
sleep 5

echo ""
echo -e "${GREEN}=== Status ===${NC}"
echo ""

TOTAL_RSS=0
for bot in "${!BOTS[@]}"; do
    SERVICE="hermes-gateway-$bot"
    ACTIVE=$(systemctl is-active "$SERVICE" 2>/dev/null || echo "failed")
    if [ "$ACTIVE" = "active" ]; then
        PID=$(systemctl show -p MainPID --value "$SERVICE" 2>/dev/null || echo 0)
        RSS=$(awk '/^VmRSS:/ {print $2}' /proc/$PID/status 2>/dev/null || echo 0)
        TOTAL_RSS=$((TOTAL_RSS + RSS))
        STATUS="${GREEN}active${NC}"
    else
        STATUS="${RED}$ACTIVE${NC}"
        PID="-"
        RSS="-"
    fi
    printf "  %-12s  status=%-8s  pid=%-8s  rss=%s KB\n" "$bot" "$ACTIVE" "$PID" "$RSS"
done

# Also check Kensei main
MAIN_ACTIVE=$(systemctl is-active hermes-gateway 2>/dev/null || echo "failed")
MAIN_PID=$(systemctl show -p MainPID --value hermes-gateway 2>/dev/null || echo 0)
MAIN_RSS=$(awk '/^VmRSS:/ {print $2}' /proc/$MAIN_PID/status 2>/dev/null || echo 0)
TOTAL_RSS=$((TOTAL_RSS + MAIN_RSS))
printf "  %-12s  status=%-8s  pid=%-8s  rss=%s KB\n" "kensei" "$MAIN_ACTIVE" "$MAIN_PID" "$MAIN_RSS"

TOTAL_MB=$((TOTAL_RSS / 1024))
echo ""
echo -e "Total RSS across all gateways: ~${GREEN}${TOTAL_MB} MB${NC}"

# ─── Wipe token files ────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}Wiping token directory...${NC}"
rm -rf "$TOKEN_DIR"
echo "  $TOKEN_DIR removed"

# ─── Next steps ──────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}=== Next Steps ===${NC}"
echo ""
echo "1. Check Discord — each bot should appear online with its persona name."
echo "2. Verify each gateway log for errors:"
for bot in "${!BOTS[@]}"; do
    echo "   journalctl -u hermes-gateway-$bot -n 20 --no-pager"
done
echo ""
echo "3. Channel setup: assign bots to the right channels per the architecture doc."
echo "4. Test co-working: Remii + Wesker in #research-ops."
echo "5. Test voice: Misa-Misa auto-join in 🔊 Misa-Misa Intake."
echo ""
echo "Backup: $BACKUP_DIR"
echo ""
echo -e "${YELLOW}To rollback:${NC}"
echo "  sudo systemctl stop hermes-gateway-{misa-misa,remii,wesker,gojo,octacon,ceecee}"
echo "  sudo systemctl disable hermes-gateway-{misa-misa,remii,wesker,gojo,octacon,ceecee}"
echo "  sudo rm /etc/systemd/system/hermes-gateway-{misa-misa,remii,wesker,gojo,octacon,ceecee}.service"
echo "  sudo systemctl daemon-reload"
echo "  # Restore profile configs from $BACKUP_DIR"
