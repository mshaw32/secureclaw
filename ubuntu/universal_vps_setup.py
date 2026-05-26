#!/usr/bin/env python3
"""
Universal Ubuntu VPS Setup Script
Handles both SSH and RDP initial access scenarios
Configures RDP, Tailscale, security lockdown, and installs OpenClaw + Chrome
Author: Brandon
"""

import os
import sys
import subprocess
import time
import pwd
import json
from pathlib import Path
import getpass
import tkinter as tk
from tkinter import messagebox, simpledialog
import threading
import secrets
import string
import re

STATE_FILE = "/var/lib/vps-setup/state.json"

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
    """Terminal colors for better UX"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

class UniversalVPSSetup:
    def __init__(self):
        self.setup_log = []
        self.os_info = self._detect_os_info()
        self.is_desktop_env = self.detect_desktop_environment()
        self.gui_available = self.is_desktop_env and self.check_display()
        self.initial_access_method = self.detect_access_method()

        # Restore persisted state so re-runs skip completed steps
        state = self._load_state()
        self.desktop_type = state.get("desktop_type")
        self.rdp_username = state.get("rdp_username")
        self.tailscale_ip = state.get("tailscale_ip")

    # ── State management ──────────────────────────────────────────────────────

    def _load_state(self):
        """Load setup progress from disk"""
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_state(self, **kwargs):
        """Persist setup progress to disk"""
        state = self._load_state()
        state.update(kwargs)
        Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

    def _step_done(self, step):
        """Return True if a step has already been completed"""
        return self._load_state().get(step, False)

    # ── OS / service helpers ──────────────────────────────────────────────────

    def _detect_os_info(self):
        """Read /etc/os-release and return a dict of OS metadata"""
        info = {}
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        k, _, v = line.partition("=")
                        info[k] = v.strip('"')
        except Exception:
            pass
        return info

    def find_service(self, *candidates):
        """Return the first service name that exists on this system.
        Falls back to the first candidate if none are found."""
        for name in candidates:
            result = subprocess.run(
                f"systemctl list-unit-files {name}.service 2>/dev/null | grep -q {name}",
                shell=True, capture_output=True
            )
            if result.returncode == 0:
                return name
        return candidates[0]

    def service_command(self, action, *candidates):
        """Run a systemctl action against the first matching service name"""
        service = self.find_service(*candidates)
        self.run_command(f"systemctl {action} {service}")

    # ── Environment detection ─────────────────────────────────────────────────

    def detect_desktop_environment(self):
        """Detect if we're running in a desktop environment"""
        # DISPLAY is deliberately excluded — SSH X11 forwarding sets it on
        # headless servers and produces false positives
        desktop_indicators = [
            'DESKTOP_SESSION',
            'GDMSESSION',
            'XDG_CURRENT_DESKTOP',
        ]

        for indicator in desktop_indicators:
            if os.environ.get(indicator):
                return True

        if os.environ.get('WAYLAND_DISPLAY'):
            return True

        # Only treat X11 unix sockets as proof of a running desktop —
        # the directory itself can exist on bare Ubuntu without any X server
        if os.path.exists('/tmp/.X11-unix'):
            try:
                if any(os.scandir('/tmp/.X11-unix')):
                    return True
            except Exception:
                pass

        return False

    def check_display(self):
        """Check if GUI display is available"""
        try:
            root = tk.Tk()
            root.withdraw()
            return True
        except:
            return False

    def get_os_codename(self):
        """Get the Ubuntu OS codename for repository setup"""
        try:
            result = subprocess.run("lsb_release -cs", shell=True, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except Exception:
            return "jammy"  # fallback to 22.04

    def detect_access_method(self):
        """Detect how the user is accessing the system"""
        # Check current environment first
        if os.environ.get('SSH_CLIENT') or os.environ.get('SSH_CONNECTION'):
            return "SSH"

        # sudo strips SSH_* vars — walk up the process tree to find them
        try:
            pid = os.getpid()
            visited = set()
            while pid > 1 and pid not in visited:
                visited.add(pid)
                try:
                    with open(f'/proc/{pid}/environ', 'rb') as f:
                        for var in f.read().split(b'\x00'):
                            if var.startswith((b'SSH_CLIENT=', b'SSH_CONNECTION=')):
                                return "SSH"
                    with open(f'/proc/{pid}/status') as f:
                        for line in f:
                            if line.startswith('PPid:'):
                                pid = int(line.split()[1])
                                break
                except (PermissionError, FileNotFoundError):
                    break
        except Exception:
            pass

        if self.is_desktop_env:
            return "RDP"
        return "CONSOLE"

    # ── Logging ───────────────────────────────────────────────────────────────

    def log(self, message, level="INFO"):
        """Log messages with timestamps and optional GUI display"""
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

        if self.gui_available and level in ["ERROR", "WARNING", "SUCCESS"] and self.initial_access_method == "RDP":
            try:
                root = tk.Tk()
                root.withdraw()
                if level == "ERROR":
                    messagebox.showerror("Setup Error", message)
                elif level == "WARNING":
                    messagebox.showwarning("Setup Warning", message)
                elif level == "SUCCESS":
                    messagebox.showinfo("Setup Success", message)
                root.destroy()
            except:
                pass

    # ── UI helpers ────────────────────────────────────────────────────────────

    def show_startup_message(self):
        """Display appropriate startup message based on access method"""
        print(f"{Colors.HEADER}{Colors.BOLD}")
        print("=" * 70)
        print("        Universal Ubuntu VPS Interactive Setup")
        print("=" * 70)
        print(f"{Colors.ENDC}")

        os_name = self.os_info.get("PRETTY_NAME", "Unknown OS")
        state = self._load_state()
        completed = [k for k, v in state.items() if v and not k.startswith(("desktop_type", "rdp_username", "tailscale_ip"))]

        print(f"{Colors.CYAN}Detected Environment:{Colors.ENDC}")
        print(f"  • OS: {Colors.BOLD}{os_name}{Colors.ENDC}")
        print(f"  • Access Method: {Colors.BOLD}{self.initial_access_method}{Colors.ENDC}")
        print(f"  • Desktop Environment: {Colors.BOLD}{'Yes' if self.is_desktop_env else 'No'}{Colors.ENDC}")
        print(f"  • GUI Available: {Colors.BOLD}{'Yes' if self.gui_available else 'No'}{Colors.ENDC}")

        if completed:
            print(f"\n{Colors.GREEN}Resuming — steps already completed:{Colors.ENDC}")
            for step in completed:
                print(f"  {Colors.GREEN}✓{Colors.ENDC}  {step.replace('_', ' ').title()}")

        if self.initial_access_method == "RDP":
            print(f"\n{Colors.GREEN}RDP Mode Detected:{Colors.ENDC}")
            print("  • You're already connected via RDP")
            print("  • Script will enhance your current RDP setup")
            print("  • GUI notifications will be shown during setup")

            if self.gui_available:
                try:
                    root = tk.Tk()
                    root.withdraw()
                    result = messagebox.askyesno(
                        "VPS Setup",
                        "Welcome to Ubuntu VPS Setup!\n\n"
                        "Detected: You're connected via RDP\n\n"
                        "This script will:\n"
                        "• Enhance RDP with session persistence\n"
                        "• Install and configure Tailscale VPN\n"
                        "• Lock down server security\n"
                        "• Install OpenClaw and Chrome\n\n"
                        "Continue with setup?"
                    )
                    root.destroy()
                    if not result:
                        self.log("Setup cancelled by user", "WARNING")
                        sys.exit(0)
                except:
                    pass

        elif self.initial_access_method == "SSH":
            print(f"\n{Colors.GREEN}SSH Mode Detected:{Colors.ENDC}")
            print("  • You're connected via SSH")
            print("  • Script will install and configure RDP server")
            print("  • You'll test RDP before server lockdown")

        print(f"\n{Colors.CYAN}{Colors.BOLD}  Security Architecture{Colors.ENDC}")
        print(f"  {Colors.DIM}──────────────────────────────────────────────────────────────{Colors.ENDC}")
        print(f"  This setup hardens your VPS using two complementary layers of")
        print(f"  network security — but it is not a complete security solution")
        print(f"  on its own. Understanding what it does and does not cover is")
        print(f"  important.")
        print()
        print(f"  {Colors.BOLD}Tailscale VPN{Colors.ENDC}")
        print(f"  All remote access (SSH and RDP) is routed exclusively through")
        print(f"  Tailscale — a zero-config VPN built on the WireGuard protocol.")
        print(f"  Tailscale is SOC 2 Type II certified, end-to-end encrypted,")
        print(f"  and participates in regular independent third-party security")
        print(f"  audits. Direct public internet access to SSH and RDP is blocked.")
        print()
        print(f"  {Colors.BOLD}UFW Firewall{Colors.ENDC}")
        print(f"  Ubuntu's firewall is configured to deny all inbound connections")
        print(f"  by default, with access permitted only from the Tailscale subnet")
        print(f"  (100.64.0.0/10). This eliminates direct internet exposure of")
        print(f"  your remote access services.")
        print()
        print(f"  {Colors.WARNING}These controls substantially reduce your attack surface, but")
        print(f"  defense in depth still matters. We strongly recommend:{Colors.ENDC}")
        print(f"  {Colors.BOLD}•{Colors.ENDC}  Use a strong, unique password for your RDP account")
        print(f"  {Colors.BOLD}•{Colors.ENDC}  Enable multi-factor authentication on your Tailscale account")
        print(f"     {Colors.DIM}tailscale.com → Settings → Two-factor authentication{Colors.ENDC}")
        print(f"  {Colors.BOLD}•{Colors.ENDC}  Periodically run the Security Check tool (desktop shortcut)")
        print(f"     {Colors.DIM}to verify firewall rules are still intact{Colors.ENDC}")
        print(f"  {Colors.BOLD}•{Colors.ENDC}  Keep your server patched:  sudo apt upgrade")
        print(f"  {Colors.DIM}──────────────────────────────────────────────────────────────{Colors.ENDC}")
        print(f"\n  {Colors.WARNING}Note:{Colors.ENDC}  Have a Tailscale account ready before continuing.")
        print(f"        Create a free account at tailscale.com if you don't have one.")

    def show_gui_progress(self, title, message):
        """Show a progress window for long-running operations"""
        if not self.gui_available:
            return

        def show_progress():
            try:
                progress_window = tk.Tk()
                progress_window.title(title)
                progress_window.geometry("400x150")
                progress_window.resizable(False, False)

                progress_window.update_idletasks()
                x = (progress_window.winfo_screenwidth() // 2) - (400 // 2)
                y = (progress_window.winfo_screenheight() // 2) - (150 // 2)
                progress_window.geometry(f"400x150+{x}+{y}")

                label = tk.Label(progress_window, text=message, wraplength=350)
                label.pack(pady=20)

                progress_window.after(5000, progress_window.destroy)
                progress_window.mainloop()
            except:
                pass

        thread = threading.Thread(target=show_progress)
        thread.daemon = True
        thread.start()

    def get_user_input(self, message, options, default_index=0):
        """Get user input via GUI or console based on environment"""
        if self.gui_available and self.initial_access_method == "RDP":
            try:
                root = tk.Tk()
                root.withdraw()

                dialog = tk.Toplevel()
                dialog.title("Setup Choice")
                dialog.geometry("500x200")
                dialog.resizable(False, False)

                dialog.update_idletasks()
                x = (dialog.winfo_screenwidth() // 2) - (500 // 2)
                y = (dialog.winfo_screenheight() // 2) - (200 // 2)
                dialog.geometry(f"500x200+{x}+{y}")

                result = [default_index]

                tk.Label(dialog, text=message, wraplength=450).pack(pady=20)

                button_frame = tk.Frame(dialog)
                button_frame.pack(pady=10)

                for i, option in enumerate(options):
                    btn = tk.Button(
                        button_frame,
                        text=option,
                        command=lambda idx=i: [result.__setitem__(0, idx), dialog.destroy()]
                    )
                    btn.pack(side=tk.LEFT, padx=10)

                dialog.wait_window()
                root.destroy()
                return result[0]

            except:
                pass

        print(f"\n{Colors.CYAN}{message}{Colors.ENDC}")
        for i, option in enumerate(options):
            print(f"  {i+1}. {option}")

        while True:
            try:
                choice = input(f"\nEnter choice (1-{len(options)}) [default: {default_index+1}]: ").strip()
                if not choice:
                    return default_index
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(options):
                    return choice_idx
                else:
                    print(f"{Colors.WARNING}Please enter a number between 1 and {len(options)}{Colors.ENDC}")
            except (ValueError, KeyboardInterrupt):
                print(f"{Colors.WARNING}Invalid input. Please enter a number.{Colors.ENDC}")

    # ── Setup steps ───────────────────────────────────────────────────────────

    def run_command(self, command, check=True, shell=True, capture_output=True):
        """Execute shell commands with proper error handling"""
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

    def check_root(self):
        """Ensure script is run with root privileges"""
        if os.geteuid() != 0:
            error_msg = "This script must be run as root (use sudo)"
            self.log(error_msg, "ERROR")

            if self.gui_available and self.initial_access_method == "RDP":
                try:
                    root = tk.Tk()
                    root.withdraw()
                    messagebox.showerror(
                        "Root Access Required",
                        f"{error_msg}\n\nPlease run from terminal:\nsudo python3 {sys.argv[0]}"
                    )
                    root.destroy()
                except:
                    pass

            sys.exit(1)
        self.log("Root privileges confirmed", "SUCCESS")

    def update_system(self):
        """Update package lists and upgrade system"""
        if self._step_done("system_updated"):
            self.log("System update already completed — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== SYSTEM UPDATE ==={Colors.ENDC}")
        self.log("Starting system update...")

        if self.gui_available and self.initial_access_method == "RDP":
            self.show_gui_progress("Updating system packages...", "This may take several minutes")

        self.run_command("apt update", capture_output=False)
        self.run_command("apt upgrade -y", capture_output=False)
        self.run_command("apt install -y curl wget gnupg2 software-properties-common python3-tk")

        self.log("System update completed", "SUCCESS")
        self._save_state(system_updated=True)

    def detect_and_setup_desktop(self):
        """Detect installed desktop environment and install one if absent"""
        if self._step_done("desktop_setup"):
            self.log(f"Desktop setup already completed ({self.desktop_type}) — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== DESKTOP ENVIRONMENT DETECTION ==={Colors.ENDC}")

        result = self.run_command("dpkg -l xfce4-session 2>/dev/null | grep '^ii'", check=False)
        if result.returncode == 0:
            detected = "xfce"
        else:
            result = self.run_command(
                "dpkg -l gnome-shell 2>/dev/null | grep '^ii' || dpkg -l gdm3 2>/dev/null | grep '^ii'",
                check=False
            )
            detected = "gnome" if result.returncode == 0 else "none"

        if detected == "none":
            self.log("No desktop environment found — installing XFCE + LightDM + xrdp...", "WARNING")
            self.run_command("apt install -y xfce4 xfce4-goodies lightdm xrdp", capture_output=False)

            Path("/etc/lightdm").mkdir(parents=True, exist_ok=True)
            with open("/etc/lightdm/lightdm.conf", "w") as f:
                f.write("[Seat:*]\nWaylandEnable=false\nuser-session=xfce\n")

            self.service_command("enable", "lightdm")
            self.service_command("enable", "xrdp")
            detected = "xfce"
            self.log("XFCE desktop environment installed", "SUCCESS")
        else:
            self.log(f"Detected desktop environment: {detected}", "SUCCESS")

            result = self.run_command("dpkg -l xrdp 2>/dev/null | grep '^ii'", check=False)
            if result.returncode != 0:
                self.log("xrdp not found on existing desktop — installing xrdp only...", "WARNING")
                self.run_command("apt install -y xrdp", capture_output=False)
                self.service_command("enable", "xrdp")

        self.desktop_type = detected
        self.log(f"Desktop type set to: {self.desktop_type}", "SUCCESS")
        self._save_state(desktop_setup=True, desktop_type=detected)

    def create_rdp_user(self):
        """Create a dedicated RDP user with a generated password"""
        if self._step_done("rdp_user_created"):
            self.log(f"RDP user '{self.rdp_username}' already created — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== RDP USER CREATION ==={Colors.ENDC}")

        while True:
            username = None
            if self.gui_available:
                try:
                    root = tk.Tk()
                    root.withdraw()
                    username = simpledialog.askstring(
                        "RDP User",
                        "Enter username for RDP access:",
                        parent=root
                    )
                    root.destroy()
                except:
                    username = None

            if username is None:
                username = input(f"\n{Colors.CYAN}Enter username for RDP access: {Colors.ENDC}").strip()

            if not username:
                print(f"{Colors.WARNING}Username cannot be empty.{Colors.ENDC}")
                continue

            if not re.match(r'^[a-zA-Z0-9_-]+$', username):
                print(f"{Colors.WARNING}Username may only contain letters, digits, underscores, and hyphens.{Colors.ENDC}")
                continue

            result = self.run_command(f"id {username}", check=False)
            if result.returncode == 0:
                self.log(f"User '{username}' already exists", "WARNING")
                choice = self.get_user_input(
                    f"User '{username}' already exists. What would you like to do?",
                    ["Use existing user", "Pick a different name", "Exit setup"],
                    default_index=0
                )
                if choice == 0:
                    self.rdp_username = username
                    self.run_command(f"usermod -aG sudo {username}", check=False)
                    self.log(f"Using existing user: {username} (ensured sudo membership)", "SUCCESS")
                    self._save_state(rdp_user_created=True, rdp_username=username)
                    return
                elif choice == 1:
                    continue
                else:
                    sys.exit(0)

            break

        # Generate secure 16-char password (exclude ambiguous chars: 0, O, I, l, 1)
        safe_chars = (
            [c for c in string.ascii_uppercase if c not in 'OI'] +
            [c for c in string.ascii_lowercase if c not in 'l'] +
            [c for c in string.digits if c not in '01']
        )
        generated_password = ''.join(secrets.choice(safe_chars) for _ in range(16))

        def show_cred_box(uname, pwd, extra_line=None):
            box_width = max(44, len(uname) + 16, len(pwd) + 16)
            inner = box_width - 2
            sep = "═" * inner
            def bl(content):
                return f"║ {content:<{inner - 2}} ║"
            lines = [
                f"╔{sep}╗",
                bl("RDP LOGIN CREDENTIALS"),
                bl(""),
                bl(f"  USERNAME: {uname}"),
                bl(f"  PASSWORD: {pwd}"),
                bl(""),
            ]
            if extra_line:
                lines.append(bl(extra_line))
            lines.append(f"╚{sep}╝")
            print(f"\n{Colors.GREEN}{Colors.BOLD}" + "\n".join(lines) + f"{Colors.ENDC}\n")

        show_cred_box(username, generated_password, "  Save this password before continuing!")

        pwd_choice = self.get_user_input(
            "Would you like to use this generated password or set your own?",
            ["Use generated password", "Set my own password"],
            default_index=0
        )

        if pwd_choice == 1:
            max_attempts = 3
            attempt = 0
            password = None
            while attempt < max_attempts:
                attempt += 1
                pwd1 = getpass.getpass(f"\n{Colors.CYAN}Enter your password: {Colors.ENDC}")
                if not pwd1:
                    print(f"{Colors.WARNING}Password cannot be empty.{Colors.ENDC}")
                    attempt -= 1  # don't count empty entry as an attempt
                    continue
                pwd2 = getpass.getpass(f"{Colors.CYAN}Confirm your password: {Colors.ENDC}")
                if pwd1 != pwd2:
                    remaining = max_attempts - attempt
                    if remaining > 0:
                        print(f"{Colors.WARNING}Passwords do not match. {remaining} attempt(s) remaining.{Colors.ENDC}")
                    continue
                password = pwd1
                break

            if password is None:
                print(f"{Colors.WARNING}Passwords did not match after {max_attempts} attempts — using the generated password instead.{Colors.ENDC}")
                password = generated_password

            show_cred_box(username, password, "  Save this password before continuing!")
        else:
            password = generated_password

        try:
            self.run_command(f"useradd -m -s /bin/bash -G sudo,audio,video,input {username}")
        except subprocess.CalledProcessError:
            self.log("'input' group not found, retrying without it...", "WARNING")
            self.run_command(f"useradd -m -s /bin/bash -G sudo,audio,video {username}")

        cp_result = subprocess.run(
            ['chpasswd'],
            input=f"{username}:{password}",
            text=True,
            capture_output=True
        )
        if cp_result.returncode != 0:
            self.log(f"Failed to set password: {cp_result.stderr}", "ERROR")
            raise subprocess.CalledProcessError(cp_result.returncode, 'chpasswd')

        xsession_path = f"/home/{username}/.xsession"
        with open(xsession_path, "w") as f:
            f.write("#!/bin/bash\nexec xfce4-session\n")
        self.run_command(f"chown {username}:{username} {xsession_path}")
        self.run_command(f"chmod 755 {xsession_path}")

        print(f"{Colors.WARNING}{Colors.BOLD}  Make sure you have saved your username and password!{Colors.ENDC}")
        input(f"{Colors.CYAN}  Press Enter once you have saved your credentials to continue...{Colors.ENDC}")
        print()

        if self.gui_available:
            try:
                root = tk.Tk()
                root.withdraw()
                messagebox.showinfo(
                    "RDP Credentials — SAVE THESE",
                    f"RDP Login Credentials\n\n"
                    f"Username: {username}\n"
                    f"Password: {password}\n\n"
                    f"You will need these to connect via RDP."
                )
                root.destroy()
            except:
                pass

        self.rdp_username = username
        self.log(f"RDP user '{username}' created successfully", "SUCCESS")
        self._save_state(rdp_user_created=True, rdp_username=username)

    def configure_rdp_persistence(self):
        """Ensure xrdp is installed and configured for session persistence."""
        if self._step_done("rdp_configured"):
            self.log("RDP persistence already configured — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== RDP SESSION PERSISTENCE ==={Colors.ENDC}")

        changes_made = []
        needs_xrdp_restart = False

        result = self.run_command("dpkg -l xrdp 2>/dev/null | grep '^ii'", check=False)
        if result.returncode != 0:
            self.log("xrdp not found, installing...")
            if self.gui_available:
                self.show_gui_progress("Installing xrdp", "Setting up remote desktop server...")
            self.run_command("apt install -y xrdp", capture_output=False)
            needs_xrdp_restart = True
            changes_made.append("xrdp installed")
        else:
            self.log("xrdp is already installed", "SUCCESS")

        xrdp_ini_path = "/etc/xrdp/xrdp.ini"
        try:
            with open(xrdp_ini_path, "r") as f:
                xrdp_config = f.read()

            if "[Xorg]" in xrdp_config and "libxup.so" in xrdp_config:
                self.log("xrdp Xorg persistence module is already configured", "SUCCESS")
            else:
                self.log("Xorg persistence module missing from xrdp config, adding it...")
                self.run_command(f"cp {xrdp_ini_path} {xrdp_ini_path}.backup")
                xorg_block = """
[Xorg]
name=Xorg
lib=libxup.so
username=ask
password=ask
ip=127.0.0.1
port=-1
code=20
"""
                with open(xrdp_ini_path, "a") as f:
                    f.write(xorg_block)
                needs_xrdp_restart = True
                changes_made.append("xrdp Xorg persistence module added")

        except FileNotFoundError:
            self.log("xrdp.ini not found - xrdp may not have installed correctly", "ERROR")

        self.log("Checking session idle/sleep/lock settings...")
        if self.desktop_type == "xfce":
            self._configure_xfce_persistence()
        elif self.desktop_type == "gnome":
            self._configure_gnome_persistence()
        else:
            self.log("Unknown desktop type — skipping sleep/lock config", "WARNING")

        self.run_command("ufw allow 3389/tcp", check=False)

        if not changes_made:
            self.log("RDP session persistence is already properly configured - no changes needed", "SUCCESS")
        else:
            self.log(f"Changes applied: {', '.join(changes_made)}", "SUCCESS")

        if needs_xrdp_restart:
            self.service_command("enable", "xrdp")

            if self.initial_access_method == "RDP":
                warning = (
                    "xrdp configuration was updated and needs to restart.\n\n"
                    "Your RDP session will briefly disconnect.\n"
                    "Reconnect in a few seconds to continue setup."
                )
                if self.gui_available:
                    try:
                        root = tk.Tk()
                        root.withdraw()
                        messagebox.showwarning("Brief Disconnection Required", warning)
                        root.destroy()
                    except Exception:
                        pass

                print(f"\n{Colors.WARNING}{'=' * 60}{Colors.ENDC}")
                print(f"{Colors.WARNING}xrdp restart required — you will briefly disconnect!{Colors.ENDC}")
                print(f"{Colors.WARNING}Reconnect within 30 seconds to continue.{Colors.ENDC}")
                print(f"{Colors.WARNING}{'=' * 60}{Colors.ENDC}")
                time.sleep(5)

            self.service_command("restart", "xrdp")
            self.log("xrdp restarted with persistence configuration", "SUCCESS")

        self._save_state(rdp_configured=True)

    def _configure_xfce_persistence(self):
        """Write idempotent XFCE xfconf XML files to disable sleep, DPMS, and screen lock"""
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

        power_file = xfconf_dir / "xfce4-power-manager.xml"
        screensaver_file = xfconf_dir / "xfce4-screensaver.xml"
        changes = []

        existing_power = power_file.read_text() if power_file.exists() else ""
        if existing_power.strip() == power_xml.strip():
            self.log("XFCE power manager already configured", "SUCCESS")
        else:
            power_file.write_text(power_xml)
            changes.append("power manager")

        existing_screensaver = screensaver_file.read_text() if screensaver_file.exists() else ""
        if existing_screensaver.strip() == screensaver_xml.strip():
            self.log("XFCE screensaver already configured", "SUCCESS")
        else:
            screensaver_file.write_text(screensaver_xml)
            changes.append("screensaver")

        if changes:
            self.log(f"XFCE persistence configured: {', '.join(changes)}", "SUCCESS")
        else:
            self.log("XFCE session persistence already configured — no changes needed", "SUCCESS")

    def _configure_gnome_persistence(self):
        """Disable GNOME sleep and screen lock via dconf system-wide policy"""
        self.log("Checking GNOME session idle/sleep/lock settings...")
        dconf_dir = Path("/etc/dconf/db/local.d")
        dconf_dir.mkdir(parents=True, exist_ok=True)

        dconf_config = """\
[org/gnome/desktop/session]
idle-delay=uint32 0

[org/gnome/settings-daemon/plugins/power]
sleep-inactive-ac-timeout=0
sleep-inactive-battery-timeout=0
power-button-action='nothing'

[org/gnome/desktop/screensaver]
lock-enabled=false
"""
        dconf_file = dconf_dir / "00-rdp-persistence"
        existing = dconf_file.read_text() if dconf_file.exists() else ""

        if existing.strip() == dconf_config.strip():
            self.log("Session persistence (no sleep/lock) already configured", "SUCCESS")
        else:
            dconf_file.write_text(dconf_config)

            locks_dir = dconf_dir / "locks"
            locks_dir.mkdir(parents=True, exist_ok=True)
            with open(locks_dir / "00-rdp-persistence", "w") as f:
                f.write("/org/gnome/desktop/session/idle-delay\n")
                f.write("/org/gnome/settings-daemon/plugins/power/sleep-inactive-ac-timeout\n")
                f.write("/org/gnome/settings-daemon/plugins/power/sleep-inactive-battery-timeout\n")
                f.write("/org/gnome/desktop/screensaver/lock-enabled\n")

            self.run_command("dconf update")
            self.log("GNOME sleep and screen lock disabled", "SUCCESS")

    def install_tailscale(self):
        """Install Tailscale"""
        if self._step_done("tailscale_installed"):
            self.log("Tailscale already installed — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== TAILSCALE INSTALLATION ==={Colors.ENDC}")
        self.log("Installing Tailscale...")

        # Check if already installed on the system even without state file
        result = self.run_command("which tailscale", check=False)
        if result.returncode == 0:
            self.log("Tailscale binary already present — skipping install", "SUCCESS")
            self._save_state(tailscale_installed=True)
            return

        if self.gui_available:
            self.show_gui_progress("Installing Tailscale", "Adding repository and installing VPN client...")

        codename = self.get_os_codename()
        self.run_command(f"curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/{codename}.noarmor.gpg | tee /usr/share/keyrings/tailscale-archive-keyring.gpg > /dev/null")
        self.run_command(f'curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/{codename}.tailscale-keyring.list | tee /etc/apt/sources.list.d/tailscale.list')
        self.run_command("apt update")
        self.run_command("apt install -y tailscale")

        self.log("Tailscale installed successfully", "SUCCESS")
        self._save_state(tailscale_installed=True)

    def configure_tailscale(self):
        """Interactive Tailscale configuration"""
        # Check if already authenticated — works even without state file
        result = self.run_command("tailscale status", check=False)
        if result.returncode == 0 and self.tailscale_ip:
            self.log(f"Tailscale already authenticated (IP: {self.tailscale_ip}) — skipping", "SUCCESS")
            self._save_state(tailscale_configured=True, tailscale_ip=self.tailscale_ip)
            return True

        if self._step_done("tailscale_configured") and self.tailscale_ip:
            self.log(f"Tailscale already configured (IP: {self.tailscale_ip}) — skipping", "SUCCESS")
            return True

        print(f"\n{Colors.HEADER}=== TAILSCALE CONFIGURATION ==={Colors.ENDC}")

        print(f"""
{Colors.BOLD}What is Tailscale?{Colors.ENDC}
{Colors.CYAN}  Tailscale is a private VPN that connects your devices securely
  over the internet. Once set up, you will use your Tailscale IP
  address to RDP into this server from anywhere — no open ports,
  no exposed firewall rules.

  Think of it as a private tunnel between your computer and this
  server that nobody else can access.{Colors.ENDC}

{Colors.BOLD}Before you continue:{Colors.ENDC}
{Colors.WARNING}  You need a free Tailscale account to proceed.
  If you don't have one yet, create one now at:

      https://tailscale.com

  Sign up is free and takes about 2 minutes.
  You can use Google, Microsoft, or GitHub to sign in.{Colors.ENDC}

{Colors.BOLD}What happens next:{Colors.ENDC}
{Colors.CYAN}  A link will appear in the terminal.
  Open that link in your browser and sign in to your Tailscale
  account to authorise this server. Once approved, setup continues
  automatically.{Colors.ENDC}
""")

        proceed = self.get_user_input(
            "Do you have a Tailscale account and are ready to authenticate?",
            ["Yes, I have an account — continue", "I need to create an account first", "Skip Tailscale setup"],
            default_index=0
        )

        if proceed == 1:
            print(f"\n{Colors.CYAN}  Go to {Colors.BOLD}https://tailscale.com{Colors.ENDC}{Colors.CYAN} and create your free account.{Colors.ENDC}")
            print(f"{Colors.CYAN}  Come back and re-run this setup once your account is ready.{Colors.ENDC}\n")
            input(f"{Colors.WARNING}  Press Enter once your account is created and you are ready to continue...{Colors.ENDC}")
            proceed = self.get_user_input(
                "Ready to authenticate with Tailscale?",
                ["Yes, authenticate now", "Skip Tailscale setup"],
                default_index=0
            )
            if proceed == 1:
                self.log("Tailscale setup skipped by user", "WARNING")
                return False

        if proceed == 2:
            self.log("Tailscale setup skipped by user", "WARNING")
            return False

        try:
            self.run_command("tailscale up", capture_output=False)
        except subprocess.CalledProcessError:
            self.log("Tailscale authentication may have failed", "WARNING")
            retry = self.get_user_input(
                "Tailscale authentication failed. What would you like to do?",
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
            result = self.run_command("tailscale ip -4")
            self.tailscale_ip = result.stdout.strip()
            self.log(f"Tailscale IP assigned: {self.tailscale_ip}", "SUCCESS")
            self._save_state(tailscale_configured=True, tailscale_ip=self.tailscale_ip)
            return True
        except:
            self.log("Failed to get Tailscale IP", "ERROR")
            return False

    def test_tailscale_connection(self):
        """Test Tailscale connectivity based on access method"""
        print(f"\n{Colors.HEADER}=== TAILSCALE CONNECTION TEST ==={Colors.ENDC}")

        if not self.tailscale_ip:
            self.log("No Tailscale IP available for testing", "ERROR")
            return False

        if self.initial_access_method == "SSH":
            rdp_user = self.rdp_username or "your-rdp-user"

            print(f"""
{Colors.BOLD}Before you test the connection:{Colors.ENDC}
{Colors.WARNING}  Tailscale must also be installed on your personal computer
  or device — the one you will use to RDP in.

  Download and install it now if you haven't already:

      https://tailscale.com/download

  Sign in with the SAME account you used to authorise this server.
  Once connected, your device and this server will be on the same
  private network.{Colors.ENDC}

{Colors.BOLD}Your server's Tailscale IP:{Colors.ENDC}
{Colors.GREEN}  {self.tailscale_ip}{Colors.ENDC}

{Colors.BOLD}Test these connections from your personal device:{Colors.ENDC}
{Colors.CYAN}  • RDP:  {self.tailscale_ip}:3389   (username: {rdp_user})
  • SSH:  ssh {getpass.getuser()}@{self.tailscale_ip}{Colors.ENDC}
""")

            while True:
                test_result = self.get_user_input(
                    "Can you successfully connect via RDP and SSH through Tailscale?",
                    ["Yes, connections work", "No, having issues", "Skip test (risky)"],
                    default_index=0
                )

                if test_result == 0:
                    self.log("Tailscale connectivity confirmed", "SUCCESS")
                    return True
                elif test_result == 2:
                    self.log("User chose to skip connection test", "WARNING")
                    return True
                else:
                    troubleshoot = self.get_user_input(
                        "Connection issues detected. What would you like to do?",
                        ["Get troubleshooting help", "Retry test", "Continue anyway (risky)", "Exit setup"],
                        default_index=1
                    )

                    if troubleshoot == 0:
                        self.show_troubleshooting_help()
                    elif troubleshoot == 1:
                        continue
                    elif troubleshoot == 2:
                        return True
                    else:
                        sys.exit(0)

        elif self.initial_access_method == "RDP":
            if self.gui_available:
                try:
                    root = tk.Tk()
                    root.withdraw()
                    result = messagebox.askyesno(
                        "Tailscale Test",
                        f"Your server's Tailscale IP is: {self.tailscale_ip}\n\n"
                        f"Tailscale should now be running.\n"
                        f"You can test SSH access from another device if desired.\n\n"
                        f"Continue with server lockdown?"
                    )
                    root.destroy()
                    if result:
                        self.log("RDP user confirmed Tailscale setup", "SUCCESS")
                        return True
                    else:
                        return False
                except:
                    pass

            result = self.get_user_input(
                f"Tailscale IP: {self.tailscale_ip}\n\nTailscale is now running. Continue with server lockdown?",
                ["Yes, continue", "No, troubleshoot first"],
                default_index=0
            )
            return result == 0

        return True

    def show_troubleshooting_help(self):
        """Display troubleshooting information"""
        help_text = """
TAILSCALE TROUBLESHOOTING:

1. Tailscale Client Installation:
   • Download from https://tailscale.com/download
   • Install on your home computer
   • Login with the same account used on server

2. Connection Issues:
   • Check both devices show as connected in Tailscale admin panel
   • Verify no local firewalls blocking connections
   • Try: tailscale ping [server-ip] from home computer

3. RDP Issues:
   • Use RDP client with server IP: {tailscale_ip}:3389
   • Try different RDP clients if one fails
   • Ensure server firewall allows Tailscale traffic

4. SSH Issues:
   • Command: ssh username@{tailscale_ip}
   • Check SSH service is running: systemctl status ssh
   • Verify SSH allows connections from Tailscale network
        """.format(tailscale_ip=self.tailscale_ip)

        if self.gui_available:
            try:
                root = tk.Tk()
                root.withdraw()

                help_window = tk.Toplevel()
                help_window.title("Troubleshooting Help")
                help_window.geometry("600x400")

                text_widget = tk.Text(help_window, wrap=tk.WORD)
                scrollbar = tk.Scrollbar(help_window, orient=tk.VERTICAL, command=text_widget.yview)
                text_widget.configure(yscrollcommand=scrollbar.set)

                text_widget.insert(tk.END, help_text)
                text_widget.config(state=tk.DISABLED)

                text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

                close_btn = tk.Button(help_window, text="Close", command=help_window.destroy)
                close_btn.pack(pady=10)

                help_window.wait_window()
                root.destroy()
            except:
                pass

        print(f"{Colors.CYAN}{help_text}{Colors.ENDC}")

    def lockdown_server(self):
        """Lock down server to only allow Tailscale connections"""
        if self._step_done("server_locked_down"):
            self.log("Server already locked down — skipping", "SUCCESS")
            return True

        print(f"\n{Colors.HEADER}=== SERVER LOCKDOWN ==={Colors.ENDC}")

        warning_message = ("⚠️  WARNING: Server Lockdown ⚠️\n\n"
                          "This will lock down the server to Tailscale-only access!\n"
                          "After this step, you can only connect via Tailscale network.\n\n"
                          "Make sure you tested Tailscale connections successfully.")

        if self.gui_available:
            try:
                root = tk.Tk()
                root.withdraw()
                result = messagebox.askyesno("Server Lockdown Warning", warning_message)
                root.destroy()
                if not result:
                    self.log("Server lockdown cancelled by user", "WARNING")
                    return False
            except:
                pass

        print(f"{Colors.FAIL}{Colors.BOLD}WARNING: This will lock down the server!{Colors.ENDC}")
        print(f"{Colors.WARNING}After this step, you will only be able to connect via Tailscale.{Colors.ENDC}")
        print(f"{Colors.WARNING}Make sure you can connect via Tailscale before proceeding.{Colors.ENDC}")

        confirmation = input(f"\n{Colors.WARNING}Type 'LOCKDOWN' to confirm server lockdown: {Colors.ENDC}")
        if confirmation != 'LOCKDOWN':
            self.log("Server lockdown cancelled by user", "WARNING")
            return False

        self.log("Beginning server lockdown...")

        # Explicitly enable IPv6 filtering before resetting rules —
        # do not rely on the distro default being correct
        self.run_command("sed -i 's/^IPV6=no/IPV6=yes/' /etc/default/ufw", check=False)
        result = self.run_command("grep -c '^IPV6=' /etc/default/ufw", check=False)
        if result.stdout.strip() == "0":
            self.run_command("echo 'IPV6=yes' >> /etc/default/ufw")
        self.log("UFW IPv6 filtering confirmed enabled")

        self.run_command("ufw --force reset")
        self.run_command("ufw default deny incoming")
        self.run_command("ufw default allow outgoing")
        self.run_command("ufw allow in on tailscale0")
        self.run_command("ufw allow out on tailscale0")

        # Allow SSH and RDP from both Tailscale IPv4 CGNAT and IPv6 CGNAT ranges
        tailscale_subnet_v4 = "100.64.0.0/10"
        tailscale_subnet_v6 = "fd7a:115c:a1e0::/48"
        for subnet in (tailscale_subnet_v4, tailscale_subnet_v6):
            self.run_command(f"ufw allow from {subnet} to any port 22")
            self.run_command(f"ufw allow from {subnet} to any port 3389")
        self.run_command("ufw --force enable")

        if self.tailscale_ip:
            # Only append ListenAddress if not already present
            with open("/etc/ssh/sshd_config", "r") as f:
                sshd_config = f.read()

            if f"ListenAddress {self.tailscale_ip}" not in sshd_config:
                with open("/etc/ssh/sshd_config", "a") as f:
                    f.write(f"\n# Tailscale only configuration\nListenAddress {self.tailscale_ip}\n")

            self.service_command("restart", "ssh", "sshd")

        self.log("Server lockdown completed", "SUCCESS")
        self._save_state(server_locked_down=True)

        if self.initial_access_method == "SSH":
            print(f"\n{Colors.WARNING}  ⚠  Your connection may disconnect — this is normal.{Colors.ENDC}")
            print(f"\n{Colors.BOLD}  What to do next:{Colors.ENDC}")
            print(f"{Colors.WARNING}  • If you stay connected: run sudo vps-post-setup right here in this window.{Colors.ENDC}")
            print(f"{Colors.WARNING}  • If you get disconnected: reconnect via SSH to {self.tailscale_ip}{Colors.ENDC}")
            print(f"{Colors.WARNING}    then run: sudo vps-post-setup{Colors.ENDC}")
            print(f"{Colors.WARNING}    (this finishes installing OpenClaw and Chrome){Colors.ENDC}")
            print(f"\n{Colors.FAIL}  ✗  IMPORTANT: Do NOT run sudo vps-post-setup inside an RDP session.{Colors.ENDC}")
            print(f"{Colors.FAIL}     Use this console or a direct SSH terminal only.{Colors.ENDC}\n")

            for i in range(10, 0, -1):
                print(f"{Colors.WARNING}  Closing connection in {i}...{Colors.ENDC}")
                time.sleep(1)

        elif self.initial_access_method == "RDP":
            if self.gui_available:
                try:
                    root = tk.Tk()
                    root.withdraw()
                    messagebox.showinfo(
                        "Lockdown Complete",
                        f"Server lockdown completed!\n\n"
                        f"Your server is now secure and only accessible via Tailscale.\n"
                        f"Tailscale IP: {self.tailscale_ip}\n\n"
                        f"Continuing with application installation..."
                    )
                    root.destroy()
                except:
                    pass

            print(f"{Colors.GREEN}Lockdown completed! Continuing with setup...{Colors.ENDC}")

        return True

    def install_applications(self):
        """Install OpenClaw and Chrome"""
        if self.gui_available:
            self.show_gui_progress("Installing Applications", "Installing OpenClaw and Google Chrome...")

        self.install_openclaw()
        self.install_homebrew()
        self.install_chrome()
        self.install_chrome_cleanup()
        self.install_security_check()
        self.create_user_shortcuts()

    def install_openclaw(self):
        """Install OpenClaw using the official installer"""
        if self._step_done("openclaw_installed"):
            self.log("OpenClaw already installed — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== OPENCLAW AI INSTALLATION ==={Colors.ENDC}")
        self.log("Installing OpenClaw AI...")

        install_user = self.rdp_username or "root"

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
        self._save_state(openclaw_installed=True)

    def install_homebrew(self):
        """Pre-install Homebrew so OpenClaw skills install correctly during onboarding"""
        if self._step_done("homebrew_installed"):
            self.log("Homebrew already installed — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== HOMEBREW INSTALLATION ==={Colors.ENDC}")
        install_user = self.rdp_username or "root"

        # Check if already present for this user
        result = self.run_command(
            f"su - {install_user} -c 'command -v brew'", check=False
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
        self._save_state(homebrew_installed=True)

    def install_chrome(self):
        """Install Google Chrome"""
        if self._step_done("chrome_installed"):
            self.log("Chrome already installed — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== GOOGLE CHROME INSTALLATION ==={Colors.ENDC}")
        self.log("Installing Google Chrome...")

        result = self.run_command("dpkg -l | grep google-chrome", check=False)
        if result.returncode == 0:
            self.log("Google Chrome is already installed", "SUCCESS")
            self._save_state(chrome_installed=True)
            return

        try:
            self.log("Downloading Chrome package...")
            self.run_command("wget -q -O /tmp/google-chrome-stable_current_amd64.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb")
            self.run_command("apt install -y /tmp/google-chrome-stable_current_amd64.deb")
            self.run_command("rm -f /tmp/google-chrome-stable_current_amd64.deb")

        except subprocess.CalledProcessError:
            self.log("Fallback: Installing Chrome via repository...", "WARNING")
            self.run_command("wget -q -O /usr/share/keyrings/google-chrome.gpg https://dl.google.com/linux/linux_signing_key.pub")
            self.run_command('echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list')
            self.run_command("apt update")
            self.run_command("apt install -y google-chrome-stable")

        result = self.run_command("google-chrome --version")
        self.log(f"Chrome installed: {result.stdout.strip()}", "SUCCESS")
        self._save_state(chrome_installed=True)

    def install_security_check(self):
        """Install the desktop security verification script"""
        if self._step_done("security_check_installed"):
            self.log("Security check already installed — skipping", "SUCCESS")
            return

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

        self._save_state(security_check_installed=True)

    def install_chrome_cleanup(self):
        """Install a daily systemd timer to keep Chrome storage under 1GB"""
        if self._step_done("chrome_cleanup_installed"):
            self.log("Chrome cleanup already installed — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== CHROME STORAGE CLEANUP ==={Colors.ENDC}")
        self.log("Installing Chrome storage cleanup timer...")

        install_user = self.rdp_username or "root"
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
        self._save_state(chrome_cleanup_installed=True)

    def create_user_shortcuts(self):
        """Create desktop shortcuts for regular users"""
        if self._step_done("shortcuts_created"):
            self.log("User shortcuts already created — skipping", "SUCCESS")
            return

        print(f"\n{Colors.HEADER}=== CREATING USER SHORTCUTS ==={Colors.ENDC}")

        user_dirs = list(_real_user_homes())

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
            desktop_dir.mkdir(exist_ok=True)

            # Chrome shortcut
            chrome_desktop = "/usr/share/applications/google-chrome.desktop"
            if Path(chrome_desktop).exists():
                user_shortcut = desktop_dir / "google-chrome.desktop"
                self.run_command(f"cp {chrome_desktop} {user_shortcut}")
                self.run_command(f"chown {username}:{username} {user_shortcut}")
                self.run_command(f"chmod +x {user_shortcut}")
                self.log(f"Created google-chrome.desktop shortcut for {username}", "SUCCESS")

            # URL shortcuts
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

        if self.rdp_username:
            self.run_command(
                f"su - {self.rdp_username} -c 'xdg-user-dirs-update'",
                check=False
            )

        self._save_state(shortcuts_created=True)

    def create_final_report(self):
        """Create final setup report"""
        print(f"\n{Colors.HEADER}=== FINAL SETUP REPORT ==={Colors.ENDC}")

        try:
            tailscale_result = self.run_command("tailscale ip -4")
            tailscale_ip = tailscale_result.stdout.strip()
        except:
            tailscale_ip = self.tailscale_ip or "Not available"

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

        rdp_user = self.rdp_username or "your-rdp-user"

        report = f"""
{Colors.GREEN}{Colors.BOLD}UNIVERSAL VPS SETUP COMPLETED!{Colors.ENDC}

{Colors.CYAN}Setup Summary:{Colors.ENDC}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{Colors.BOLD}Initial Access Method: {self.initial_access_method}{Colors.ENDC}

{Colors.BOLD}Network Configuration:{Colors.ENDC}
• Tailscale IP: {tailscale_ip}
• RDP Access: {tailscale_ip}:3389  (user: {rdp_user})
• SSH Access: ssh {getpass.getuser()}@{tailscale_ip}
• Security: Locked down to Tailscale-only access

{Colors.BOLD}Applications Installed:{Colors.ENDC}
• OpenClaw AI: {openclaw_status}
• Google Chrome: {chrome_version}
• Desktop shortcuts created for all users

{Colors.BOLD}Access Information:{Colors.ENDC}
• RDP: Connect to {tailscale_ip}:3389 with user {rdp_user}
• Applications available in desktop environment
• Session persistence enabled (browsers stay open)

{Colors.WARNING}Security Notes:{Colors.ENDC}
• Server locked down to Tailscale network only
• UFW firewall active with restrictive rules
• All connections must use Tailscale VPN

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

{Colors.GREEN}Setup completed successfully!{Colors.ENDC}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        print(report)

        if self.gui_available and self.initial_access_method == "RDP":
            try:
                root = tk.Tk()
                root.withdraw()
                messagebox.showinfo(
                    "Setup Complete!",
                    f"Ubuntu VPS setup completed successfully!\n\n"
                    f"Tailscale IP: {tailscale_ip}\n"
                    f"RDP user: {rdp_user}\n"
                    f"OpenClaw: {openclaw_status}\n"
                    f"Chrome: Installed\n\n"
                    f"Applications are available on your desktop!"
                )
                root.destroy()
            except:
                pass

        with open("/var/log/universal_vps_setup.log", "w") as f:
            f.write("Universal VPS Setup Log\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"Initial Access Method: {self.initial_access_method}\n")
            f.write(f"Desktop Type: {self.desktop_type}\n")
            f.write(f"RDP User: {rdp_user}\n")
            f.write(f"Tailscale IP: {tailscale_ip}\n\n")
            for entry in self.setup_log:
                f.write(entry + "\n")

    # ── Orchestrator ──────────────────────────────────────────────────────────

    def run_setup(self):
        """Main setup orchestrator - handles both SSH and RDP scenarios"""
        try:
            self.show_startup_message()

            # If lockdown already done for SSH users, nothing left to do in phase 1
            if self._step_done("server_locked_down") and self.initial_access_method == "SSH":
                print(f"\n{Colors.GREEN}Phase 1 already complete.{Colors.ENDC}")
                print(f"{Colors.WARNING}Reconnect via Tailscale ({self.tailscale_ip}) and run post_lockdown_setup.py{Colors.ENDC}")
                return

            response = self.get_user_input(
                "Ready to begin VPS setup?",
                ["Start setup", "Exit"],
                default_index=0
            )

            if response == 1:
                self.log("Setup cancelled by user", "WARNING")
                sys.exit(0)

            self.check_root()
            self.update_system()
            self.detect_and_setup_desktop()
            self.create_rdp_user()
            self.configure_rdp_persistence()
            self.install_tailscale()

            if self.configure_tailscale():
                if self.test_tailscale_connection():
                    if self.lockdown_server():
                        if self.initial_access_method == "SSH":
                            print(f"\n{Colors.GREEN}{Colors.BOLD}  Phase 1 Complete!{Colors.ENDC}")
                            print(f"{Colors.WARNING}  • If you stayed connected: run sudo vps-post-setup right here in this window.{Colors.ENDC}")
                            print(f"{Colors.WARNING}  • If you got disconnected: reconnect via SSH to {self.tailscale_ip}{Colors.ENDC}")
                            print(f"{Colors.WARNING}    then run: sudo vps-post-setup{Colors.ENDC}")
                            print(f"{Colors.FAIL}  IMPORTANT: Do NOT run sudo vps-post-setup inside an RDP session.{Colors.ENDC}")
                            return

                        elif self.initial_access_method == "RDP":
                            self.install_applications()
                            self.create_final_report()
                else:
                    print(f"{Colors.FAIL}Setup aborted due to connectivity issues{Colors.ENDC}")
            else:
                print(f"{Colors.WARNING}Setup completed without Tailscale configuration{Colors.ENDC}")

        except KeyboardInterrupt:
            print(f"\n{Colors.WARNING}Setup interrupted by user{Colors.ENDC}")
            sys.exit(1)
        except Exception as e:
            self.log(f"Setup failed: {str(e)}", "ERROR")
            if self.gui_available:
                try:
                    root = tk.Tk()
                    root.withdraw()
                    messagebox.showerror("Setup Failed", f"An error occurred during setup:\n\n{str(e)}")
                    root.destroy()
                except:
                    pass
            sys.exit(1)


def main():
    setup = UniversalVPSSetup()
    setup.run_setup()

if __name__ == "__main__":
    main()
