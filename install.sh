#!/bin/bash
# SecureClaw Setup Installer
# Supports both VPS/remote-server installs and local Ubuntu desktop installs.

set -e

# Branch is passed as $1 (e.g. "dev"). Defaults to "main".
BRANCH="${1:-main}"
if [[ "$BRANCH" != "main" && "$BRANCH" != "dev" ]]; then
    BRANCH="main"
fi

# ── Colors ────────────────────────────────────────────────────────────────────
RESET=$'\033[0m'
BOLD=$'\033[1m'
DIM=$'\033[2m'
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[0;33m'
BLUE=$'\033[0;34m'
CYAN=$'\033[0;36m'
WHITE=$'\033[1;37m'

# ── Helpers ───────────────────────────────────────────────────────────────────
print_banner() {
    clear
    echo
    echo -e "${BLUE}${BOLD}  ╔══════════════════════════════════════════════════════════════╗${RESET}"
    echo -e "${BLUE}${BOLD}  ║                                                              ║${RESET}"
    echo -e "${BLUE}${BOLD}  ║           🦞  SecureClaw Setup Installer                     ║${RESET}"
    echo -e "${BLUE}${BOLD}  ║           Secure Remote Desktop Environment                 ║${RESET}"
    echo -e "${BLUE}${BOLD}  ║                          By: Belew Consulting LLC           ║${RESET}"
    echo -e "${BLUE}${BOLD}  ║                                                              ║${RESET}"
    echo -e "${BLUE}${BOLD}  ╚══════════════════════════════════════════════════════════════╝${RESET}"
    echo
    echo -e "  ${YELLOW}${BOLD}  ⚠  WARNING${RESET}"
    echo -e "  ${YELLOW}  This script modifies firewall policies and system configuration.${RESET}"
    echo -e "  ${YELLOW}  Incorrect use on a system you depend on could lock you out or${RESET}"
    echo -e "  ${YELLOW}  require a full reinstall. By continuing, you accept all responsibility${RESET}"
    echo -e "  ${YELLOW}  for any data loss or damages. Proceed only if you know what you are doing.${RESET}"
    echo
}

print_divider() {
    echo -e "${DIM}  ──────────────────────────────────────────────────────────────${RESET}"
}

print_step() {
    local num=$1
    local total=$2
    local msg=$3
    printf "  ${CYAN}${BOLD}[%s/%s]${RESET}  %s" "$num" "$total" "$msg"
}

print_ok() {
    echo -e "  ${GREEN}${BOLD}✓ Done${RESET}"
}

print_info() {
    echo -e "  ${WHITE}ℹ${RESET}  $1"
}

print_warn() {
    echo -e "  ${YELLOW}⚠${RESET}  $1"
}

print_error() {
    echo -e "  ${RED}${BOLD}✗ Error:${RESET} $1"
}

# ── Checks ────────────────────────────────────────────────────────────────────
check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root."
        echo
        echo -e "  Please run:  ${YELLOW}sudo bash install.sh${RESET}"
        echo
        exit 1
    fi
}

check_ubuntu() {
    if ! command -v apt &> /dev/null; then
        print_error "This installer only supports Ubuntu/Debian systems."
        exit 1
    fi
}

# ── Mode detection ────────────────────────────────────────────────────────────
# Sets SETUP_MODE="vps" or "local".
# Auto-detects via environment / filesystem, then confirms with the user.
detect_mode() {
    SETUP_MODE="vps"  # safe default

    # SSH_CLIENT / SSH_CONNECTION may survive sudo depending on sudoers config
    if [[ -n "${SSH_CLIENT:-}" || -n "${SSH_CONNECTION:-}" ]]; then
        SETUP_MODE="vps"
    elif [[ -n "${XRDP_SESSION:-}" ]]; then
        # Already inside an xrdp session — treat as VPS continuation
        SETUP_MODE="vps"
    else
        # Check for an active graphical session on the physical machine.
        # /tmp/.X11-unix contains a socket per running X server.
        # Wayland compositors create sockets under /run/user/<uid>/wayland-0.
        # Both are readable as root without needing env vars stripped by sudo.
        if [[ -d /tmp/.X11-unix ]] && [[ -n "$(ls /tmp/.X11-unix 2>/dev/null)" ]]; then
            SETUP_MODE="local"
        elif ls /run/user/*/wayland-0 2>/dev/null | head -1 | grep -q .; then
            SETUP_MODE="local"
        fi
    fi

    echo
    print_divider
    echo
    echo -e "  ${CYAN}${BOLD}Select setup type:${RESET}"
    echo
    echo -e "  ${CYAN}  1.${RESET}  ${BOLD}VPS / remote server${RESET}"
    echo -e "       ${DIM}SSH or cloud provider — fresh headless server${RESET}"
    echo -e "  ${CYAN}  2.${RESET}  ${BOLD}Local Ubuntu desktop${RESET}"
    echo -e "       ${DIM}Physically present at this machine — Ubuntu Desktop installed${RESET}"
    echo

    if [[ "$SETUP_MODE" == "local" ]]; then
        DEFAULT_CHOICE="2"
        echo -e "  ${GREEN}Auto-detected: local desktop${RESET}"
    else
        DEFAULT_CHOICE="1"
        echo -e "  ${GREEN}Auto-detected: VPS / remote server${RESET}"
    fi
    echo

    read -rp "  Enter choice [${DEFAULT_CHOICE}]: " mode_choice
    mode_choice="${mode_choice:-$DEFAULT_CHOICE}"

    case "$mode_choice" in
        2) SETUP_MODE="local" ;;
        *) SETUP_MODE="vps"   ;;
    esac
}

# ── Steps ─────────────────────────────────────────────────────────────────────
install_python() {
    print_step 2 4 "Installing Python and dependencies...    "
    if ! command -v python3 &> /dev/null; then
        apt-get update -qq
        apt-get install -y -qq python3 python3-pip python3-tk > /dev/null 2>&1
    else
        # Ensure tkinter is present even if python3 was pre-installed
        apt-get install -y -qq python3-tk > /dev/null 2>&1
    fi
    print_ok
}

install_scripts() {
    print_step 3 4 "Installing setup scripts...              "

    # Locate scripts — check ubuntu/ subdirectory first, then current directory
    SCRIPT_DIR=""
    if [[ -f "ubuntu/universal_vps_setup.py" && -f "ubuntu/post_lockdown_setup.py" ]]; then
        SCRIPT_DIR="ubuntu"
    elif [[ -f "universal_vps_setup.py" && -f "post_lockdown_setup.py" ]]; then
        SCRIPT_DIR="."
    fi

    if [[ -n "$SCRIPT_DIR" ]]; then
        cp "$SCRIPT_DIR/universal_vps_setup.py" /usr/local/bin/
        cp "$SCRIPT_DIR/post_lockdown_setup.py" /usr/local/bin/
        chmod +x /usr/local/bin/universal_vps_setup.py
        chmod +x /usr/local/bin/post_lockdown_setup.py
        if [[ "$SETUP_MODE" == "local" ]]; then
            cp "$SCRIPT_DIR/local_setup.py" /usr/local/bin/
            chmod +x /usr/local/bin/local_setup.py
        fi
    else
        # Repo not available locally — download from GitHub
        REPO_BASE="https://raw.githubusercontent.com/brandonbelew/secureclaw/${BRANCH}"
        if ! command -v curl &> /dev/null; then
            apt-get install -y -qq curl > /dev/null 2>&1
        fi
        curl -fsSL "$REPO_BASE/ubuntu/universal_vps_setup.py" -o /usr/local/bin/universal_vps_setup.py
        curl -fsSL "$REPO_BASE/ubuntu/post_lockdown_setup.py" -o /usr/local/bin/post_lockdown_setup.py
        chmod +x /usr/local/bin/universal_vps_setup.py
        chmod +x /usr/local/bin/post_lockdown_setup.py
        if [[ "$SETUP_MODE" == "local" ]]; then
            curl -fsSL "$REPO_BASE/ubuntu/local_setup.py" -o /usr/local/bin/local_setup.py
            chmod +x /usr/local/bin/local_setup.py
        fi
    fi

    print_ok
}

create_shortcuts() {
    print_step 4 4 "Creating shortcuts...                    "

    cat > /usr/local/bin/vps-setup << EOF
#!/bin/bash
REPO_BASE="https://raw.githubusercontent.com/brandonbelew/secureclaw/${BRANCH}"
curl -fsSL "\$REPO_BASE/ubuntu/universal_vps_setup.py?\$(date +%s)" -o /usr/local/bin/universal_vps_setup.py \
    && chmod +x /usr/local/bin/universal_vps_setup.py \
    || echo "  Warning: could not fetch latest script, running cached version"
python3 /usr/local/bin/universal_vps_setup.py "\$@"
EOF

    cat > /usr/local/bin/vps-post-setup << EOF
#!/bin/bash
REPO_BASE="https://raw.githubusercontent.com/brandonbelew/secureclaw/${BRANCH}"
if curl -fsSL "\$REPO_BASE/ubuntu/post_lockdown_setup.py?\$(date +%s)" -o /usr/local/bin/post_lockdown_setup.py; then
    chmod +x /usr/local/bin/post_lockdown_setup.py
    sed -i 's/^REPO_BRANCH_OVERRIDE = None.*\$/REPO_BRANCH_OVERRIDE = "${BRANCH}"/' /usr/local/bin/post_lockdown_setup.py
else
    echo "  Warning: could not fetch latest script, running cached version"
fi
python3 /usr/local/bin/post_lockdown_setup.py "\$@"
EOF

    cat > /usr/local/bin/local-setup << EOF
#!/bin/bash
REPO_BASE="https://raw.githubusercontent.com/brandonbelew/secureclaw/${BRANCH}"
if curl -fsSL "\$REPO_BASE/ubuntu/local_setup.py?\$(date +%s)" -o /usr/local/bin/local_setup.py; then
    chmod +x /usr/local/bin/local_setup.py
else
    echo "  Warning: could not fetch latest script, running cached version"
fi
export SECURECLAW_BRANCH="${BRANCH}"
python3 /usr/local/bin/local_setup.py "\$@"
EOF

    chmod +x /usr/local/bin/vps-setup
    chmod +x /usr/local/bin/vps-post-setup
    chmod +x /usr/local/bin/local-setup
    print_ok
}

show_complete() {
    if [[ "$SETUP_MODE" == "local" ]]; then
        show_complete_local
    else
        show_complete_vps
    fi
}

show_complete_vps() {
    echo
    print_divider
    echo
    echo -e "  ${GREEN}${BOLD}  Installation complete!${RESET}"
    echo
    echo -e "  This installer will set up your server with:"
    echo -e "  ${GREEN}  ✓${RESET}  Remote Desktop (RDP) access"
    echo -e "  ${GREEN}  ✓${RESET}  A dedicated user account with sudo access"
    echo -e "  ${GREEN}  ✓${RESET}  Tailscale VPN — secure remote access from anywhere"
    echo -e "  ${GREEN}  ✓${RESET}  OpenClaw AI assistant — running as a background service"
    echo -e "  ${GREEN}  ✓${RESET}  Google Chrome browser"
    echo
    print_divider
    echo
    echo -e "  ${BOLD}What happens next:${RESET}"
    echo
    echo -e "  ${CYAN}  1.${RESET}  The setup wizard will guide you step by step"
    echo -e "  ${CYAN}  2.${RESET}  You will create your RDP login username and password"
    echo -e "  ${CYAN}  3.${RESET}  You will be asked to authenticate Tailscale"
    echo -e "       ${DIM}(a link will appear — open it in your browser)${RESET}"
    echo -e "  ${CYAN}  4.${RESET}  After lockdown, SSH will drop — reconnect via Tailscale"
    echo -e "  ${CYAN}  5.${RESET}  Run ${YELLOW}sudo vps-post-setup${RESET} to finish the installation"
    echo
    print_divider
    echo
}

show_complete_local() {
    echo
    print_divider
    echo
    echo -e "  ${GREEN}${BOLD}  Installation complete!${RESET}"
    echo
    echo -e "  This installer will set up your local machine with:"
    echo -e "  ${GREEN}  ✓${RESET}  xrdp — remote desktop access via Tailscale"
    echo -e "  ${GREEN}  ✓${RESET}  Tailscale VPN — reach this machine from anywhere"
    echo -e "  ${GREEN}  ✓${RESET}  Tailscale-only firewall rules (SSH + RDP)"
    echo -e "  ${GREEN}  ✓${RESET}  OpenClaw AI assistant — running as a background service"
    echo -e "  ${GREEN}  ✓${RESET}  Google Chrome browser"
    echo
    print_divider
    echo
    echo -e "  ${BOLD}What happens next:${RESET}"
    echo
    echo -e "  ${CYAN}  1.${RESET}  The setup wizard will guide you step by step"
    echo -e "  ${CYAN}  2.${RESET}  You will select or create the install user"
    echo -e "  ${CYAN}  3.${RESET}  You will be asked to authenticate Tailscale"
    echo -e "       ${DIM}(a link will appear — open it in your browser)${RESET}"
    echo -e "  ${CYAN}  4.${RESET}  Everything installs in a single pass — no reconnect needed"
    echo -e "  ${CYAN}  5.${RESET}  Run ${YELLOW}sudo local-setup${RESET} any time to re-run or resume"
    echo
    print_divider
    echo
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    print_banner

    check_root
    check_ubuntu

    # If stdin is not a terminal (e.g. curl | bash), reconnect to the
    # controlling terminal so interactive read prompts work. Falls back
    # silently if /dev/tty is unavailable (containers, CI, etc.).
    if [[ ! -t 0 ]]; then
        exec < /dev/tty 2>/dev/null || true
    fi

    detect_mode

    print_divider
    echo
    echo -e "  Type ${YELLOW}${BOLD}INSTALL${RESET} to accept and continue, or anything else to cancel."
    echo
    read -rp "  > " confirm
    echo
    if [[ "$confirm" != "INSTALL" ]]; then
        echo -e "  ${YELLOW}Cancelled.${RESET} No changes were made to your server."
        echo
        exit 0
    fi

    echo -e "  ${BOLD}Preparing your server...${RESET}"
    echo
    print_step 1 4 "Checking system...                       "
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        print_ok
        print_info "Detected: ${PRETTY_NAME}"
    else
        print_ok
    fi

    install_python
    install_scripts
    create_shortcuts
    show_complete

    echo -e "  ${GREEN}${BOLD}Starting setup wizard...${RESET}"
    echo
    if [[ "$SETUP_MODE" == "local" ]]; then
        exec /usr/local/bin/local-setup
    else
        exec /usr/local/bin/vps-setup
    fi
}

main
