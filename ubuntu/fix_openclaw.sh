#!/bin/bash
# fix_openclaw.sh — Fixes OpenClaw installs that used the legacy system service.
# Removes the manual openclaw.service, re-installs via the official installer,
# and enables linger so the user service starts at boot.
#
# Usage:
#   sudo bash fix_openclaw.sh
#   sudo bash fix_openclaw.sh <username>   # specify user explicitly

set -e

RESET=$'\033[0m'; BOLD=$'\033[1m'; RED=$'\033[0;31m'
GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; CYAN=$'\033[0;36m'

ok()   { echo -e "  ${GREEN}✓${RESET}  $1"; }
info() { echo -e "  ${CYAN}ℹ${RESET}  $1"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
die()  { echo -e "  ${RED}${BOLD}✗ Error:${RESET} $1"; exit 1; }
run_as_login_user() {
    local username="$1"
    local command="$2"
    if command -v runuser >/dev/null 2>&1; then
        runuser -l "$username" -c "$command"
    else
        su - "$username" -c "$command"
    fi
}
gateway_status() {
    local username="$1"
    run_as_login_user "$username" 'export XDG_RUNTIME_DIR=/run/user/$(id -u); systemctl --user is-active openclaw-gateway'
}

if [[ $EUID -ne 0 ]]; then
    die "This script must be run as root. Use: sudo bash fix_openclaw.sh"
fi

echo
echo -e "${BOLD}  OpenClaw Service Fix${RESET}"
echo -e "  ${CYAN}──────────────────────────────────────────${RESET}"
echo

# ── Determine target user ──────────────────────────────────────────────────────
if [[ -n "$1" ]]; then
    TARGET_USER="$1"
else
    # Find users in /home with UID >= 1000
    mapfile -t HOME_USERS < <(
        awk -F: '$3 >= 1000 && $6 ~ /^\/home/ {print $1}' /etc/passwd
    )
    if [[ ${#HOME_USERS[@]} -eq 0 ]]; then
        die "No users found in /home. Pass the username as an argument."
    elif [[ ${#HOME_USERS[@]} -eq 1 ]]; then
        TARGET_USER="${HOME_USERS[0]}"
        info "Target user: ${BOLD}${TARGET_USER}${RESET}"
    else
        echo -e "  Multiple users found: ${HOME_USERS[*]}"
        read -rp "  Enter username to fix OpenClaw for: " TARGET_USER
    fi
fi

id "$TARGET_USER" &>/dev/null || die "User '$TARGET_USER' does not exist."

echo

# ── Step 1: Remove legacy system service ──────────────────────────────────────
info "Checking for legacy system service..."
if systemctl list-unit-files openclaw.service 2>/dev/null | grep -q openclaw; then
    info "Stopping and removing openclaw.service..."
    systemctl stop openclaw 2>/dev/null || true
    systemctl disable openclaw 2>/dev/null || true
    rm -f /etc/systemd/system/openclaw.service
    systemctl daemon-reload
    ok "Legacy system service removed"
else
    ok "No legacy system service found"
fi

# ── Step 2: Kill any orphaned openclaw-gateway processes ──────────────────────
info "Cleaning up any stale gateway processes..."
pkill -u "$TARGET_USER" -f openclaw-gateway 2>/dev/null || true
sleep 1
ok "Stale processes cleared"

# ── Step 3: Ensure system deps are present (installer can't sudo without TTY) ──
info "Ensuring Node.js and installer dependencies are installed..."
if ! command -v node &>/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    ok "NodeSource repository configured"
else
    ok "Node.js already present ($(node --version))"
fi
apt-get install -y \
    git curl wget sudo \
    nodejs build-essential cmake make g++ python3 \
    ca-certificates
ok "Installer dependencies verified"

# ── Step 4: Re-install via official installer ─────────────────────────────────
info "Running official OpenClaw installer as ${TARGET_USER}..."
echo
curl -fsSL https://openclaw.ai/install.sh -o /tmp/openclaw_install.sh
chmod 755 /tmp/openclaw_install.sh
run_as_login_user "$TARGET_USER" \
    'export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; \
    for cmd in git curl sudo node npm bash; do \
        command -v "$cmd" >/dev/null || { echo "Missing dependency in user PATH: $cmd" >&2; exit 1; }; \
    done; \
    bash /tmp/openclaw_install.sh --no-onboard'
run_as_login_user "$TARGET_USER" \
    "export PATH=/home/$TARGET_USER/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; \
    openclaw gateway install"
rm -f /tmp/openclaw_install.sh
echo
ok "OpenClaw installed"

# ── Step 5: Enable linger ──────────────────────────────────────────────────────
info "Enabling linger for ${TARGET_USER} (service starts at boot)..."
loginctl enable-linger "$TARGET_USER"
ok "Linger enabled"
if gateway_status "$TARGET_USER" >/dev/null 2>&1; then
    ok "OpenClaw gateway service is active"
else
    warn "OpenClaw gateway service is installed but not active yet"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo
echo -e "  ${CYAN}──────────────────────────────────────────${RESET}"
echo -e "  ${GREEN}${BOLD}Fix complete!${RESET}"
echo
echo -e "  OpenClaw is now managed by its own user service."
echo -e "  To set up Discord (or any other channel), run as ${TARGET_USER}:"
echo
echo -e "    ${YELLOW}openclaw onboard${RESET}"
echo -e "    ${YELLOW}openclaw channels login --channel discord${RESET}"
echo
