#!/usr/bin/env python3
"""
OpenClaw Control Panel Widget
GTK3 desktop widget for OpenClaw service status and quick actions.
"""

import base64
from datetime import datetime, timezone
import json
import os
import subprocess
import threading
import time
from pathlib import Path

# Must be set before importing GTK — forces Adwaita dark variant even in
# xrdp sessions that have no settings daemon (xfsettingsd/gsd-xsettings).
os.environ.setdefault("GTK_THEME", "Adwaita:dark")

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, GLib, Gdk, GdkPixbuf, Gio

# Twemoji lobster emoji (🦞) — CC-BY 4.0 Twitter/Twemoji
LOGO_B64 = (
    "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"
)

REPO_OWNER = "mshaw32"
REPO_NAME = "secureclaw"
DEFAULT_PORT = 18789
REPO_BRANCH_OVERRIDE = None  # injected at install time by install_widget.sh

DARK_CSS = """
window {
    background-color: #1a1c1e;
    color: #e0e0e0;
}
.panel {
    background-color: #22252a;
    border-radius: 8px;
    padding: 10px;
    margin: 4px;
}
.header-box {
    background-color: #22252a;
    border-radius: 8px;
    padding: 14px 16px;
    margin: 6px 6px 2px 6px;
}
.title-label {
    font-size: 15px;
    font-weight: bold;
    color: #e8a020;
}
.subtitle-label {
    font-size: 11px;
    color: #888888;
}
.section-label {
    font-size: 11px;
    font-weight: bold;
    color: #666666;
    letter-spacing: 1px;
}
.led-card {
    background-color: #1e2124;
    border-radius: 6px;
    padding: 8px;
    margin: 2px;
    border: 1px solid #2a2d32;
}
.led-card-green {
    border-color: #2a4a2a;
    background-color: #1a2a1a;
}
.led-card-red {
    border-color: #4a1a1a;
    background-color: #2a1a1a;
}
.led-card-yellow {
    border-color: #4a3a1a;
    background-color: #2a2a1a;
}
.led-dot {
    font-size: 12px;
}
.led-name {
    font-size: 11px;
    font-weight: bold;
    color: #cccccc;
}
.led-status {
    font-size: 10px;
    color: #888888;
}
.action-button {
    background-image: none;
    background-color: #2a2d32;
    border: 1px solid #383c42;
    border-radius: 6px;
    color: #e0e0e0;
    padding: 6px 10px;
    font-size: 12px;
}
.action-button label {
    color: #e0e0e0;
}
.action-button:hover {
    background-image: none;
    background-color: #383c42;
    border-color: #e8a020;
}
.action-button:hover label {
    color: #ffffff;
}
.action-label {
    font-size: 12px;
    font-weight: bold;
    color: #e0e0e0;
}
.action-sublabel {
    font-size: 10px;
    color: #888888;
}
.footer-box {
    background-color: #16181a;
    border-radius: 6px;
    padding: 6px 10px;
    margin: 2px 6px 6px 6px;
}
.footer-label {
    font-size: 10px;
    color: #666666;
}
.uptime-badge {
    background-color: #1a3a1a;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 10px;
    color: #4caf50;
}
.refresh-button {
    background-image: none;
    background-color: #2a2d32;
    border: 1px solid #383c42;
    border-radius: 4px;
    color: #aaaaaa;
    padding: 2px 8px;
    font-size: 10px;
}
.refresh-button label {
    color: #aaaaaa;
}
.refresh-button:hover {
    background-image: none;
    border-color: #e8a020;
    color: #e0e0e0;
}
.refresh-button:hover label {
    color: #e0e0e0;
}
.tools-section {
    background-color: #22252a;
    border-radius: 8px;
    padding: 10px;
    margin: 2px 6px 2px 6px;
}
.tool-row {
    background-color: #1e2124;
    border-radius: 5px;
    padding: 6px 8px;
    margin: 2px 0px;
    border: 1px solid #2a2d32;
}
.tool-name {
    font-size: 11px;
    font-weight: bold;
    color: #cccccc;
}
.tool-desc {
    font-size: 10px;
    color: #666666;
}
.tool-installed {
    font-size: 10px;
    color: #4caf50;
}
.tool-install-btn {
    background-image: none;
    background-color: #1a3a1a;
    border: 1px solid #2a5a2a;
    border-radius: 4px;
    color: #4caf50;
    padding: 2px 8px;
    font-size: 10px;
}
.tool-install-btn label {
    color: #4caf50;
}
.tool-install-btn:hover {
    background-image: none;
    background-color: #2a5a2a;
}
"""



def get_repo_branch():
    """Return the branch this widget was installed from."""
    if REPO_BRANCH_OVERRIDE and REPO_BRANCH_OVERRIDE in ("main", "dev"):
        return REPO_BRANCH_OVERRIDE
    return "main"


def get_dashboard_port():
    """Read dashboard port from openclaw config, defaulting to 18789."""
    config = Path.home() / ".openclaw" / "openclaw.json"
    try:
        with open(config) as f:
            return json.load(f).get("gateway", {}).get("port", DEFAULT_PORT)
    except Exception:
        return DEFAULT_PORT


def run_command(cmd, shell=True, timeout=10):
    """Run a shell command and return (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            cmd, shell=shell, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout", 1
    except Exception as e:
        return "", str(e), 1


class StatusCard:
    """A single LED status card widget."""

    def __init__(self, name):
        self.name = name
        self.state = "unknown"  # green, red, yellow, unknown

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.box.get_style_context().add_class("led-card")

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.led = Gtk.Label(label="●")
        self.led.get_style_context().add_class("led-dot")
        row.pack_start(self.led, False, False, 0)

        name_label = Gtk.Label(label=name)
        name_label.get_style_context().add_class("led-name")
        name_label.set_halign(Gtk.Align.START)
        row.pack_start(name_label, True, True, 0)

        self.box.pack_start(row, False, False, 0)

        self.status_label = Gtk.Label(label="Checking...")
        self.status_label.get_style_context().add_class("led-status")
        self.status_label.set_halign(Gtk.Align.START)
        self.box.pack_start(self.status_label, False, False, 0)

        self._pulse_on = True
        self._pulse_source = None
        self._set_color("unknown")

    def set_state(self, state, status_text):
        """Update the LED state. Must be called from main thread."""
        # Remove old card classes
        ctx = self.box.get_style_context()
        for cls in ("led-card-green", "led-card-red", "led-card-yellow"):
            ctx.remove_class(cls)

        self.state = state
        self.status_label.set_text(status_text)
        self._set_color(state)

        if self._pulse_source:
            GLib.source_remove(self._pulse_source)
            self._pulse_source = None

        if state == "green":
            ctx.add_class("led-card-green")
            self._pulse_source = GLib.timeout_add(1200, self._pulse)
        elif state == "red":
            ctx.add_class("led-card-red")
            self.led.set_opacity(1.0)
        elif state == "yellow":
            ctx.add_class("led-card-yellow")
            self.led.set_opacity(1.0)
        else:
            self.led.set_opacity(0.4)

    def _set_color(self, state):
        colors = {"green": "#4caf50", "red": "#f44336", "yellow": "#ffb300", "unknown": "#555555"}
        color = colors.get(state, "#555555")
        self.led.set_markup(f'<span foreground="{color}">●</span>')

    def _pulse(self):
        if self.state != "green":
            return False
        self._pulse_on = not self._pulse_on
        self.led.set_opacity(1.0 if self._pulse_on else 0.5)
        return True


class OpenClawWidget(Gtk.Window):

    def __init__(self):
        super().__init__(title="OpenClaw Control Panel")
        self.set_default_size(420, -1)
        self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER)

        self.branch = get_repo_branch()
        self.port = get_dashboard_port()
        self.tools_data = []
        self._tool_rows = {}

        # Build lobster pixbuf once — reused at header (48px) and action rows (24px)
        _logo_data = base64.b64decode(LOGO_B64)
        _stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(_logo_data))
        self.logo_pixbuf_48 = GdkPixbuf.Pixbuf.new_from_stream_at_scale(
            _stream, 48, 48, True, None
        )
        self.logo_pixbuf_24 = self.logo_pixbuf_48.scale_simple(
            24, 24, GdkPixbuf.InterpType.BILINEAR
        )

        self._apply_css()
        self._build_ui()

        self.connect("destroy", Gtk.main_quit)

        # Initial status refresh
        self._schedule_refresh()

        # Auto-refresh every 30 seconds
        GLib.timeout_add_seconds(30, self._auto_refresh)

    def _apply_css(self):
        # Belt-and-suspenders: also set programmatically for environments
        # where the env var alone isn't picked up after process start.
        settings = Gtk.Settings.get_default()
        settings.set_property("gtk-application-prefer-dark-theme", True)

        provider = Gtk.CssProvider()
        provider.load_from_data(DARK_CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _build_ui(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(outer)

        outer.pack_start(self._build_header(), False, False, 0)
        outer.pack_start(self._build_status_section(), False, False, 0)
        outer.pack_start(self._build_actions_section(), False, False, 0)
        outer.pack_start(self._build_tools_section(), False, False, 0)
        outer.pack_start(self._build_footer(), False, False, 0)

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.get_style_context().add_class("header-box")

        logo_img = Gtk.Image.new_from_pixbuf(self.logo_pixbuf_48)
        logo_img.set_valign(Gtk.Align.CENTER)
        box.pack_start(logo_img, False, False, 0)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label="OpenClaw Control Panel")
        title.get_style_context().add_class("title-label")
        title.set_halign(Gtk.Align.START)
        text_box.pack_start(title, False, False, 0)

        hostname = os.uname().nodename
        self.version_label = Gtk.Label(label=f"Loading version... · {hostname}")
        self.version_label.get_style_context().add_class("subtitle-label")
        self.version_label.set_halign(Gtk.Align.START)
        text_box.pack_start(self.version_label, False, False, 0)

        box.pack_start(text_box, True, True, 0)
        return box

    # ── Status LEDs ───────────────────────────────────────────────────────────

    def _build_status_section(self):
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        wrapper.get_style_context().add_class("panel")
        wrapper.set_margin_start(6)
        wrapper.set_margin_end(6)
        wrapper.set_margin_top(4)

        lbl = Gtk.Label(label="SERVICE STATUS")
        lbl.get_style_context().add_class("section-label")
        lbl.set_halign(Gtk.Align.START)
        wrapper.pack_start(lbl, False, False, 0)

        grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        wrapper.pack_start(grid, False, False, 0)

        self.card_service = StatusCard("OpenClaw Service")
        self.card_tailscale = StatusCard("Tailscale VPN")
        self.card_firewall = StatusCard("Firewall Rules")

        # Extra detail labels inside the Tailscale card
        self.ts_ip_host_label = Gtk.Label(label="")
        self.ts_ip_host_label.get_style_context().add_class("led-status")
        self.ts_ip_host_label.set_halign(Gtk.Align.START)
        self.ts_ip_host_label.set_ellipsize(3)
        self.card_tailscale.box.pack_start(self.ts_ip_host_label, False, False, 0)

        self.ts_expiry_label = Gtk.Label(label="")
        self.ts_expiry_label.get_style_context().add_class("led-status")
        self.ts_expiry_label.set_halign(Gtk.Align.START)
        self.card_tailscale.box.pack_start(self.ts_expiry_label, False, False, 0)

        for card in (self.card_service, self.card_tailscale, self.card_firewall):
            card.box.set_hexpand(True)
            grid.pack_start(card.box, True, True, 0)

        return wrapper

    # ── Actions ───────────────────────────────────────────────────────────────

    def _build_actions_section(self):
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        wrapper.get_style_context().add_class("panel")
        wrapper.set_margin_start(6)
        wrapper.set_margin_end(6)
        wrapper.set_margin_top(0)

        lbl = Gtk.Label(label="ACTIONS")
        lbl.get_style_context().add_class("section-label")
        lbl.set_halign(Gtk.Align.START)
        wrapper.pack_start(lbl, False, False, 0)

        # Open Dashboard
        dash_row = self._make_action_row(
            "Open Dashboard",
            f"http://127.0.0.1:{self.port}/",
            self._on_open_dashboard,
            icon_pixbuf=self.logo_pixbuf_24
        )
        self.dash_sublabel = dash_row[1]
        wrapper.pack_start(dash_row[0], False, False, 0)

        # Start Browser
        plugin_row = self._make_action_row(
            "Start Browser",
            "Start the OpenClaw managed browser",
            self._on_install_plugin,
            icon_pixbuf=self.logo_pixbuf_24
        )
        self.plugin_sublabel = plugin_row[1]
        wrapper.pack_start(plugin_row[0], False, False, 0)

        # Check for Updates
        update_row = self._make_action_row(
            "Check for Updates",
            "Checks openclaw update status",
            self._on_check_updates,
            icon_pixbuf=self.logo_pixbuf_24
        )
        self.update_sublabel = update_row[1]
        wrapper.pack_start(update_row[0], False, False, 0)

        return wrapper

    def _make_action_row(self, label_text, sub_text, callback, icon_pixbuf=None):
        """Returns (row_box, sublabel_widget)."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        if icon_pixbuf is not None:
            icon_img = Gtk.Image.new_from_pixbuf(icon_pixbuf)
            icon_img.set_valign(Gtk.Align.CENTER)
            row.pack_start(icon_img, False, False, 0)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text_box.set_hexpand(True)

        lbl = Gtk.Label(label=label_text)
        lbl.get_style_context().add_class("action-label")
        lbl.set_halign(Gtk.Align.START)
        text_box.pack_start(lbl, False, False, 0)

        sublabel = Gtk.Label(label=sub_text)
        sublabel.get_style_context().add_class("action-sublabel")
        sublabel.set_halign(Gtk.Align.START)
        sublabel.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        text_box.pack_start(sublabel, False, False, 0)

        row.pack_start(text_box, True, True, 0)

        btn = Gtk.Button(label="Go")
        btn.get_style_context().add_class("action-button")
        btn.connect("clicked", callback)
        row.pack_start(btn, False, False, 0)

        return row, sublabel

    # ── Tools Section ─────────────────────────────────────────────────────────

    def _build_tools_section(self):
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        wrapper.get_style_context().add_class("tools-section")

        lbl = Gtk.Label(label="AVAILABLE TOOLS")
        lbl.get_style_context().add_class("section-label")
        lbl.set_halign(Gtk.Align.START)
        wrapper.pack_start(lbl, False, False, 0)

        self.tools_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        wrapper.pack_start(self.tools_list_box, False, False, 0)

        self.tools_status_label = Gtk.Label(label="Checking for tools...")
        self.tools_status_label.get_style_context().add_class("action-sublabel")
        self.tools_status_label.set_halign(Gtk.Align.START)
        self.tools_list_box.pack_start(self.tools_status_label, False, False, 0)

        return wrapper

    def _update_tools_ui(self, tools):
        """Rebuild the tools list UI. Called from main thread."""
        # Clear existing rows
        for child in self.tools_list_box.get_children():
            self.tools_list_box.remove(child)
        self._tool_rows = {}

        if tools is None:
            lbl = Gtk.Label(label="Unable to check for tools")
            lbl.get_style_context().add_class("action-sublabel")
            lbl.set_halign(Gtk.Align.START)
            self.tools_list_box.pack_start(lbl, False, False, 0)
            self.tools_list_box.show_all()
            return

        if len(tools) == 0:
            lbl = Gtk.Label(label="No tools available yet")
            lbl.get_style_context().add_class("action-sublabel")
            lbl.set_halign(Gtk.Align.START)
            self.tools_list_box.pack_start(lbl, False, False, 0)
            self.tools_list_box.show_all()
            return

        for tool in tools:
            row = self._make_tool_row(tool)
            self.tools_list_box.pack_start(row, False, False, 0)

        self.tools_list_box.show_all()

    def _make_tool_row(self, tool):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.get_style_context().add_class("tool-row")

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text_box.set_hexpand(True)

        name_lbl = Gtk.Label(label=tool.get("name", tool.get("id", "Unknown")))
        name_lbl.get_style_context().add_class("tool-name")
        name_lbl.set_halign(Gtk.Align.START)
        text_box.pack_start(name_lbl, False, False, 0)

        desc_lbl = Gtk.Label(label=tool.get("description", ""))
        desc_lbl.get_style_context().add_class("tool-desc")
        desc_lbl.set_halign(Gtk.Align.START)
        text_box.pack_start(desc_lbl, False, False, 0)

        row.pack_start(text_box, True, True, 0)

        # Check installed state
        installed = self._is_tool_installed(tool)
        if installed:
            tag = Gtk.Label(label="✓ Installed")
            tag.get_style_context().add_class("tool-installed")
            row.pack_start(tag, False, False, 0)
        else:
            btn = Gtk.Button(label="Install")
            btn.get_style_context().add_class("tool-install-btn")
            btn.connect("clicked", lambda b, t=tool: self._on_install_tool(t))
            row.pack_start(btn, False, False, 0)

        self._tool_rows[tool.get("id")] = row
        return row

    def _is_tool_installed(self, tool):
        detect_cmd = tool.get("detect_command", "")
        if not detect_cmd:
            return False
        _, _, rc = run_command(detect_cmd)
        return rc == 0

    # ── Footer ────────────────────────────────────────────────────────────────

    def _build_footer(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.get_style_context().add_class("footer-box")

        self.refresh_time_label = Gtk.Label(label="⟳ --:--:--")
        self.refresh_time_label.get_style_context().add_class("footer-label")
        box.pack_start(self.refresh_time_label, False, False, 0)

        self.uptime_label = Gtk.Label(label="")
        self.uptime_label.get_style_context().add_class("uptime-badge")
        box.pack_start(self.uptime_label, True, False, 0)

        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.get_style_context().add_class("refresh-button")
        refresh_btn.connect("clicked", lambda b: self._schedule_refresh())
        box.pack_end(refresh_btn, False, False, 0)

        return box

    # ── Status Refresh ────────────────────────────────────────────────────────

    def _auto_refresh(self):
        self._schedule_refresh()
        return True  # keep the timer running

    def _schedule_refresh(self):
        t = threading.Thread(target=self._do_refresh, daemon=True)
        t.start()

    def _do_refresh(self):
        """Run all checks in background thread, post results to UI."""
        service_state, service_text = self._check_service()
        tailscale_state, tailscale_text, ts_ip_host, ts_expiry = self._check_tailscale()
        firewall_state, firewall_text = self._check_firewall()
        version = self._get_version()
        uptime = self._get_uptime()
        tools = self._fetch_tools_manifest()

        GLib.idle_add(self._apply_refresh, service_state, service_text,
                      tailscale_state, tailscale_text, ts_ip_host, ts_expiry,
                      firewall_state, firewall_text, version, uptime, tools)

    def _apply_refresh(self, service_state, service_text,
                       tailscale_state, tailscale_text, ts_ip_host, ts_expiry,
                       firewall_state, firewall_text,
                       version, uptime, tools):
        self.card_service.set_state(service_state, service_text)
        self.card_tailscale.set_state(tailscale_state, tailscale_text)
        self.card_firewall.set_state(firewall_state, firewall_text)

        self.ts_ip_host_label.set_text(ts_ip_host)
        self.ts_expiry_label.set_markup(ts_expiry) if ts_expiry else self.ts_expiry_label.set_text("")

        hostname = os.uname().nodename
        self.version_label.set_text(f"{version} · {hostname}")

        now = time.strftime("%H:%M:%S")
        self.refresh_time_label.set_text(f"⟳ Refreshed {now}")
        self.uptime_label.set_markup(f'<span foreground="#4caf50">{uptime}</span>')

        self.port = get_dashboard_port()
        self.dash_sublabel.set_text(f"http://127.0.0.1:{self.port}/")

        self.tools_data = tools or []
        self._update_tools_ui(self.tools_data)

        return False  # idle_add callback: don't repeat

    # ── Individual Checks ─────────────────────────────────────────────────────

    def _check_service(self):
        stdout, _, rc = run_command(
            "systemctl --user is-active openclaw-gateway", timeout=8
        )
        if stdout == "active":
            return "green", "active"
        elif stdout in ("inactive", "failed"):
            return "red", stdout or "inactive"
        else:
            return "red", "not running"

    def _check_tailscale(self):
        """Returns (led_state, status_text, ip_host_text, expiry_markup)."""
        stdout, stderr, rc = run_command("tailscale status --json", timeout=8)
        if rc != 0:
            if "not found" in stderr.lower() or "command" in stderr.lower():
                return "yellow", "not installed", "", ""
            return "red", "not running", "", ""
        try:
            data = json.loads(stdout)
            state = data.get("BackendState", "")
            self_node = data.get("Self", {})

            # IP + hostname
            ips = self_node.get("TailscaleIPs", [])
            ip = ips[0] if ips else ""
            hostname = self_node.get("HostName", "") or self_node.get("DNSName", "").split(".")[0]
            ip_host = f"{ip}  ·  {hostname}" if ip else ""

            # Key expiry
            expiry_str = self_node.get("KeyExpiry", "")
            expiry_markup = self._format_expiry(expiry_str)

            if state == "Running":
                return "green", "Running", ip_host, expiry_markup
            return "red", state or "not running", ip_host, expiry_markup
        except Exception:
            return "yellow", "unknown", "", ""

    @staticmethod
    def _format_expiry(expiry_str):
        if not expiry_str:
            return '<span foreground="#555555">No expiry set</span>'
        try:
            expiry_dt = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            days = (expiry_dt - now).days
            date_str = expiry_dt.strftime("%b %d %Y")
            if days < 0:
                return f'<span foreground="#f44336">Key EXPIRED</span>'
            elif days < 7:
                return f'<span foreground="#f44336">Expires in {days}d  ⚠</span>'
            elif days < 30:
                return f'<span foreground="#ffb300">Expires in {days}d</span>'
            else:
                return f'<span foreground="#555555">Expires {date_str}</span>'
        except Exception:
            return ""

    def _check_firewall(self):
        stdout, stderr, rc = run_command("sudo -n ufw status", timeout=8)
        if rc != 0:
            return "yellow", "unknown"
        if "Status: active" in stdout:
            return "green", "active"
        return "red", "inactive"

    def _get_version(self):
        stdout, _, rc = run_command("openclaw -V", timeout=8)
        if rc == 0 and stdout:
            return stdout.split()[0] if stdout else "openclaw"
        return "openclaw"

    def _get_uptime(self):
        stdout, _, rc = run_command("uptime -p", timeout=5)
        if rc == 0 and stdout:
            return stdout
        return ""

    def _fetch_tools_manifest(self):
        url = (f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}"
               f"/{self.branch}/tools/manifest.json")
        stdout, _, rc = run_command(f"wget -q -O - {url!r}", timeout=15)
        if rc != 0:
            return None
        try:
            data = json.loads(stdout)
            return data.get("tools", [])
        except Exception:
            return None

    # ── Action Handlers ───────────────────────────────────────────────────────

    def _on_open_dashboard(self, button):
        self.port = get_dashboard_port()
        url = f"http://127.0.0.1:{self.port}/"
        run_command(f"xdg-open {url!r}")

    def _on_install_plugin(self, button):
        button.set_sensitive(False)
        self.plugin_sublabel.set_text("Starting...")

        def do_start():
            _, _, rc = run_command("openclaw browser start", timeout=30)
            GLib.idle_add(self._show_browser_dialog, button, rc)

        threading.Thread(target=do_start, daemon=True).start()

    def _show_browser_dialog(self, button, rc):
        self.plugin_sublabel.set_text("Start the OpenClaw managed browser")
        button.set_sensitive(True)

        dialog = Gtk.Dialog(
            title="Start Browser",
            transient_for=self,
            modal=True
        )
        dialog.set_default_size(320, -1)
        dialog.get_content_area().set_spacing(8)
        dialog.get_content_area().set_margin_start(12)
        dialog.get_content_area().set_margin_end(12)
        dialog.get_content_area().set_margin_top(12)
        dialog.get_content_area().set_margin_bottom(12)

        msg = "Browser started." if rc == 0 else "Browser start returned an error. Check openclaw status."
        lbl = Gtk.Label(label=msg)
        lbl.set_line_wrap(True)
        lbl.set_halign(Gtk.Align.START)
        dialog.get_content_area().pack_start(lbl, False, False, 0)

        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

        return False

    def _on_check_updates(self, button):
        button.set_sensitive(False)
        self.update_sublabel.set_text("Checking...")

        def do_check():
            stdout, stderr, rc = run_command("openclaw update status", timeout=30)
            result = stdout or stderr or "No output from update check."
            GLib.idle_add(self._show_update_dialog, button, result)

        threading.Thread(target=do_check, daemon=True).start()

    def _show_update_dialog(self, button, result):
        button.set_sensitive(True)
        now = time.strftime("%H:%M")
        self.update_sublabel.set_text(f"Last checked: {now}")

        # Detect update keywords
        low = result.lower()
        update_available = any(k in low for k in ("update available", "new version", "upgrade"))
        if update_available:
            self.update_sublabel.set_text(f"Update available! (checked {now})")

        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.NONE,
            text="OpenClaw Update Status"
        )
        dialog.format_secondary_text(result)
        dialog.add_button("Dismiss", Gtk.ResponseType.CLOSE)
        if update_available:
            dialog.add_button("Update Now", Gtk.ResponseType.ACCEPT)
            dialog.set_default_response(Gtk.ResponseType.ACCEPT)

        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.ACCEPT:
            run_command(
                "xfce4-terminal --title='OpenClaw Update' "
                "--command='bash -c \"openclaw update; echo; echo Done -- press Enter; read\"'"
            )
        return False

    def _on_install_tool(self, tool):
        script_path = tool.get("install_script", "")
        if not script_path:
            return
        url = (f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}"
               f"/{self.branch}/{script_path}")
        tool_name = tool.get("name", tool.get("id", "Tool"))
        cmd = (
            f"xfce4-terminal --title='Install {tool_name}' "
            f"--command='bash -c \"wget -qO /tmp/_tool_install.sh {url!r} "
            f"&& sudo bash /tmp/_tool_install.sh; echo; echo Done -- press Enter; read\"'"
        )
        run_command(cmd)
        # Re-fetch tools to update installed status
        GLib.timeout_add_seconds(5, lambda: self._schedule_refresh() or False)


def main():
    widget = OpenClawWidget()
    widget.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
