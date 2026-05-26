#!/usr/bin/env python3
"""
Post-Lockdown Setup Continuation Script
Completes OpenClaw and Chrome installation after server lockdown
Author: Brandon
"""

import os
import sys
import subprocess
import time
import pwd
from pathlib import Path

# Injected at install time by vps-post-setup shortcut via sed.
# When None, _get_repo_branch() falls back to git detection.
REPO_BRANCH_OVERRIDE = None  # injected at install time

def _real_user_homes():
    """Yield Path objects for /home subdirs owned by real system users (uid >= 1000).
    Excludes dirs like /home/linuxbrew that are not actual user accounts."""
    for d in Path("/home").iterdir():
        if not d.is_dir():
            continue
        try:
            entry = pwd.getpwnam(d.name)
            if entry.pw_uid >= 1000:
                yield d
        except KeyError:
            continue


class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

class PostLockdownSetup:
    def __init__(self):
        self.setup_log = []
        
    def log(self, message, level="INFO"):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {level}: {message}"
        self.setup_log.append(log_entry)
        
        if level == "ERROR":
            print(f"{Colors.FAIL}{log_entry}{Colors.ENDC}")
        elif level == "WARNING":
            print(f"{Colors.WARNING}{log_entry}{Colors.ENDC}")
        elif level == "SUCCESS":
            print(f"{Colors.GREEN}{log_entry}{Colors.ENDC}")
        else:
            print(f"{Colors.CYAN}{log_entry}{Colors.ENDC}")

    def run_command(self, command, check=True, shell=True, capture_output=True):
        try:
            self.log(f"Executing: {command}")
            result = subprocess.run(
                command, 
                shell=shell, 
                check=check, 
                capture_output=capture_output,
                text=True
            )
            if capture_output and result.stdout:
                self.log(f"Command output: {result.stdout.strip()}")
            return result
        except subprocess.CalledProcessError as e:
            self.log(f"Command failed: {command}", "ERROR")
            if capture_output and e.stderr:
                self.log(f"Error output: {e.stderr.strip()}", "ERROR")
            raise

    def verify_tailscale_connection(self):
        """Verify we're connected via Tailscale"""
        print(f"\n{Colors.HEADER}=== VERIFYING TAILSCALE CONNECTION ==={Colors.ENDC}")
        
        try:
            result = self.run_command("tailscale ip -4")
            tailscale_ip = result.stdout.strip()
            
            # Check if we're connecting from SSH_CLIENT via Tailscale network
            ssh_client = os.environ.get('SSH_CLIENT', '')
            if ssh_client:
                client_ip = ssh_client.split()[0]
                if client_ip.startswith('100.'):  # Tailscale IP range
                    self.log(f"Confirmed connection via Tailscale from {client_ip}", "SUCCESS")
                    return True
                else:
                    self.log(f"Warning: Connected from non-Tailscale IP {client_ip}", "WARNING")
            
            self.log(f"Server Tailscale IP: {tailscale_ip}", "SUCCESS")
            return True
            
        except Exception as e:
            self.log(f"Failed to verify Tailscale connection: {e}", "ERROR")
            return False

    def configure_hostname(self):
        """Interactively set a memorable system hostname and sync it to Tailscale."""
        import re
        print(f"\n{Colors.HEADER}=== SET SERVER HOSTNAME ==={Colors.ENDC}")

        try:
            current = subprocess.run(
                ["hostname"], capture_output=True, text=True
            ).stdout.strip()
        except Exception:
            current = "unknown"

        print(f"""
{Colors.CYAN}Give your server a memorable name. It will appear in:{Colors.ENDC}
  • Your Tailscale admin console  (tailscale.com/admin/machines)
  • Your terminal prompt
  • The OpenClaw Control Panel widget

{Colors.DIM}Examples:  trade-bot-1   openclaw-prod   my-vps   btc-server{Colors.ENDC}

Current hostname: {Colors.BOLD}{current}{Colors.ENDC}
""")

        name = input(
            f"{Colors.CYAN}Enter new hostname (or press Enter to keep '{current}'): {Colors.ENDC}"
        ).strip()

        if not name:
            self.log(f"Keeping existing hostname: {current}", "INFO")
            return

        # Sanitize to RFC 1123: lowercase, alphanumeric + hyphens, no leading/trailing hyphens
        name = re.sub(r'[^a-z0-9-]', '-', name.lower()).strip('-')
        if not name:
            self.log("Invalid hostname entered, keeping existing", "WARNING")
            return

        # Set system hostname
        self.run_command(f"hostnamectl set-hostname {name}")
        self.log(f"System hostname set to: {name}", "SUCCESS")

        # Push to Tailscale (tailscale set available since Tailscale 1.42)
        result = subprocess.run(
            ["tailscale", "set", f"--hostname={name}"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            self.log(f"Tailscale hostname updated to: {name}", "SUCCESS")
        else:
            self.log(
                f"Could not update Tailscale hostname automatically. "
                f"Set it manually: tailscale.com/admin/machines → ... → Edit name",
                "WARNING"
            )

    def test_lockdown_status(self):
        """Verify server lockdown is working"""
        print(f"\n{Colors.HEADER}=== LOCKDOWN STATUS CHECK ==={Colors.ENDC}")
        
        # Check UFW status
        result = self.run_command("ufw status verbose")
        if "Status: active" in result.stdout:
            self.log("UFW firewall is active", "SUCCESS")
            
            # Show current rules
            rules = result.stdout
            if "100.64.0.0/10" in rules:
                self.log("Tailscale subnet rules are active", "SUCCESS")
            else:
                self.log("Tailscale subnet rules not found", "WARNING")
        else:
            self.log("UFW firewall is not active!", "ERROR")
        
        # Check SSH configuration
        try:
            result = self.run_command("ss -tlnp | grep :22")
            tailscale_result = self.run_command("tailscale ip -4")
            tailscale_ip = tailscale_result.stdout.strip()
            
            if tailscale_ip in result.stdout:
                self.log("SSH is listening only on Tailscale IP", "SUCCESS")
            else:
                self.log("SSH may be listening on other interfaces", "WARNING")
        except:
            self.log("Could not verify SSH configuration", "WARNING")

    def get_install_user(self):
        """Find the primary non-root user to install OpenClaw for"""
        users = [d.name for d in _real_user_homes()]
        if len(users) == 1:
            return users[0]
        elif len(users) > 1:
            print(f"\n{Colors.CYAN}Multiple users found: {', '.join(users)}{Colors.ENDC}")
            while True:
                choice = input("Enter username to install OpenClaw for: ").strip()
                if choice in users:
                    return choice
                print(f"{Colors.WARNING}Invalid choice. Options: {', '.join(users)}{Colors.ENDC}")
        else:
            self.log("No regular user found in /home", "ERROR")
            return None

    def install_openclaw(self):
        """Install OpenClaw using the official installer"""
        print(f"\n{Colors.HEADER}=== OPENCLAW AI INSTALLATION ==={Colors.ENDC}")
        self.log("Installing OpenClaw AI...")

        install_user = self.get_install_user()
        if not install_user:
            self.log("Skipping OpenClaw install — no target user found", "WARNING")
            return

        # Remove legacy system service if present from a previous install
        legacy_service = Path("/etc/systemd/system/openclaw.service")
        if legacy_service.exists():
            self.run_command("systemctl stop openclaw", check=False)
            self.run_command("systemctl disable openclaw", check=False)
            legacy_service.unlink()
            self.run_command("systemctl daemon-reload")
            self.log("Removed legacy openclaw system service", "SUCCESS")

        # Pre-install Node.js as root so the official installer doesn't need
        # sudo internally (which fails without a TTY in a su subprocess).
        self.log("Installing Node.js and build tools...")
        print(f"\n  {Colors.WARNING}{Colors.BOLD}⚠  Note:{Colors.ENDC}{Colors.WARNING} This step can take 2–3 minutes and may appear to hang.{Colors.ENDC}")
        print(f"  {Colors.WARNING}   If progress stops, press Enter a few times to continue.{Colors.ENDC}\n")
        self.run_command("curl -fsSL https://deb.nodesource.com/setup_22.x | bash -")
        self.run_command("apt-get install -y nodejs build-essential cmake make g++ python3")

        # Run the official OpenClaw installer as the target user.
        # Node.js is already present so the installer skips the sudo step.
        self.log("Running official OpenClaw installer...")
        self.run_command(
            f"su - {install_user} -c "
            f"'curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard'",
            capture_output=False
        )

        # Enable linger so the user's systemd services start at boot
        # without requiring an active login session
        self.run_command(f"loginctl enable-linger {install_user}")
        self.log("OpenClaw installed and gateway service registered", "SUCCESS")

    def install_homebrew(self):
        """Pre-install Homebrew so OpenClaw skills install correctly during onboarding"""
        print(f"\n{Colors.HEADER}=== HOMEBREW INSTALLATION ==={Colors.ENDC}")
        install_user = self.get_install_user()
        if not install_user:
            self.log("No install user set — skipping Homebrew", "WARNING")
            return

        # Check if already present for this user
        result = self.run_command(
            f"su - {install_user} -c 'command -v brew'", check=False
        )
        if result.returncode == 0:
            self.log("Homebrew already present — skipping", "SUCCESS")
            return

        self.log("Installing Homebrew (required for OpenClaw skills)...")
        # Extra deps Homebrew needs on Linux beyond what we already installed
        self.run_command("apt-get install -y -qq file procps")

        # Pre-create the Homebrew prefix as root and give the user ownership
        # so the installer doesn't need sudo to create /home/linuxbrew
        self.run_command("mkdir -p /home/linuxbrew/.linuxbrew")
        self.run_command(f"chown -R {install_user}:{install_user} /home/linuxbrew")

        # Download installer as root, run it as the target user
        self.run_command(
            "curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh "
            "-o /tmp/brew_install.sh"
        )
        self.run_command(
            f"su - {install_user} -c 'NONINTERACTIVE=1 bash /tmp/brew_install.sh'",
            capture_output=False
        )
        self.run_command("rm -f /tmp/brew_install.sh", check=False)

        # Add brew to the user's shell profile so it's on PATH after login
        brew_env = 'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"'
        for rc in [f"/home/{install_user}/.bashrc", f"/home/{install_user}/.profile"]:
            self.run_command(
                f"grep -qF 'linuxbrew' {rc} || echo '{brew_env}' >> {rc}",
                check=False
            )

        self.log("Homebrew installed", "SUCCESS")

    def install_chrome(self):
        """Install Google Chrome"""
        print(f"\n{Colors.HEADER}=== GOOGLE CHROME INSTALLATION ==={Colors.ENDC}")
        self.log("Installing Google Chrome...")
        
        # Check if already installed
        result = self.run_command("dpkg -l | grep google-chrome", check=False)
        if result.returncode == 0:
            self.log("Google Chrome is already installed", "SUCCESS")
            return
        
        # Download and install Chrome
        try:
            # Download Chrome .deb package
            self.log("Downloading Chrome package...")
            self.run_command("wget -q -O /tmp/google-chrome-stable_current_amd64.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb")
            
            # Install Chrome
            self.log("Installing Chrome package...")
            self.run_command("apt install -y /tmp/google-chrome-stable_current_amd64.deb")
            
            # Clean up
            self.run_command("rm -f /tmp/google-chrome-stable_current_amd64.deb")
            
        except subprocess.CalledProcessError:
            # Fallback method using repository
            self.log("Fallback: Installing Chrome via repository...", "WARNING")

            # Add Google Chrome repository key and source
            self.run_command("wget -q -O /usr/share/keyrings/google-chrome.gpg https://dl.google.com/linux/linux_signing_key.pub")
            self.run_command('echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list')
            
            # Update and install
            self.run_command("apt update")
            self.run_command("apt install -y google-chrome-stable")
        
        # Verify installation
        result = self.run_command("google-chrome --version")
        self.log(f"Chrome installed: {result.stdout.strip()}", "SUCCESS")

    def install_security_check(self):
        """Install the desktop security verification script"""
        print(f"\n{Colors.HEADER}=== SECURITY CHECK TOOL ==={Colors.ENDC}")
        self.log("Installing security check tool...")

        script = r"""#!/bin/bash
# SecureClaw Security Verification

# ── Auto-elevate to root ───────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    exec sudo bash "$0" "$@"
fi

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

pass()    { echo -e "  ${GREEN}✓${RESET}  $1"; }
fail()    { echo -e "  ${RED}✗  $1${RESET}"; ISSUES=$((ISSUES+1)); }
warn()    { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
info()    { echo -e "  ${CYAN}ℹ${RESET}  $1"; }
section() { echo -e "\n${BOLD}  ── $1${RESET}\n"; }
fix_ok()  { echo -e "    ${GREEN}✓  $1${RESET}"; }
fix_err() { echo -e "    ${RED}✗  $1${RESET}"; }

ISSUES=0
FIX_UFW=0
FIX_UFW6=0
FIX_TS_RULE=0
FIX_SSH_RULE=0
FIX_RDP_RULE=0
RESTART_SVCS=()

clear
echo
echo -e "${BOLD}  ╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}  ║        🦞  SecureClaw Security Verification                 ║${RESET}"
echo -e "${BOLD}  ║        $(date '+%Y-%m-%d %H:%M:%S')                                 ║${RESET}"
echo -e "${BOLD}  ╚══════════════════════════════════════════════════════════════╝${RESET}"

# ── Firewall ──────────────────────────────────────────────────────────────────
section "Firewall (UFW)"
ufw_out=$(ufw status verbose 2>/dev/null)
if echo "$ufw_out" | grep -q "Status: active"; then
    pass "UFW is active"
else
    fail "UFW is NOT active — server is unprotected!"; FIX_UFW=1
fi
if grep -q "^IPV6=yes" /etc/default/ufw 2>/dev/null; then
    pass "UFW IPv6 filtering is enabled"
else
    fail "UFW IPv6 filtering is disabled — IPv6 traffic may be unprotected!"; FIX_UFW6=1
fi
if echo "$ufw_out" | grep -q "tailscale0"; then
    pass "Tailscale interface rules present"
else
    fail "Tailscale interface rules missing"; FIX_TS_RULE=1
fi
if echo "$ufw_out" | grep -qE "100\.64\.0\.0/10.*22|22.*100\.64\.0\.0/10"; then
    pass "SSH (22) restricted to Tailscale IPv4 subnet"
else
    fail "SSH (22) does not have a Tailscale IPv4 rule"; FIX_SSH_RULE=1
fi
if echo "$ufw_out" | grep -qE "fd7a:115c:a1e0::/48.*22|22.*fd7a:115c:a1e0::/48"; then
    pass "SSH (22) restricted to Tailscale IPv6 subnet"
else
    fail "SSH (22) does not have a Tailscale IPv6 rule"; FIX_SSH_RULE=1
fi
if echo "$ufw_out" | grep -qE "100\.64\.0\.0/10.*3389|3389.*100\.64\.0\.0/10"; then
    pass "RDP (3389) restricted to Tailscale IPv4 subnet"
else
    fail "RDP (3389) does not have a Tailscale IPv4 rule"; FIX_RDP_RULE=1
fi
if echo "$ufw_out" | grep -qE "fd7a:115c:a1e0::/48.*3389|3389.*fd7a:115c:a1e0::/48"; then
    pass "RDP (3389) restricted to Tailscale IPv6 subnet"
else
    fail "RDP (3389) does not have a Tailscale IPv6 rule"; FIX_RDP_RULE=1
fi

# ── Tailscale ─────────────────────────────────────────────────────────────────
section "Tailscale VPN"
ts_ip=$(tailscale ip -4 2>/dev/null)
if [ -n "$ts_ip" ]; then
    pass "Connected — Tailscale IP: $ts_ip"
else
    fail "Tailscale is not connected!"
    info "Manual fix: run  sudo tailscale up  then authenticate in your browser"
fi

# ── SSH ───────────────────────────────────────────────────────────────────────
section "SSH (port 22)"
ssh_listen=$(ss -tlnp 2>/dev/null | grep ':22 ')
if [ -n "$ssh_listen" ]; then
    if echo "$ssh_listen" | grep -qE "0\.0\.0\.0:22|\*:22|:::22"; then
        if [ "$FIX_UFW" -eq 0 ] && [ "$FIX_SSH_RULE" -eq 0 ]; then
            pass "SSH listening on all interfaces — access restricted by UFW to Tailscale subnet only"
        else
            warn "SSH is listening on all interfaces and UFW rules need attention (see Firewall section)"
        fi
    else
        pass "SSH is bound to restricted interface only"
    fi
else
    warn "SSH does not appear to be listening"
fi

# ── RDP ───────────────────────────────────────────────────────────────────────
section "RDP (port 3389)"
rdp_listen=$(ss -tlnp 2>/dev/null | grep ':3389 ')
if [ -n "$rdp_listen" ]; then
    pass "XRDP is listening on port 3389"
    info "Protected by UFW — only reachable via Tailscale (100.64.0.0/10)"
else
    warn "XRDP does not appear to be listening on 3389"
fi

# ── OpenClaw ──────────────────────────────────────────────────────────────────
section "OpenClaw"
if systemctl is-active --quiet openclaw; then
    pass "OpenClaw service is running"
    oc_ports=$(ss -tlnp 2>/dev/null | grep -i openclaw | awk '{print $4}' | sed 's/.*://' | sort -u)
    if [ -n "$oc_ports" ]; then
        for port in $oc_ports; do
            if echo "$ufw_out" | grep -q "$port"; then
                pass "OpenClaw port $port has an explicit UFW rule"
            else
                info "OpenClaw port $port — covered by UFW default deny incoming"
            fi
        done
    else
        info "OpenClaw does not expose a network port"
    fi
else
    warn "OpenClaw service is not running"; RESTART_SVCS+=("openclaw")
fi

# ── Services ──────────────────────────────────────────────────────────────────
section "Services"
for svc in xrdp tailscaled chrome-cleanup.timer; do
    if systemctl is-active --quiet "$svc"; then
        pass "$svc is running"
    else
        warn "$svc is not active"; RESTART_SVCS+=("$svc")
    fi
done

# ── Summary ───────────────────────────────────────────────────────────────────
echo
echo -e "  ${DIM}──────────────────────────────────────────────────────────────${RESET}"
echo
if [ "$ISSUES" -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}  ✓  All checks passed — server is properly secured.${RESET}"
    echo
    read -rp "  Press Enter to close..."
    exit 0
fi

echo -e "  ${RED}${BOLD}  ✗  $ISSUES issue(s) found — review the output above.${RESET}"
echo

# ── Auto-fix ──────────────────────────────────────────────────────────────────
fixable=$((FIX_UFW + FIX_UFW6 + FIX_TS_RULE + FIX_SSH_RULE + FIX_RDP_RULE + ${#RESTART_SVCS[@]}))

if [ "$fixable" -gt 0 ]; then
    echo -e "  ${CYAN}${BOLD}$fixable issue(s) can be fixed automatically:${RESET}"
    [ "$FIX_UFW"      -eq 1 ] && echo -e "    ${YELLOW}→${RESET}  Enable UFW"
    [ "$FIX_UFW6"     -eq 1 ] && echo -e "    ${YELLOW}→${RESET}  Enable UFW IPv6 filtering"
    [ "$FIX_TS_RULE"  -eq 1 ] && echo -e "    ${YELLOW}→${RESET}  Add Tailscale interface rule"
    [ "$FIX_SSH_RULE" -eq 1 ] && echo -e "    ${YELLOW}→${RESET}  Restrict SSH to Tailscale subnets (IPv4 + IPv6)"
    [ "$FIX_RDP_RULE" -eq 1 ] && echo -e "    ${YELLOW}→${RESET}  Restrict RDP to Tailscale subnets (IPv4 + IPv6)"
    for svc in "${RESTART_SVCS[@]}"; do
        echo -e "    ${YELLOW}→${RESET}  Start and enable $svc"
    done
    echo
    read -rp "  Apply fixes now? [y/N] > " fix_ans
    echo

    if [[ "$fix_ans" =~ ^[Yy]$ ]]; then
        echo -e "  ${BOLD}Applying fixes...${RESET}"
        echo
        ufw_changed=0

        if [ "$FIX_UFW" -eq 1 ]; then
            echo -e "  → Enabling UFW..."
            ufw --force enable && fix_ok "UFW enabled" || fix_err "Failed to enable UFW"
            ufw_changed=1
        fi

        if [ "$FIX_UFW6" -eq 1 ]; then
            echo -e "  → Enabling UFW IPv6 filtering..."
            sed -i 's/^IPV6=no/IPV6=yes/' /etc/default/ufw
            grep -q '^IPV6=' /etc/default/ufw || echo 'IPV6=yes' >> /etc/default/ufw
            fix_ok "UFW IPv6 filtering enabled"
            ufw_changed=1
        fi

        if [ "$FIX_TS_RULE" -eq 1 ]; then
            echo -e "  → Adding Tailscale interface rules..."
            ufw allow in on tailscale0 && \
            ufw allow out on tailscale0 && \
            fix_ok "Tailscale interface rules added" || fix_err "Failed to add Tailscale rules"
            ufw_changed=1
        fi

        if [ "$FIX_SSH_RULE" -eq 1 ]; then
            echo -e "  → Restricting SSH to Tailscale subnets (IPv4 + IPv6)..."
            ufw delete allow 22/tcp  2>/dev/null || true
            ufw delete allow 22      2>/dev/null || true
            ufw delete allow OpenSSH 2>/dev/null || true
            ufw allow from 100.64.0.0/10       to any port 22 proto tcp && \
            ufw allow from fd7a:115c:a1e0::/48 to any port 22 proto tcp && \
                fix_ok "SSH restricted to Tailscale (IPv4 + IPv6)" || fix_err "Failed to restrict SSH"
            ufw_changed=1
        fi

        if [ "$FIX_RDP_RULE" -eq 1 ]; then
            echo -e "  → Restricting RDP to Tailscale subnets (IPv4 + IPv6)..."
            ufw delete allow 3389/tcp 2>/dev/null || true
            ufw delete allow 3389     2>/dev/null || true
            ufw allow from 100.64.0.0/10       to any port 3389 proto tcp && \
            ufw allow from fd7a:115c:a1e0::/48 to any port 3389 proto tcp && \
                fix_ok "RDP restricted to Tailscale (IPv4 + IPv6)" || fix_err "Failed to restrict RDP"
            ufw_changed=1
        fi

        if [ "$ufw_changed" -eq 1 ]; then
            echo -e "  → Reloading UFW..."
            ufw --force reload && fix_ok "UFW reloaded" || fix_err "UFW reload failed"
        fi

        for svc in "${RESTART_SVCS[@]}"; do
            echo -e "  → Starting $svc..."
            systemctl enable --now "$svc" 2>/dev/null && \
                fix_ok "$svc started" || fix_err "Could not start $svc"
        done

        echo
        echo -e "  ${GREEN}${BOLD}Fixes applied — re-running verification...${RESET}"
        sleep 2
        exec "$0"
    fi
fi

read -rp "  Press Enter to close..."
"""

        with open("/usr/local/bin/security-check", "w") as f:
            f.write(script)
        os.chmod("/usr/local/bin/security-check", 0o755)
        self.log("Security check script installed", "SUCCESS")

        # Place a .desktop launcher on each user's desktop
        desktop_entry = """\
[Desktop Entry]
Version=1.0
Type=Application
Name=Security Check
Comment=Verify firewall and security settings
Exec=xfce4-terminal --title="SecureClaw Security Check" -e /usr/local/bin/security-check
Icon=security-high
Terminal=false
Categories=System;Security;
"""
        for user_dir in _real_user_homes():
            username = user_dir.name
            desktop_dir = user_dir / "Desktop"
            desktop_dir.mkdir(exist_ok=True)
            shortcut_path = desktop_dir / "security-check.desktop"
            with open(shortcut_path, "w") as f:
                f.write(desktop_entry)
            self.run_command(f"chown {username}:{username} {shortcut_path}")
            self.run_command(f"chmod +x {shortcut_path}")
            self.log(f"Created Security Check shortcut for {username}", "SUCCESS")

    def install_chrome_cleanup(self):
        """Install a daily systemd timer to keep Chrome storage under 1GB"""
        print(f"\n{Colors.HEADER}=== CHROME STORAGE CLEANUP ==={Colors.ENDC}")
        self.log("Installing Chrome storage cleanup timer...")

        install_user = self.get_install_user()
        if not install_user:
            self.log("No target user found — skipping Chrome cleanup", "WARNING")
            return

        home_dir = f"/home/{install_user}"
        chrome_dir = f"{home_dir}/.config/google-chrome"

        cleanup_script = f"""\
#!/bin/bash
# Chrome storage cleanup — trims safe cache dirs when total exceeds 1GB
CHROME_DIR="{chrome_dir}"
MAX_KB=1048576

[ -d "$CHROME_DIR" ] || exit 0

current=$(du -sk "$CHROME_DIR" 2>/dev/null | cut -f1)
if [ "$current" -gt "$MAX_KB" ]; then
    rm -rf "$CHROME_DIR/BrowserMetrics"
    find "$CHROME_DIR" -mindepth 2 -maxdepth 2 -type d \\( \\
        -name "Cache" -o \\
        -name "Code Cache" -o \\
        -name "GPUCache" \\
    \\) -exec rm -rf {{}}/* \\;
    new=$(du -sk "$CHROME_DIR" 2>/dev/null | cut -f1)
    echo "Chrome cleanup: $((current/1024))MB -> $((new/1024))MB"
fi
"""
        with open("/usr/local/bin/chrome-cleanup", "w") as f:
            f.write(cleanup_script)
        os.chmod("/usr/local/bin/chrome-cleanup", 0o755)

        service_content = f"""\
[Unit]
Description=Chrome Storage Cleanup

[Service]
Type=oneshot
User={install_user}
ExecStart=/usr/local/bin/chrome-cleanup
"""
        timer_content = """\
[Unit]
Description=Chrome Storage Cleanup Timer

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
"""
        with open("/etc/systemd/system/chrome-cleanup.service", "w") as f:
            f.write(service_content)
        with open("/etc/systemd/system/chrome-cleanup.timer", "w") as f:
            f.write(timer_content)

        self.run_command("systemctl daemon-reload")
        self.run_command("systemctl enable chrome-cleanup.timer")
        self.run_command("systemctl start chrome-cleanup.timer")
        self.log("Chrome cleanup timer enabled (runs daily)", "SUCCESS")

    def _get_repo_branch(self):
        """Return the active branch. Override injected at install time takes priority."""
        if REPO_BRANCH_OVERRIDE in ("main", "dev"):
            return REPO_BRANCH_OVERRIDE
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True,
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            branch = result.stdout.strip()
            return branch if branch in ("main", "dev") else "main"
        except Exception:
            return "main"

    def install_openclaw_widget(self):
        """Install the OpenClaw Control Panel desktop widget."""
        print(f"\n{Colors.HEADER}=== OPENCLAW CONTROL PANEL ==={Colors.ENDC}")
        self.log("Installing OpenClaw Control Panel...")

        branch = self._get_repo_branch()
        self.log(f"Using branch: {branch}")

        raw_base = f"https://raw.githubusercontent.com/brandonbelew/secureclaw/{branch}"
        widget_url = f"{raw_base}/ubuntu/openclaw_widget.py"
        install_bin = "/usr/local/bin/openclaw-widget"

        # Download widget script
        self.run_command(f"wget -q -O {install_bin} {widget_url}")
        os.chmod(install_bin, 0o755)
        # Inject branch so widget fetches manifest from the correct branch at runtime
        self.run_command(
            f"sed -i 's/^REPO_BRANCH_OVERRIDE = None.*$/REPO_BRANCH_OVERRIDE = \"{branch}\"/' {install_bin}"
        )
        self.log("Widget script downloaded and made executable", "SUCCESS")

        # Install GTK3 Python bindings (pre-installed on XFCE Ubuntu, but ensure present)
        self.run_command("apt-get install -y python3-gi gir1.2-gtk-3.0")
        self.log("GTK3 Python bindings installed", "SUCCESS")

        # Sudoers entry for passwordless UFW status check
        sudoers_content = (
            "# Allow sudo group to check UFW status without password (used by openclaw-widget)\n"
            "%sudo ALL=(ALL) NOPASSWD: /usr/sbin/ufw status\n"
        )
        sudoers_path = "/etc/sudoers.d/openclaw-widget"
        with open(sudoers_path, "w") as f:
            f.write(sudoers_content)
        os.chmod(sudoers_path, 0o440)
        self.log("Sudoers entry written for UFW status check", "SUCCESS")

        # System-wide application menu entry
        desktop_dir = Path("/usr/local/share/applications")
        desktop_dir.mkdir(parents=True, exist_ok=True)
        desktop_content = (
            "[Desktop Entry]\n"
            "Name=OpenClaw Control Panel\n"
            "Comment=OpenClaw service status and launcher\n"
            "Exec=/usr/local/bin/openclaw-widget\n"
            "Icon=network-server\n"
            "Terminal=false\n"
            "Type=Application\n"
            "Categories=Network;System;\n"
            "StartupNotify=true\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        system_desktop_path = desktop_dir / "openclaw-widget.desktop"
        with open(system_desktop_path, "w") as f:
            f.write(desktop_content)
        self.log("Application menu entry written", "SUCCESS")

        # Per-user autostart entries
        for user_dir in _real_user_homes():
            username = user_dir.name
            autostart_dir = user_dir / ".config" / "autostart"
            autostart_dir.mkdir(parents=True, exist_ok=True)

            autostart_path = autostart_dir / "openclaw-widget.desktop"
            with open(autostart_path, "w") as f:
                f.write(desktop_content)
            self.run_command(f"chown -R {username}:{username} {autostart_dir}")

            # Desktop shortcut
            desktop_dir = user_dir / "Desktop"
            desktop_dir.mkdir(exist_ok=True)
            desktop_shortcut = desktop_dir / "openclaw-widget.desktop"
            with open(desktop_shortcut, "w") as f:
                f.write(desktop_content)
            self.run_command(f"chmod +x {desktop_shortcut}")
            self.run_command(f"chown {username}:{username} {desktop_shortcut}")

            self.log(f"Autostart + desktop shortcut created for {username}", "SUCCESS")

        self.log("OpenClaw Control Panel installed", "SUCCESS")

    def create_user_shortcuts(self):
        """Create desktop shortcuts for regular users"""
        print(f"\n{Colors.HEADER}=== CREATING USER SHORTCUTS ==={Colors.ENDC}")
        
        # Find regular user directories (excluding system users)
        user_dirs = list(_real_user_homes())
        
        # URL shortcuts to create on every user's desktop
        url_shortcuts = [
            {
                "filename": "OC-Onboard-Docs.desktop",
                "name": "OC Onboard Docs",
                "url": "https://docs.openclaw.ai/cli/onboard",
                "icon": "text-html",
            },
            {
                "filename": "OC-Browser.desktop",
                "name": "OC Browser",
                "url": "https://docs.openclaw.ai/tools/browser",
                "icon": "text-html",
            },
        ]

        for user_dir in user_dirs:
            username = user_dir.name
            desktop_dir = user_dir / "Desktop"

            # Create Desktop directory if it doesn't exist
            desktop_dir.mkdir(exist_ok=True)

            # Copy Chrome desktop file
            chrome_desktop = "/usr/share/applications/google-chrome.desktop"
            if Path(chrome_desktop).exists():
                user_shortcut = desktop_dir / "google-chrome.desktop"
                self.run_command(f"cp {chrome_desktop} {user_shortcut}")
                self.run_command(f"chown {username}:{username} {user_shortcut}")
                self.run_command(f"chmod +x {user_shortcut}")
                self.log(f"Created google-chrome.desktop shortcut for {username}", "SUCCESS")

            # Create URL shortcuts
            for sc in url_shortcuts:
                content = (
                    f"[Desktop Entry]\n"
                    f"Version=1.0\n"
                    f"Type=Link\n"
                    f"Name={sc['name']}\n"
                    f"URL={sc['url']}\n"
                    f"Icon={sc['icon']}\n"
                )
                shortcut_path = desktop_dir / sc["filename"]
                with open(shortcut_path, "w") as f:
                    f.write(content)
                self.run_command(f"chown {username}:{username} {shortcut_path}")
                self.run_command(f"chmod +x {shortcut_path}")
                self.log(f"Created {sc['name']} shortcut for {username}", "SUCCESS")

            # Enable hidden files in Thunar (XFCE file manager)
            thunar_conf_dir = user_dir / ".config" / "Thunar"
            thunar_conf_dir.mkdir(parents=True, exist_ok=True)
            thunar_conf = thunar_conf_dir / "thunarrc"
            # Write or patch the setting
            existing = thunar_conf.read_text() if thunar_conf.exists() else ""
            if "ShowHidden=" in existing:
                existing = "\n".join(
                    "ShowHidden=TRUE" if line.startswith("ShowHidden=") else line
                    for line in existing.splitlines()
                )
                thunar_conf.write_text(existing)
            elif "[Configuration]" in existing:
                thunar_conf.write_text(existing.rstrip() + "\nShowHidden=TRUE\n")
            else:
                thunar_conf.write_text("[Configuration]\nShowHidden=TRUE\n")
            self.run_command(f"chown -R {username}:{username} {thunar_conf_dir}")
            self.log(f"Enabled hidden files in Thunar for {username}", "SUCCESS")

    def create_final_report(self):
        """Create final setup report"""
        print(f"\n{Colors.HEADER}=== FINAL SETUP REPORT ==={Colors.ENDC}")
        
        # Get system information
        try:
            tailscale_result = self.run_command("tailscale ip -4")
            tailscale_ip = tailscale_result.stdout.strip()
        except:
            tailscale_ip = "Not available"
        
        try:
            chrome_result = self.run_command("google-chrome --version")
            chrome_version = chrome_result.stdout.strip()
        except:
            chrome_version = "Installation failed"
        
        try:
            openclaw_result = self.run_command("systemctl is-active openclaw", check=False)
            openclaw_status = "Running" if openclaw_result.stdout.strip() == "active" else "Installed (service not active)"
        except:
            openclaw_status = "Installation failed"
        
        report = f"""
{Colors.GREEN}{Colors.BOLD}VPS SETUP COMPLETED SUCCESSFULLY!{Colors.ENDC}

{Colors.CYAN}Final Configuration Summary:{Colors.ENDC}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{Colors.BOLD}Network Configuration:{Colors.ENDC}
• Tailscale IP: {tailscale_ip}
• RDP Access: {tailscale_ip}:3389
• SSH Access: ssh user@{tailscale_ip}
• Firewall: UFW active (Tailscale-only access)

{Colors.BOLD}Installed Software:{Colors.ENDC}
• RDP Server: XRDP with session persistence
• OpenClaw: {openclaw_status}
• Google Chrome: {chrome_version}

{Colors.BOLD}Desktop Applications:{Colors.ENDC}
• Applications available in desktop environment
• Shortcuts created on user desktops
• Accessible via RDP connection

{Colors.WARNING}Security Notes:{Colors.ENDC}
Your server is hardened using Tailscale VPN and UFW firewall rules that
restrict SSH and RDP to the Tailscale subnet only. Tailscale is SOC 2
Type II certified, end-to-end encrypted, and independently audited.

This configuration significantly reduces your attack surface, but it is
not a substitute for good security practices:

  {Colors.BOLD}•{Colors.ENDC}  Use a strong, unique password for your RDP account
  {Colors.BOLD}•{Colors.ENDC}  Enable multi-factor authentication on Tailscale
     {Colors.DIM}tailscale.com → Settings → Two-factor authentication{Colors.ENDC}
  {Colors.BOLD}•{Colors.ENDC}  Run the Security Check tool periodically (desktop shortcut)
     {Colors.DIM}to verify firewall rules remain intact{Colors.ENDC}
  {Colors.BOLD}•{Colors.ENDC}  Keep your server patched:  sudo apt upgrade

{Colors.FAIL}{Colors.BOLD}╔══════════════════════════════════════════════════════════════╗
║       !! ACTION REQUIRED: TAILSCALE KEY EXPIRY !!            ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Tailscale keys expire after 180 days by default.           ║
║  When your key expires you will be LOCKED OUT of your        ║
║  VPS with no way to reconnect remotely.                      ║
║                                                              ║
║  Disable key expiry NOW — takes 30 seconds:                  ║
║                                                              ║
║  1. Go to: https://login.tailscale.com/admin/machines        ║
║  2. Find this server and click the  ···  menu                ║
║  3. Click "Disable key expiry"                               ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝{Colors.ENDC}

{Colors.CYAN}Next Steps:{Colors.ENDC}
1. {Colors.BOLD}Disable Tailscale key expiry{Colors.ENDC} (see above — do this first!)
2. Connect via RDP: {tailscale_ip}:3389
3. Open a terminal and run: {Colors.BOLD}openclaw onboard{Colors.ENDC}
   {Colors.DIM}This completes the OpenClaw onboarding (API keys, preferences, etc.){Colors.ENDC}
4. OpenClaw will then continue running as a background service automatically
5. Google Chrome is available on your desktop

{Colors.GREEN}Setup logs saved to: /var/log/vps_post_setup.log{Colors.ENDC}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        
        print(report)
        
        # Save detailed log
        with open("/var/log/vps_post_setup.log", "w") as f:
            f.write("VPS Post-Lockdown Setup Log\n")
            f.write("=" * 50 + "\n\n")
            for entry in self.setup_log:
                f.write(entry + "\n")
            f.write("\n" + "=" * 50 + "\n")
            f.write("Setup completed successfully!\n")

    def run_post_setup(self):
        """Main post-lockdown setup orchestrator"""
        print(f"{Colors.HEADER}{Colors.BOLD}")
        print("=" * 60)
        print("    Post-Lockdown Setup Continuation")
        print("=" * 60)
        print(f"{Colors.ENDC}")
        
        try:
            if not self.verify_tailscale_connection():
                print(f"{Colors.FAIL}Tailscale connection could not be verified!{Colors.ENDC}")
                print(f"{Colors.WARNING}Continuing anyway, but please verify your connection.{Colors.ENDC}")
            
            self.configure_hostname()
            self.test_lockdown_status()
            self.install_openclaw()
            self.install_homebrew()
            self.install_chrome()
            self.install_chrome_cleanup()
            self.install_security_check()
            self.install_openclaw_widget()
            self.create_user_shortcuts()
            self.create_final_report()
            
            print(f"\n{Colors.GREEN}{Colors.BOLD}All setup tasks completed successfully!{Colors.ENDC}")
            
        except KeyboardInterrupt:
            print(f"\n{Colors.WARNING}Setup interrupted by user{Colors.ENDC}")
            sys.exit(1)
        except Exception as e:
            self.log(f"Post-setup failed: {str(e)}", "ERROR")
            print(f"\n{Colors.FAIL}Setup encountered an error. Check logs for details.{Colors.ENDC}")
            sys.exit(1)

def main():
    if os.geteuid() != 0:
        print(f"{Colors.FAIL}This script must be run as root (use sudo){Colors.ENDC}")
        sys.exit(1)
    
    setup = PostLockdownSetup()
    setup.run_post_setup()

if __name__ == "__main__":
    main()
