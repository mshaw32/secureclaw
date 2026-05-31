#!/usr/bin/env bash
# install_widget.sh — Standalone OpenClaw Control Panel installer
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/mshaw32/secureclaw/main/ubuntu/install_widget.sh | sudo bash
#   curl -fsSL https://raw.githubusercontent.com/mshaw32/secureclaw/dev/ubuntu/install_widget.sh  | sudo bash -s -- dev

set -euo pipefail

REPO_OWNER="mshaw32"
REPO_NAME="secureclaw"
INSTALL_BIN="/usr/local/bin/openclaw-widget"
DESKTOP_DIR="/usr/local/share/applications"
SUDOERS_FILE="/etc/sudoers.d/openclaw-widget"

# ── Detect branch ──────────────────────────────────────────────────────────────
detect_branch() {
    # If a branch argument was passed, use it
    if [[ -n "${1:-}" ]]; then
        echo "$1"
        return
    fi
    # If we're inside the repo, use git
    if git rev-parse --is-inside-work-tree &>/dev/null 2>&1; then
        local branch
        branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
        if [[ "$branch" == "main" || "$branch" == "dev" ]]; then
            echo "$branch"
            return
        fi
    fi
    echo "main"
}

BRANCH=$(detect_branch "${1:-}")
echo "Using branch: $BRANCH"

RAW_BASE="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${BRANCH}"

# ── Install GTK3 dependencies ──────────────────────────────────────────────────
echo "[1/7] Installing dependencies..."
apt-get install -y python3-gi gir1.2-gtk-3.0 wget >/dev/null

# ── Download widget script ─────────────────────────────────────────────────────
echo "[2/7] Downloading openclaw-widget..."
wget -q -O "$INSTALL_BIN" "${RAW_BASE}/ubuntu/openclaw_widget.py"
chmod +x "$INSTALL_BIN"
# Inject branch so widget can fetch manifest from the correct branch at runtime
sed -i "s/^REPO_BRANCH_OVERRIDE = None.*$/REPO_BRANCH_OVERRIDE = \"${BRANCH}\"/" "$INSTALL_BIN"

# ── Sudoers entry for UFW status ───────────────────────────────────────────────
echo "[3/7] Writing sudoers entry..."
cat > "$SUDOERS_FILE" <<'EOF'
# Allow sudo group members to check UFW status without a password (used by openclaw-widget)
%sudo ALL=(ALL) NOPASSWD: /usr/sbin/ufw status
EOF
chmod 440 "$SUDOERS_FILE"

# ── System-wide .desktop file ──────────────────────────────────────────────────
echo "[4/7] Installing application menu entry..."
mkdir -p "$DESKTOP_DIR"
cat > "${DESKTOP_DIR}/openclaw-widget.desktop" <<'EOF'
[Desktop Entry]
Name=OpenClaw Control Panel
Comment=OpenClaw service status and launcher
Exec=/usr/local/bin/openclaw-widget
Icon=network-server
Terminal=false
Type=Application
Categories=Network;System;
StartupNotify=true
X-GNOME-Autostart-enabled=true
EOF

# ── Per-user autostart + desktop shortcut ─────────────────────────────────────
echo "[5/7] Creating per-user autostart and desktop entries..."

DESKTOP_CONTENT="[Desktop Entry]
Name=OpenClaw Control Panel
Comment=OpenClaw service status and launcher
Exec=/usr/local/bin/openclaw-widget
Icon=network-server
Terminal=false
Type=Application
Categories=Network;System;
StartupNotify=true
X-GNOME-Autostart-enabled=true"

for user_dir in /home/*/; do
    [[ -d "$user_dir" ]] || continue
    username=$(basename "$user_dir")
    uid=$(id -u "$username" 2>/dev/null || echo 0)
    (( uid < 1000 )) && continue

    # Autostart
    autostart_dir="${user_dir}.config/autostart"
    mkdir -p "$autostart_dir"
    echo "$DESKTOP_CONTENT" > "${autostart_dir}/openclaw-widget.desktop"
    chown -R "${username}:${username}" "$autostart_dir"

    # Desktop shortcut
    desktop_dir="${user_dir}Desktop"
    mkdir -p "$desktop_dir"
    echo "$DESKTOP_CONTENT" > "${desktop_dir}/openclaw-widget.desktop"
    chmod +x "${desktop_dir}/openclaw-widget.desktop"
    chown "${username}:${username}" "${desktop_dir}/openclaw-widget.desktop"

    echo "  -> autostart + desktop shortcut created for $username"
done

echo "[6/7] Updating desktop database..."
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo "[7/7] Done!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " OpenClaw Control Panel installed successfully!"
echo ""
echo " To launch now:       openclaw-widget &"
echo " Auto-starts on:      next RDP session login"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
