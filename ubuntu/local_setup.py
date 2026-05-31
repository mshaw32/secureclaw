#!/usr/bin/env python3
"""
Local Ubuntu 24.04 LTS Setup Script
For physically-present desktop installs — configures xrdp, Tailscale,
security lockdown, and installs OpenClaw + Chrome.

Handles GNOME (Ubuntu default) and XFCE desktop environments.
All setup runs in a single phase — no SSH disconnect or reconnect required.

Author: Brandon
"""

import os
import sys
import subprocess
import time
import pwd
import json
import shlex
import shutil
import re
import secrets
import string
import getpass
from pathlib import Path

STATE_FILE = "/var/lib/local-setup/state.json"


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
    HEADER  = '\033[95m'
    BLUE    = '\033[94m'
    CYAN    = '\033[96m'
    GREEN   = '\033[92m'
    WARNING = '\033[93m'
    FAIL    = '\033[91m'
    ENDC    = '\033[0m'
    BOLD    = '\033[1m'
    DIM     = '\033[2m'


class LocalUbuntuSetup:

    def __init__(self):
        self.setup_log    = []
        self.desktop_type = None   # 'gnome', 'xfce'  — set during setup
        self.install_user = None   # set during select_install_user
        self.tailscale_ip = None   # set during configure_tailscale

        # Restore any persisted state from a previous (interrupted) run
        state = self._load_state()
        self.desktop_type = state.get("desktop_type")
        self.install_user = state.get("install_user")
        self.tailscale_ip = state.get("tailscale_ip")

    # ── State management ──────────────────────────────────────────────────────

    def _load_state(self):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_state(self, **kwargs):
        state = self._load_state()
        state.update(kwargs)
        Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

    def _step_done(self, step):
        return self._load_state().get(step, False)

    # ── Logging ───────────────────────────────────────────────────────────────

    def log(self, message, level="INFO"):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {level}: {message}"
        self.setup_log.append(entry)
        if level == "ERROR":
            print(f"{Colors.FAIL}{entry}{Colors.ENDC}")
        elif level == "WARNING":
            print(f"{Colors.WARNING}{entry}{Colors.ENDC}")
        elif level == "SUCCESS":
            print(f"{Colors.GREEN}{entry}{Colors.ENDC}")
        else:
            print(f"{Colors.CYAN}{entry}{Colors.ENDC}")

    # ── Shell helper ──────────────────────────────────────────────────────────

    def run_command(self, command, check=True, shell=True, capture_output=True):
        try:
            self.log(f"Executing: {command}")
            result = subprocess.run(
                command, shell=shell, check=check,
                capture_output=capture_output, text=True
            )
            if capture_output and result.stdout:
                self.log(f"Output: {result.stdout.strip()}")
            return result
        except subprocess.CalledProcessError as e:
            self.log(f"Command failed: {command}", "ERROR")
            if capture_output and e.stderr:
                self.log(f"Error: {e.stderr.strip()}", "ERROR")
            raise

    def run_as_login_user(self, username, command, check=True, capture_output=True):
        quoted_user = shlex.quote(username)
        quoted_command = shlex.quote(command)
        if shutil.which("runuser"):
            wrapper = f"runuser -l {quoted_user} -c {quoted_command}"
        else:
            wrapper = f"su - {quoted_user} -c {quoted_command}"
        return self.run_command(wrapper, check=check, capture_output=capture_output)

    def get_openclaw_install_status(self, username):
        result = self.run_as_login_user(
            username,
            "export PATH=/home/$(id -un)/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; "
            "command -v openclaw",
            check=False,
        )
        return result.returncode == 0

    def get_user_input(self, message, options, default_index=0):
        print(f"\n{Colors.CYAN}{message}{Colors.ENDC}")
        for i, option in enumerate(options):
            marker = f"{Colors.DIM} (default){Colors.ENDC}" if i == default_index else ""
            print(f"  {i + 1}. {option}{marker}")
        while True:
            try:
                choice = input(f"\nEnter choice (1-{len(options)}): ").strip()
                if not choice:
                    return default_index
                idx = int(choice) - 1
                if 0 <= idx < len(options):
                    return idx
                print(f"{Colors.WARNING}Please enter a number between 1 and {len(options)}{Colors.ENDC}")
            except (ValueError, KeyboardInterrupt):
                print(f"{Colors.WARNING}Invalid input.{Colors.ENDC}")

    # ── OS helpers ────────────────────────────────────────────────────────────

    def get_os_codename(self):
        try:
            r = subprocess.run(
                "lsb_release -cs", shell=True, capture_output=True, text=True, check=True
            )
            return r.stdout.strip()
        except Exception:
            return "noble"  # 24.04 fallback

    def find_service(self, *candidates):
        for name in candidates:
            r = subprocess.run(
                f"systemctl list-unit-files {name}.service 2>/dev/null | grep -q {name}",
                shell=True, capture_output=True
            )
            if r.returncode == 0:
                return name
        return candidates[0]

    def service_command(self, action, *candidates):
        svc = self.find_service(*candidates)
        self.run_command(f"systemctl {action} {svc}")

    # ── Setup steps ───────────────────────────────────────────────────────────

    def update_system(self):
        if self._step_done("system_updated"):
            self.log("System update already completed — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== SYSTEM UPDATE ==={Colors.ENDC}")
        self.run_command("apt-get update", capture_output=False)
        self.run_command("apt-get upgrade -y", capture_output=False)
        # Include openssh-server — not installed by default on Ubuntu Desktop
        self.run_command(
            "apt-get install -y curl wget gnupg2 software-properties-common "
            "python3-tk openssh-server",
            capture_output=False
        )
        self.log("System update completed", "SUCCESS")
        self._save_state(system_updated=True)

    def detect_and_record_desktop(self):
        """Detect the existing desktop environment. Install XFCE if none found."""
        if self._step_done("desktop_detected"):
            self.log(f"Desktop already detected ({self.desktop_type}) — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== DESKTOP DETECTION ==={Colors.ENDC}")

        # GNOME
        r = self.run_command(
            "dpkg -l gnome-shell 2>/dev/null | grep '^ii' || "
            "dpkg -l gdm3 2>/dev/null | grep '^ii'",
            check=False
        )
        if r.returncode == 0:
            self.desktop_type = "gnome"
            self.log("Detected: GNOME desktop", "SUCCESS")
            self._save_state(desktop_detected=True, desktop_type="gnome")
            return

        # XFCE
        r = self.run_command("dpkg -l xfce4-session 2>/dev/null | grep '^ii'", check=False)
        if r.returncode == 0:
            self.desktop_type = "xfce"
            self.log("Detected: XFCE desktop", "SUCCESS")
            self._save_state(desktop_detected=True, desktop_type="xfce")
            return

        # Nothing found — install XFCE
        self.log("No desktop environment found — installing XFCE + LightDM", "WARNING")
        self.run_command(
            "apt-get install -y xfce4 xfce4-goodies lightdm", capture_output=False
        )
        Path("/etc/lightdm").mkdir(parents=True, exist_ok=True)
        with open("/etc/lightdm/lightdm.conf", "w") as f:
            f.write("[Seat:*]\nWaylandEnable=false\nuser-session=xfce\n")
        self.service_command("enable", "lightdm")
        self.desktop_type = "xfce"
        self.log("XFCE desktop installed", "SUCCESS")
        self._save_state(desktop_detected=True, desktop_type="xfce")

    def setup_xrdp(self):
        """Install xrdp and configure it for the detected desktop type."""
        if self._step_done("xrdp_configured"):
            self.log("xrdp already configured — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== XRDP SETUP ==={Colors.ENDC}")

        r = self.run_command("dpkg -l xrdp 2>/dev/null | grep '^ii'", check=False)
        if r.returncode != 0:
            self.log("Installing xrdp...")
            self.run_command("apt-get install -y xrdp", capture_output=False)

        # Needed to avoid TLS certificate errors in xrdp sessions
        self.run_command("adduser xrdp ssl-cert", check=False)

        if self.desktop_type == "gnome":
            self._configure_xrdp_for_gnome()
        else:
            self._configure_xrdp_for_xfce()

        self.service_command("enable", "xrdp")
        self.service_command("restart", "xrdp")
        self.log("xrdp configured and started", "SUCCESS")
        self._save_state(xrdp_configured=True)

    def _configure_xrdp_for_gnome(self):
        """
        Three-step GNOME + xrdp fix for Ubuntu 24.04:
          1. Disable Wayland in GDM3 (xrdp requires an X11 session)
          2. Write a polkit rule so the colour-manager auth popup never appears
          3. Configure startwm.sh to launch gnome-session
        """
        # 1. Disable Wayland in GDM3
        gdm3_conf = Path("/etc/gdm3/custom.conf")
        if gdm3_conf.exists():
            text = gdm3_conf.read_text()
            if "WaylandEnable=false" not in text:
                # Uncomment the existing commented line if present
                text = re.sub(r"#\s*WaylandEnable\s*=\s*false", "WaylandEnable=false", text)
                # Otherwise inject under [daemon]
                if "WaylandEnable=false" not in text:
                    text = text.replace("[daemon]", "[daemon]\nWaylandEnable=false", 1)
                gdm3_conf.write_text(text)
                self.log("Disabled Wayland in GDM3 (/etc/gdm3/custom.conf)", "SUCCESS")
            else:
                self.log("Wayland already disabled in GDM3", "SUCCESS")
        else:
            # Create a minimal gdm3 config if it doesn't exist
            gdm3_conf.parent.mkdir(parents=True, exist_ok=True)
            gdm3_conf.write_text("[daemon]\nWaylandEnable=false\n")
            self.log("Created /etc/gdm3/custom.conf with Wayland disabled", "SUCCESS")

        # 2. Polkit rule — prevents colour-manager auth dialogs in every xrdp session
        polkit_rule = """\
polkit.addRule(function(action, subject) {
    if ((action.id == "org.freedesktop.color-manager.create-device"  ||
         action.id == "org.freedesktop.color-manager.create-profile" ||
         action.id == "org.freedesktop.color-manager.delete-device"  ||
         action.id == "org.freedesktop.color-manager.delete-profile" ||
         action.id == "org.freedesktop.color-manager.modify-device"  ||
         action.id == "org.freedesktop.color-manager.modify-profile") &&
        subject.isInGroup("sudo")) {
        return polkit.Result.YES;
    }
});
"""
        polkit_dir = Path("/etc/polkit-1/rules.d")
        polkit_dir.mkdir(parents=True, exist_ok=True)
        (polkit_dir / "45-allow-colord.rules").write_text(polkit_rule)
        self.log("Polkit colour-manager rule written", "SUCCESS")

        # 3. startwm.sh — launch a GNOME-on-X11 session
        startwm_path = Path("/etc/xrdp/startwm.sh")
        if startwm_path.exists():
            backup = Path("/etc/xrdp/startwm.sh.pre-local-setup")
            if not backup.exists():
                backup.write_text(startwm_path.read_text())
                self.log("Backed up original startwm.sh", "SUCCESS")

        startwm_path.write_text(
            "#!/bin/sh\n"
            "unset DBUS_SESSION_BUS_ADDRESS\n"
            "unset XDG_RUNTIME_DIR\n"
            "exec gnome-session\n"
        )
        os.chmod(startwm_path, 0o755)
        self.log("xrdp startwm.sh configured for GNOME", "SUCCESS")

    def _configure_xrdp_for_xfce(self):
        """Disable sleep/screensaver for XFCE xrdp sessions."""
        # Do NOT touch startwm.sh — the default xrdp behaviour of reading
        # ~/.xsession works correctly and matches what the VPS setup does.

        # Disable sleep/screensaver so xrdp sessions don't blank
        xfconf_dir = Path("/etc/xdg/xfce4/xfconf/xfce-perchannel-xml")
        xfconf_dir.mkdir(parents=True, exist_ok=True)

        power_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-power-manager" version="1.0">
  <property name="xfce4-power-manager" type="empty">
    <property name="inactivity-sleep-mode-on-ac" type="uint" value="0"/>
    <property name="blank-on-ac" type="int" value="0"/>
    <property name="dpms-on-ac-sleep" type="uint" value="0"/>
    <property name="dpms-on-ac-off" type="uint" value="0"/>
  </property>
</channel>"""

        screensaver_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-screensaver" version="1.0">
  <property name="saver" type="empty">
    <property name="enabled" type="bool" value="false"/>
    <property name="lock-enabled" type="bool" value="false"/>
  </property>
</channel>"""

        (xfconf_dir / "xfce4-power-manager.xml").write_text(power_xml)
        (xfconf_dir / "xfce4-screensaver.xml").write_text(screensaver_xml)
        self.log("XFCE power/screensaver configured for xrdp sessions", "SUCCESS")

    def select_install_user(self):
        """
        Choose which user OpenClaw, Chrome shortcuts, and the widget are installed for.
        On a local install the primary user almost always already exists.
        """
        if self._step_done("user_selected"):
            self.log(f"Install user already set to '{self.install_user}' — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== SELECT INSTALL USER ==={Colors.ENDC}")

        existing = sorted(d.name for d in _real_user_homes())

        if len(existing) == 1:
            user = existing[0]
            print(f"\n{Colors.CYAN}Found existing user: {Colors.BOLD}{user}{Colors.ENDC}")
            choice = self.get_user_input(
                "Install OpenClaw and desktop tools for this user?",
                [f"Yes — use {user}", "Create a new user instead"],
                default_index=0
            )
            if choice == 0:
                self.install_user = user
                self.run_command(f"usermod -aG sudo {user}", check=False)
                self._write_xsession(user)
                self._save_state(user_selected=True, install_user=user)
                self.log(f"Using existing user: {user}", "SUCCESS")
                return

        elif len(existing) > 1:
            options = existing + ["Create a new user"]
            choice = self.get_user_input(
                "Multiple users found. Which user should OpenClaw be installed for?",
                options
            )
            if choice < len(existing):
                self.install_user = existing[choice]
                self._write_xsession(self.install_user)
                self._save_state(user_selected=True, install_user=self.install_user)
                self.log(f"Using existing user: {self.install_user}", "SUCCESS")
                return

        self._create_new_user()

    def _create_new_user(self):
        """Create a new local user."""
        while True:
            username = input(f"\n{Colors.CYAN}Enter new username: {Colors.ENDC}").strip()
            if not username:
                print(f"{Colors.WARNING}Username cannot be empty.{Colors.ENDC}")
                continue
            if not re.match(r'^[a-zA-Z0-9_-]+$', username):
                print(f"{Colors.WARNING}Letters, digits, underscores, and hyphens only.{Colors.ENDC}")
                continue
            r = self.run_command(f"id {username}", check=False)
            if r.returncode == 0:
                print(f"{Colors.WARNING}User '{username}' already exists.{Colors.ENDC}")
                choice = self.get_user_input(
                    "Use this existing user?",
                    ["Yes, use existing", "Pick a different name"],
                    default_index=0
                )
                if choice == 0:
                    self.install_user = username
                    self._write_xsession(username)
                    self._save_state(user_selected=True, install_user=username)
                    return
                continue
            break

        # Generate a readable password (exclude visually ambiguous chars)
        safe_chars = (
            [c for c in string.ascii_uppercase if c not in 'OI'] +
            [c for c in string.ascii_lowercase if c not in 'l'] +
            [c for c in string.digits if c not in '01']
        )
        password = ''.join(secrets.choice(safe_chars) for _ in range(16))

        box_inner = max(44, len(username) + 16, len(password) + 16) - 2
        sep = "═" * box_inner
        def bl(s): return f"║ {s:<{box_inner - 2}} ║"
        lines = [
            f"╔{sep}╗", bl("NEW USER CREDENTIALS"), bl(""),
            bl(f"  USERNAME: {username}"), bl(f"  PASSWORD: {password}"), bl(""),
            bl("  Save this password before continuing!"), f"╚{sep}╝"
        ]
        print(f"\n{Colors.GREEN}{Colors.BOLD}" + "\n".join(lines) + f"{Colors.ENDC}\n")
        input(f"{Colors.CYAN}Press Enter once you have saved the credentials...{Colors.ENDC}")

        try:
            self.run_command(f"useradd -m -s /bin/bash -G sudo,audio,video,input {username}")
        except subprocess.CalledProcessError:
            self.run_command(f"useradd -m -s /bin/bash -G sudo,audio,video {username}")

        cp = subprocess.run(['chpasswd'], input=f"{username}:{password}", text=True, capture_output=True)
        if cp.returncode != 0:
            self.log(f"Failed to set password: {cp.stderr}", "ERROR")
            raise subprocess.CalledProcessError(cp.returncode, 'chpasswd')

        self.install_user = username
        self._write_xsession(username)
        self.log(f"User '{username}' created", "SUCCESS")
        self._save_state(user_selected=True, install_user=username)

    def _write_xsession(self, username):
        """Write a desktop-appropriate .xsession for the user's xrdp sessions."""
        xsession_path = Path(f"/home/{username}/.xsession")
        if self.desktop_type == "gnome":
            content = (
                "#!/bin/bash\n"
                "unset DBUS_SESSION_BUS_ADDRESS\n"
                "unset XDG_RUNTIME_DIR\n"
                "exec gnome-session\n"
            )
        else:
            content = "#!/bin/bash\nexec xfce4-session\n"

        xsession_path.write_text(content)
        self.run_command(f"chown {username}:{username} {xsession_path}")
        self.run_command(f"chmod 755 {xsession_path}")
        self.log(f"Written .xsession ({self.desktop_type}) for {username}", "SUCCESS")

    # ── Tailscale ─────────────────────────────────────────────────────────────

    def install_tailscale(self):
        if self._step_done("tailscale_installed"):
            self.log("Tailscale already installed — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== TAILSCALE INSTALLATION ==={Colors.ENDC}")

        r = self.run_command("which tailscale", check=False)
        if r.returncode == 0:
            self.log("Tailscale binary already present — skipping install", "SUCCESS")
            self._save_state(tailscale_installed=True)
            return

        codename = self.get_os_codename()
        self.run_command(
            f"curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/{codename}.noarmor.gpg "
            f"| tee /usr/share/keyrings/tailscale-archive-keyring.gpg > /dev/null"
        )
        self.run_command(
            f"curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/{codename}.tailscale-keyring.list "
            f"| tee /etc/apt/sources.list.d/tailscale.list"
        )
        self.run_command("apt-get update")
        self.run_command("apt-get install -y tailscale")
        self.log("Tailscale installed", "SUCCESS")
        self._save_state(tailscale_installed=True)

    def configure_tailscale(self):
        r = self.run_command("tailscale status", check=False)
        if r.returncode == 0 and self.tailscale_ip:
            self.log(f"Tailscale already authenticated (IP: {self.tailscale_ip}) — skipping", "SUCCESS")
            return True

        print(f"\n{Colors.HEADER}=== TAILSCALE CONFIGURATION ==={Colors.ENDC}")

        print(f"""
{Colors.BOLD}Why Tailscale?{Colors.ENDC}
{Colors.CYAN}  Tailscale creates a private encrypted network between your devices.
  Once configured, you can RDP into this machine from anywhere using
  its Tailscale IP — no open firewall ports, no public exposure.{Colors.ENDC}

{Colors.WARNING}  You need a free Tailscale account to continue.
  Create one at tailscale.com if you don't have one yet.{Colors.ENDC}
""")

        proceed = self.get_user_input(
            "Ready to authenticate with Tailscale?",
            ["Yes, I have an account — continue", "I need to create an account first", "Skip Tailscale"],
            default_index=0
        )

        if proceed == 1:
            print(f"\n{Colors.CYAN}  Go to https://tailscale.com and create your free account.{Colors.ENDC}")
            input(f"{Colors.WARNING}  Press Enter when your account is ready...{Colors.ENDC}")
            proceed = self.get_user_input(
                "Ready to authenticate?",
                ["Yes, authenticate now", "Skip Tailscale"],
                default_index=0
            )
            if proceed == 1:
                self.log("Tailscale skipped by user", "WARNING")
                return False

        if proceed == 2:
            self.log("Tailscale skipped by user", "WARNING")
            return False

        try:
            self.run_command("tailscale up", capture_output=False)
        except subprocess.CalledProcessError:
            self.log("Tailscale authentication may have failed", "WARNING")
            retry = self.get_user_input(
                "What would you like to do?",
                ["Retry with reset", "Continue without Tailscale", "Exit setup"],
                default_index=0
            )
            if retry == 0:
                self.run_command("tailscale up --reset", capture_output=False)
            elif retry == 1:
                return False
            else:
                sys.exit(0)

        time.sleep(5)
        try:
            r = self.run_command("tailscale ip -4")
            self.tailscale_ip = r.stdout.strip()
            self.log(f"Tailscale IP: {self.tailscale_ip}", "SUCCESS")
            self._save_state(tailscale_configured=True, tailscale_ip=self.tailscale_ip)
            return True
        except Exception:
            self.log("Failed to get Tailscale IP", "ERROR")
            return False

    # ── Firewall ──────────────────────────────────────────────────────────────

    def lockdown_server(self):
        """
        Apply UFW rules restricting SSH and RDP to Tailscale-only access.

        Differs from the VPS lockdown in two ways:
          - No countdown / SSH-disconnect drama — you're sitting at the machine
          - SSH ListenAddress is NOT bound to the Tailscale IP so local LAN
            SSH access still works if the user ever needs it
        """
        if self._step_done("server_locked_down"):
            self.log("Firewall lockdown already applied — skipping", "SUCCESS")
            return True

        print(f"\n{Colors.HEADER}=== FIREWALL LOCKDOWN ==={Colors.ENDC}")

        print(f"""
{Colors.CYAN}This will configure UFW so that SSH (22) and RDP (3389) connections
are only accepted from your Tailscale network. Direct internet access
to those ports will be blocked.

You can still use this machine locally at any time — the firewall
only affects incoming network connections.{Colors.ENDC}
""")

        confirm = self.get_user_input(
            "Apply Tailscale-only firewall rules?",
            ["Yes, apply firewall rules", "Skip (not recommended)"],
            default_index=0
        )
        if confirm == 1:
            self.log("Firewall lockdown skipped by user", "WARNING")
            return True  # non-fatal — continue setup

        self.log("Applying firewall rules...")

        # Ensure IPv6 filtering is enabled
        self.run_command("sed -i 's/^IPV6=no/IPV6=yes/' /etc/default/ufw", check=False)
        r = self.run_command("grep -c '^IPV6=' /etc/default/ufw", check=False)
        if r.stdout.strip() == "0":
            self.run_command("echo 'IPV6=yes' >> /etc/default/ufw")

        self.run_command("ufw --force reset")
        self.run_command("ufw default deny incoming")
        self.run_command("ufw default allow outgoing")
        self.run_command("ufw allow in on tailscale0")
        self.run_command("ufw allow out on tailscale0")

        for subnet in ("100.64.0.0/10", "fd7a:115c:a1e0::/48"):
            self.run_command(f"ufw allow from {subnet} to any port 22")
            self.run_command(f"ufw allow from {subnet} to any port 3389")

        self.run_command("ufw --force enable")
        self.log("Firewall locked down to Tailscale-only access", "SUCCESS")
        self._save_state(server_locked_down=True)
        return True

    # ── Applications ──────────────────────────────────────────────────────────

    def install_openclaw(self):
        if self._step_done("openclaw_installed"):
            self.log("OpenClaw already installed — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== OPENCLAW AI INSTALLATION ==={Colors.ENDC}")

        if not self.install_user:
            self.log("No install user set — skipping OpenClaw", "WARNING")
            return

        # Remove legacy system service if left over from an old install
        legacy = Path("/etc/systemd/system/openclaw.service")
        if legacy.exists():
            self.run_command("systemctl stop openclaw", check=False)
            self.run_command("systemctl disable openclaw", check=False)
            legacy.unlink()
            self.run_command("systemctl daemon-reload")
            self.log("Removed legacy openclaw system service", "SUCCESS")

        # Pre-install Node.js as root so the official installer doesn't need
        # sudo internally (fails without a TTY in a su subprocess)
        self.log("Installing Node.js and build tools...")
        print(f"\n  {Colors.WARNING}{Colors.BOLD}⚠  Note:{Colors.ENDC}{Colors.WARNING} This step can take 2–3 minutes and may appear to hang.{Colors.ENDC}")
        print(f"  {Colors.WARNING}   If progress stops, press Enter a few times to continue.{Colors.ENDC}\n")
        self.run_command("curl -fsSL https://deb.nodesource.com/setup_22.x | bash -")
        self.run_command(
            "apt-get install -y "
            "git curl wget sudo "
            "nodejs build-essential cmake make g++ python3 "
            "ca-certificates"
        )

        # Keep the official streamed installer path, but set PATH explicitly so
        # LXC/container login shells can see root-installed prerequisites.
        self.log("Running official OpenClaw installer...")
        install_command = (
            "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; "
            "for cmd in git curl sudo node npm bash; do "
            "command -v \"$cmd\" >/dev/null || { echo \"Missing dependency in user PATH: $cmd\" >&2; exit 1; }; "
            "done; "
            "curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard"
        )
        self.run_command(
            f"su - {shlex.quote(self.install_user)} -c {shlex.quote(install_command)}",
            capture_output=False,
        )

        # Enable linger so the user's systemd services survive without an active session
        self.run_command(f"loginctl enable-linger {self.install_user}")
        self.log("OpenClaw installed", "SUCCESS")
        self._save_state(openclaw_installed=True)

    def install_homebrew(self):
        """Pre-install Homebrew so OpenClaw skills install correctly during onboarding"""
        if self._step_done("homebrew_installed"):
            self.log("Homebrew already installed — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== HOMEBREW INSTALLATION ==={Colors.ENDC}")
        if not self.install_user:
            self.log("No install user set — skipping Homebrew", "WARNING")
            return

        # Check if already present for this user
        result = self.run_command(
            f"su - {self.install_user} -c 'command -v brew'", check=False
        )
        if result.returncode == 0:
            self.log("Homebrew already present — skipping", "SUCCESS")
            self._save_state(homebrew_installed=True)
            return

        self.log("Installing Homebrew (required for OpenClaw skills)...")
        # Extra deps Homebrew needs on Linux beyond what we already installed
        self.run_command("apt-get install -y -qq file procps")

        # Pre-create the Homebrew prefix as root and give the user ownership
        # so the installer doesn't need sudo to create /home/linuxbrew
        self.run_command("mkdir -p /home/linuxbrew/.linuxbrew")
        self.run_command(f"chown -R {self.install_user}:{self.install_user} /home/linuxbrew")

        # Download installer as root, run it as the target user
        self.run_command(
            "curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh "
            "-o /tmp/brew_install.sh"
        )
        self.run_command(
            f"su - {self.install_user} -c 'NONINTERACTIVE=1 bash /tmp/brew_install.sh'",
            capture_output=False
        )
        self.run_command("rm -f /tmp/brew_install.sh", check=False)

        # Add brew to the user's shell profile so it's on PATH after login
        brew_env = 'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"'
        for rc in [f"/home/{self.install_user}/.bashrc", f"/home/{self.install_user}/.profile"]:
            self.run_command(
                f"grep -qF 'linuxbrew' {rc} || echo '{brew_env}' >> {rc}",
                check=False
            )

        self.log("Homebrew installed", "SUCCESS")
        self._save_state(homebrew_installed=True)

    def install_chrome(self):
        if self._step_done("chrome_installed"):
            self.log("Chrome already installed — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== GOOGLE CHROME INSTALLATION ==={Colors.ENDC}")

        r = self.run_command("dpkg -l | grep google-chrome", check=False)
        if r.returncode == 0:
            self.log("Chrome already installed", "SUCCESS")
            self._save_state(chrome_installed=True)
            return

        try:
            self.run_command(
                "wget -q -O /tmp/chrome.deb "
                "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"
            )
            self.run_command("apt-get install -y /tmp/chrome.deb")
            self.run_command("rm -f /tmp/chrome.deb")
        except subprocess.CalledProcessError:
            self.log("Fallback: installing Chrome via repository...", "WARNING")
            self.run_command(
                "wget -q -O /usr/share/keyrings/google-chrome.gpg "
                "https://dl.google.com/linux/linux_signing_key.pub"
            )
            self.run_command(
                'echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] '
                'http://dl.google.com/linux/chrome/deb/ stable main" '
                '> /etc/apt/sources.list.d/google-chrome.list'
            )
            self.run_command("apt-get update")
            self.run_command("apt-get install -y google-chrome-stable")

        r = self.run_command("google-chrome --version")
        self.log(f"Chrome installed: {r.stdout.strip()}", "SUCCESS")
        self._save_state(chrome_installed=True)

    def install_chrome_cleanup(self):
        if self._step_done("chrome_cleanup_installed"):
            self.log("Chrome cleanup already installed — skipping", "SUCCESS")
            return

        if not self.install_user:
            return

        print(f"\n{Colors.HEADER}=== CHROME STORAGE CLEANUP ==={Colors.ENDC}")

        chrome_dir = f"/home/{self.install_user}/.config/google-chrome"

        cleanup_script = f"""\
#!/bin/bash
# Chrome storage cleanup — trims safe cache dirs when total exceeds 1 GB
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

        service = f"""\
[Unit]
Description=Chrome Storage Cleanup

[Service]
Type=oneshot
User={self.install_user}
ExecStart=/usr/local/bin/chrome-cleanup
"""
        timer = """\
[Unit]
Description=Chrome Storage Cleanup Timer

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
"""
        with open("/etc/systemd/system/chrome-cleanup.service", "w") as f:
            f.write(service)
        with open("/etc/systemd/system/chrome-cleanup.timer", "w") as f:
            f.write(timer)

        self.run_command("systemctl daemon-reload")
        self.run_command("systemctl enable chrome-cleanup.timer")
        self.run_command("systemctl start chrome-cleanup.timer")
        self.log("Chrome cleanup timer installed (runs daily)", "SUCCESS")
        self._save_state(chrome_cleanup_installed=True)

    def install_security_check(self):
        if self._step_done("security_check_installed"):
            self.log("Security check already installed — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== SECURITY CHECK TOOL ==={Colors.ENDC}")

        # The security-check script itself is identical to the VPS version
        security_script = r"""#!/bin/bash
# SecureClaw Security Verification

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
FIX_UFW=0; FIX_UFW6=0; FIX_TS_RULE=0; FIX_SSH_RULE=0; FIX_RDP_RULE=0
RESTART_SVCS=()

clear
echo
echo -e "${BOLD}  ╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}  ║        🦞  SecureClaw Security Verification                 ║${RESET}"
echo -e "${BOLD}  ║        $(date '+%Y-%m-%d %H:%M:%S')                                 ║${RESET}"
echo -e "${BOLD}  ╚══════════════════════════════════════════════════════════════╝${RESET}"

section "Firewall (UFW)"
ufw_out=$(ufw status verbose 2>/dev/null)
if echo "$ufw_out" | grep -q "Status: active"; then
    pass "UFW is active"
else
    fail "UFW is NOT active — machine is unprotected!"; FIX_UFW=1
fi
if grep -q "^IPV6=yes" /etc/default/ufw 2>/dev/null; then
    pass "UFW IPv6 filtering is enabled"
else
    fail "UFW IPv6 filtering is disabled"; FIX_UFW6=1
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

section "Tailscale VPN"
ts_ip=$(tailscale ip -4 2>/dev/null)
if [ -n "$ts_ip" ]; then
    pass "Connected — Tailscale IP: $ts_ip"
else
    fail "Tailscale is not connected!"
    info "Run: sudo tailscale up"
fi

section "SSH (port 22)"
ssh_listen=$(ss -tlnp 2>/dev/null | grep ':22 ')
if [ -n "$ssh_listen" ]; then
    if echo "$ssh_listen" | grep -qE "0\.0\.0\.0:22|\*:22|:::22"; then
        if [ "$FIX_UFW" -eq 0 ] && [ "$FIX_SSH_RULE" -eq 0 ]; then
            pass "SSH listening on all interfaces — restricted by UFW to Tailscale subnet only"
        else
            warn "SSH is listening on all interfaces and UFW rules need attention"
        fi
    else
        pass "SSH is bound to restricted interface only"
    fi
else
    warn "SSH does not appear to be listening"
fi

section "RDP (port 3389)"
rdp_listen=$(ss -tlnp 2>/dev/null | grep ':3389 ')
if [ -n "$rdp_listen" ]; then
    pass "XRDP is listening on port 3389"
    info "Protected by UFW — only reachable via Tailscale (100.64.0.0/10)"
else
    warn "XRDP does not appear to be listening on 3389"
fi

section "OpenClaw"
oc_user=""
while IFS=: read -r user _ uid _ _ home _; do
    if [ "$uid" -ge 1000 ] && [[ "$home" == /home/* ]] && \
       runuser -l "$user" -c 'export PATH=/home/$(id -un)/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; command -v openclaw >/dev/null' 2>/dev/null; then
        oc_user="$user"
        break
    fi
done < /etc/passwd
if [ -n "$oc_user" ]; then
    pass "OpenClaw CLI is installed for $oc_user"
else
    warn "OpenClaw CLI is not installed"
fi

section "Services"
for svc in xrdp tailscaled chrome-cleanup.timer; do
    if systemctl is-active --quiet "$svc"; then
        pass "$svc is running"
    else
        warn "$svc is not active"; RESTART_SVCS+=("$svc")
    fi
done

echo
echo -e "  ${DIM}──────────────────────────────────────────────────────────────${RESET}"
echo
if [ "$ISSUES" -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}  ✓  All checks passed — system is properly secured.${RESET}"
    echo
    read -rp "  Press Enter to close..."
    exit 0
fi

echo -e "  ${RED}${BOLD}  ✗  $ISSUES issue(s) found — review the output above.${RESET}"
echo

fixable=$((FIX_UFW + FIX_UFW6 + FIX_TS_RULE + FIX_SSH_RULE + FIX_RDP_RULE + ${#RESTART_SVCS[@]}))
if [ "$fixable" -gt 0 ]; then
    echo -e "  ${CYAN}${BOLD}$fixable issue(s) can be fixed automatically:${RESET}"
    [ "$FIX_UFW"      -eq 1 ] && echo -e "    ${YELLOW}→${RESET}  Enable UFW"
    [ "$FIX_UFW6"     -eq 1 ] && echo -e "    ${YELLOW}→${RESET}  Enable UFW IPv6 filtering"
    [ "$FIX_TS_RULE"  -eq 1 ] && echo -e "    ${YELLOW}→${RESET}  Add Tailscale interface rule"
    [ "$FIX_SSH_RULE" -eq 1 ] && echo -e "    ${YELLOW}→${RESET}  Restrict SSH to Tailscale subnets"
    [ "$FIX_RDP_RULE" -eq 1 ] && echo -e "    ${YELLOW}→${RESET}  Restrict RDP to Tailscale subnets"
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
        [ "$FIX_UFW"  -eq 1 ] && { ufw --force enable && fix_ok "UFW enabled" || fix_err "Failed to enable UFW"; ufw_changed=1; }
        [ "$FIX_UFW6" -eq 1 ] && { sed -i 's/^IPV6=no/IPV6=yes/' /etc/default/ufw; grep -q '^IPV6=' /etc/default/ufw || echo 'IPV6=yes' >> /etc/default/ufw; fix_ok "UFW IPv6 enabled"; ufw_changed=1; }
        [ "$FIX_TS_RULE" -eq 1 ] && { ufw allow in on tailscale0 && ufw allow out on tailscale0 && fix_ok "Tailscale rules added" || fix_err "Failed"; ufw_changed=1; }
        if [ "$FIX_SSH_RULE" -eq 1 ]; then
            ufw delete allow 22/tcp 2>/dev/null || true
            ufw delete allow 22 2>/dev/null || true
            ufw delete allow OpenSSH 2>/dev/null || true
            ufw allow from 100.64.0.0/10 to any port 22 proto tcp && \
            ufw allow from fd7a:115c:a1e0::/48 to any port 22 proto tcp && \
                fix_ok "SSH restricted to Tailscale" || fix_err "Failed"
            ufw_changed=1
        fi
        if [ "$FIX_RDP_RULE" -eq 1 ]; then
            ufw delete allow 3389/tcp 2>/dev/null || true
            ufw delete allow 3389 2>/dev/null || true
            ufw allow from 100.64.0.0/10 to any port 3389 proto tcp && \
            ufw allow from fd7a:115c:a1e0::/48 to any port 3389 proto tcp && \
                fix_ok "RDP restricted to Tailscale" || fix_err "Failed"
            ufw_changed=1
        fi
        [ "$ufw_changed" -eq 1 ] && { ufw --force reload && fix_ok "UFW reloaded" || fix_err "UFW reload failed"; }
        for svc in "${RESTART_SVCS[@]}"; do
            systemctl enable --now "$svc" 2>/dev/null && fix_ok "$svc started" || fix_err "Could not start $svc"
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
            f.write(security_script)
        os.chmod("/usr/local/bin/security-check", 0o755)

        # Terminal-agnostic launcher — xfce4-terminal won't exist on GNOME systems
        launcher = """\
#!/bin/bash
# Launch security-check in the best available terminal emulator
if command -v xfce4-terminal &>/dev/null; then
    exec xfce4-terminal --title="SecureClaw Security Check" -e /usr/local/bin/security-check
elif command -v gnome-terminal &>/dev/null; then
    exec gnome-terminal --title="SecureClaw Security Check" -- /usr/local/bin/security-check
elif command -v x-terminal-emulator &>/dev/null; then
    exec x-terminal-emulator -e /usr/local/bin/security-check
else
    exec xterm -title "SecureClaw Security Check" -e /usr/local/bin/security-check
fi
"""
        with open("/usr/local/bin/launch-security-check", "w") as f:
            f.write(launcher)
        os.chmod("/usr/local/bin/launch-security-check", 0o755)

        # Desktop entry uses the launcher wrapper, not xfce4-terminal directly
        desktop_entry = """\
[Desktop Entry]
Version=1.0
Type=Application
Name=Security Check
Comment=Verify firewall and security settings
Exec=/usr/local/bin/launch-security-check
Icon=security-high
Terminal=false
Categories=System;Security;
"""
        for user_dir in _real_user_homes():
            username = user_dir.name
            desktop_dir = user_dir / "Desktop"
            desktop_dir.mkdir(exist_ok=True)
            shortcut = desktop_dir / "security-check.desktop"
            shortcut.write_text(desktop_entry)
            self.run_command(f"chown {username}:{username} {shortcut}")
            self.run_command(f"chmod +x {shortcut}")
            self.log(f"Created Security Check shortcut for {username}", "SUCCESS")

        self.log("Security check tool installed", "SUCCESS")
        self._save_state(security_check_installed=True)

    def _get_repo_branch(self):
        """Which GitHub branch to pull assets (widget script) from."""
        # install.sh exports this; also honoured if set manually
        env_branch = os.environ.get("SECURECLAW_BRANCH", "")
        if env_branch in ("main", "dev"):
            return env_branch
        # Fallback: try to detect from git if running from a repo checkout
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True,
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            branch = r.stdout.strip()
            if branch in ("main", "dev"):
                return branch
        except Exception:
            pass
        return "main"

    def install_openclaw_widget(self):
        if self._step_done("widget_installed"):
            self.log("OpenClaw widget already installed — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== OPENCLAW CONTROL PANEL ==={Colors.ENDC}")

        branch = self._get_repo_branch()
        self.log(f"Using branch: {branch}")

        raw_base = f"https://raw.githubusercontent.com/mshaw32/secureclaw/{branch}"
        install_bin = "/usr/local/bin/openclaw-widget"

        self.run_command(f"wget -q -O {install_bin} {raw_base}/ubuntu/openclaw_widget.py")
        os.chmod(install_bin, 0o755)
        self.run_command(
            f"sed -i 's/^REPO_BRANCH_OVERRIDE = None.*$/REPO_BRANCH_OVERRIDE = \"{branch}\"/' {install_bin}"
        )

        self.run_command("apt-get install -y python3-gi gir1.2-gtk-3.0")

        sudoers_content = (
            "# Allow sudo group to check UFW status without password (used by openclaw-widget)\n"
            "%sudo ALL=(ALL) NOPASSWD: /usr/sbin/ufw status\n"
        )
        sudoers_path = "/etc/sudoers.d/openclaw-widget"
        with open(sudoers_path, "w") as f:
            f.write(sudoers_content)
        os.chmod(sudoers_path, 0o440)

        app_dir = Path("/usr/local/share/applications")
        app_dir.mkdir(parents=True, exist_ok=True)
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
        (app_dir / "openclaw-widget.desktop").write_text(desktop_content)

        for user_dir in _real_user_homes():
            username = user_dir.name

            autostart_dir = user_dir / ".config" / "autostart"
            autostart_dir.mkdir(parents=True, exist_ok=True)
            (autostart_dir / "openclaw-widget.desktop").write_text(desktop_content)
            self.run_command(f"chown -R {username}:{username} {autostart_dir}")

            user_desktop = user_dir / "Desktop"
            user_desktop.mkdir(exist_ok=True)
            shortcut = user_desktop / "openclaw-widget.desktop"
            shortcut.write_text(desktop_content)
            self.run_command(f"chmod +x {shortcut}")
            self.run_command(f"chown {username}:{username} {shortcut}")
            self.log(f"Autostart + desktop shortcut created for {username}", "SUCCESS")

        self.log("OpenClaw Control Panel installed", "SUCCESS")
        self._save_state(widget_installed=True)

    def create_user_shortcuts(self):
        if self._step_done("shortcuts_created"):
            self.log("Shortcuts already created — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== USER SHORTCUTS ==={Colors.ENDC}")

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

        for user_dir in _real_user_homes():
            username = user_dir.name
            desktop_dir = user_dir / "Desktop"
            desktop_dir.mkdir(exist_ok=True)

            chrome_src = Path("/usr/share/applications/google-chrome.desktop")
            if chrome_src.exists():
                dst = desktop_dir / "google-chrome.desktop"
                self.run_command(f"cp {chrome_src} {dst}")
                self.run_command(f"chown {username}:{username} {dst}")
                self.run_command(f"chmod +x {dst}")
                self.log(f"Created Chrome shortcut for {username}", "SUCCESS")

            for sc in url_shortcuts:
                content = (
                    f"[Desktop Entry]\nVersion=1.0\nType=Link\n"
                    f"Name={sc['name']}\nURL={sc['url']}\nIcon={sc['icon']}\n"
                )
                shortcut = desktop_dir / sc["filename"]
                shortcut.write_text(content)
                self.run_command(f"chown {username}:{username} {shortcut}")
                self.run_command(f"chmod +x {shortcut}")
                self.log(f"Created {sc['name']} shortcut for {username}", "SUCCESS")

            # Show hidden files in Thunar (XFCE only — Nautilus has its own setting)
            if self.desktop_type == "xfce":
                thunar_dir = user_dir / ".config" / "Thunar"
                thunar_dir.mkdir(parents=True, exist_ok=True)
                thunar_conf = thunar_dir / "thunarrc"
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
                self.run_command(f"chown -R {username}:{username} {thunar_dir}")

        if self.install_user:
            self.run_command(
                f"su - {self.install_user} -c 'xdg-user-dirs-update'", check=False
            )

        self.log("User shortcuts created", "SUCCESS")
        self._save_state(shortcuts_created=True)

    # ── Final report ──────────────────────────────────────────────────────────

    def create_final_report(self):
        print(f"\n{Colors.HEADER}=== SETUP COMPLETE ==={Colors.ENDC}")

        tailscale_ip = self.tailscale_ip or "Not configured"
        try:
            r = self.run_command("tailscale ip -4")
            tailscale_ip = r.stdout.strip()
        except Exception:
            pass

        try:
            r = self.run_command("google-chrome --version")
            chrome_ver = r.stdout.strip()
        except Exception:
            chrome_ver = "Installation failed"

        try:
            if self.install_user and self.get_openclaw_install_status(self.install_user):
                oc_status = "Installed"
            else:
                oc_status = "Installation failed"
        except Exception:
            oc_status = "Unknown"

        report = f"""
{Colors.GREEN}{Colors.BOLD}LOCAL UBUNTU SETUP COMPLETED!{Colors.ENDC}

{Colors.CYAN}Summary:{Colors.ENDC}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{Colors.BOLD}Desktop:{Colors.ENDC}       {self.desktop_type or 'unknown'}
{Colors.BOLD}Install User:{Colors.ENDC}  {self.install_user or 'unknown'}
{Colors.BOLD}Tailscale IP:{Colors.ENDC}  {tailscale_ip}

{Colors.BOLD}Installed:{Colors.ENDC}
• xrdp (remote desktop server)
• OpenClaw AI: {oc_status}
• Google Chrome: {chrome_ver}

{Colors.FAIL}{Colors.BOLD}╔══════════════════════════════════════════════════════════════╗
║       !! ACTION REQUIRED: TAILSCALE KEY EXPIRY !!            ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Tailscale keys expire after 180 days by default.           ║
║  When your key expires you will be locked out of remote      ║
║  access with no way to reconnect.                            ║
║                                                              ║
║  Disable key expiry NOW — takes 30 seconds:                  ║
║  1. Go to: https://login.tailscale.com/admin/machines        ║
║  2. Find this machine and click the  ···  menu               ║
║  3. Click "Disable key expiry"                               ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝{Colors.ENDC}

{Colors.CYAN}Next Steps:{Colors.ENDC}
1. {Colors.BOLD}Disable Tailscale key expiry{Colors.ENDC} (see above — do this first!)
2. Install Tailscale on your other devices (tailscale.com/download)
   Sign in with the same account to reach this machine remotely
3. Run OpenClaw onboarding: {Colors.BOLD}openclaw onboard{Colors.ENDC}
4. RDP into this machine from any Tailscale device:
   Address: {Colors.BOLD}{tailscale_ip}:3389{Colors.ENDC}

{Colors.GREEN}Setup log saved to: /var/log/local_setup.log{Colors.ENDC}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        print(report)

        with open("/var/log/local_setup.log", "w") as f:
            f.write("Local Ubuntu Setup Log\n" + "=" * 50 + "\n\n")
            for entry in self.setup_log:
                f.write(entry + "\n")

    # ── Orchestrator ──────────────────────────────────────────────────────────

    def run_setup(self):
        print(f"{Colors.HEADER}{Colors.BOLD}")
        print("=" * 60)
        print("    SecureClaw Local Ubuntu 24.04 Setup")
        print("=" * 60)
        print(f"{Colors.ENDC}")

        print(f"{Colors.CYAN}This script will:{Colors.ENDC}")
        print("  • Configure xrdp for remote desktop access")
        print("  • Install and authenticate Tailscale VPN")
        print("  • Apply Tailscale-only firewall rules")
        print("  • Install OpenClaw AI and Google Chrome")
        print("  • Set up desktop shortcuts and the Control Panel widget")
        print()

        if os.geteuid() != 0:
            print(f"{Colors.FAIL}This script must be run as root (use sudo){Colors.ENDC}")
            sys.exit(1)

        # Suppress interactive apt/debconf prompts (e.g. display-manager selection)
        os.environ.setdefault("DEBIAN_FRONTEND", "noninteractive")

        # Ensure stdin is connected to the terminal even when the installer was
        # piped in (e.g. curl … | sudo bash), which would leave stdin at EOF.
        try:
            sys.stdin = open("/dev/tty", "r")
        except OSError:
            pass  # Non-TTY environments (containers, CI) — proceed without

        # Show resume state from a previous run
        state = self._load_state()
        completed = [
            k for k, v in state.items()
            if v and k not in ("desktop_type", "install_user", "tailscale_ip")
        ]
        if completed:
            print(f"\n{Colors.GREEN}Resuming — steps already completed:{Colors.ENDC}")
            for step in completed:
                print(f"  {Colors.GREEN}✓{Colors.ENDC}  {step.replace('_', ' ').title()}")
            print()

        try:
            self.update_system()
            self.detect_and_record_desktop()
            self.setup_xrdp()
            self.select_install_user()
            self.install_tailscale()

            if self.configure_tailscale():
                self.lockdown_server()
            else:
                print(f"{Colors.WARNING}Continuing without Tailscale / firewall lockdown.{Colors.ENDC}")

            self.install_openclaw()
            self.install_homebrew()
            self.install_chrome()
            self.install_chrome_cleanup()
            self.install_security_check()
            self.install_openclaw_widget()
            self.create_user_shortcuts()
            self.create_final_report()

            print(f"\n{Colors.GREEN}{Colors.BOLD}All setup tasks completed!{Colors.ENDC}\n")

        except KeyboardInterrupt:
            print(f"\n{Colors.WARNING}Setup interrupted. Re-run to resume.{Colors.ENDC}")
            sys.exit(1)
        except Exception as e:
            self.log(f"Setup failed: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            print(f"\n{Colors.FAIL}Setup encountered an error. Re-run to resume from the last completed step.{Colors.ENDC}")
            sys.exit(1)


def main():
    setup = LocalUbuntuSetup()
    setup.run_setup()


if __name__ == "__main__":
    main()
