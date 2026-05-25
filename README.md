## Setup

**main (stable)**
```bash
wget -qO /tmp/sc-install.sh https://raw.githubusercontent.com/mshaw32/secureclaw/main/install.sh && sudo bash /tmp/sc-install.sh
```

**dev (latest)**
```bash
wget -qO /tmp/sc-install.sh https://raw.githubusercontent.com/mshaw32/secureclaw/dev/install.sh && sudo bash /tmp/sc-install.sh dev
```

### Proxmox VE CT / LXC

Choose **Proxmox VE CT / LXC** in the installer, or set the mode explicitly:

```bash
SECURECLAW_SETUP_MODE=proxmox_lxc wget -qO /tmp/sc-install.sh https://raw.githubusercontent.com/mshaw32/secureclaw/main/install.sh && sudo SECURECLAW_SETUP_MODE=proxmox_lxc bash /tmp/sc-install.sh
```

The LXC mode uses the VPS flow, then checks the container-side requirements that commonly need Proxmox host settings: systemd, `/dev/net/tun` for Tailscale, and firewall/iptables access for UFW lockdown.
