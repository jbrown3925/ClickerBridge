#!/usr/bin/env bash
# =============================================================================
# PerfectCue Bridge — Installer
# Ubuntu 24.04 LTS · UTM (QEMU backend) · macOS host
#
# Run as root:  sudo bash install.sh
# Re-runnable: config.json is never overwritten if it already exists.
# =============================================================================
set -euo pipefail

INSTALL_DIR="/opt/perfectcue-bridge"
SERVICE_USER="bridge"
BRIDGE_SERVICE="perfectcue-bridge"
WEB_SERVICE="perfectcue-web"

# ── Colours ────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; exit 1; }
step()  { echo -e "\n${CYAN}▶ $*${NC}"; }

# ── Root check ─────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Please run as root:  sudo bash install.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     PerfectCue Bridge — Installer        ║"
echo "║     Ubuntu 24.04 · UTM · macOS           ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── System packages ────────────────────────────────────────────────────
step "Installing system packages"
apt-get update -qq
apt-get install -y -q \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    gcc \
    usbutils
info "System packages installed"

# ── Service user ───────────────────────────────────────────────────────
step "Creating service user"
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
    info "Created user '$SERVICE_USER'"
else
    info "User '$SERVICE_USER' already exists"
fi
usermod -aG input "$SERVICE_USER"
info "User '$SERVICE_USER' is in group 'input'"

# ── Install directory ──────────────────────────────────────────────────
step "Installing files to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR/web"

cp "$SCRIPT_DIR/perfectcue_bridge.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/web/index.html"       "$INSTALL_DIR/web/"
cp "$SCRIPT_DIR/web_server.py"        "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/perfectcue_bridge.py"

# Preserve existing config — never overwrite
if [[ ! -f "$INSTALL_DIR/config.json" ]]; then
    cp "$SCRIPT_DIR/config.json" "$INSTALL_DIR/"
    info "Default config.json installed"
else
    warn "config.json already exists — preserving existing config"
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
info "Files installed"

# ── sudoers rule — allow bridge user to control its own service ────────
step "Writing sudoers rule"
SUDOERS_FILE='/etc/sudoers.d/perfectcue-bridge'
cat > "$SUDOERS_FILE" << 'EOF'
# Allow the bridge service account to control only the bridge service
bridge ALL=(ALL) NOPASSWD: /bin/systemctl start perfectcue-bridge
bridge ALL=(ALL) NOPASSWD: /bin/systemctl stop perfectcue-bridge
bridge ALL=(ALL) NOPASSWD: /bin/systemctl restart perfectcue-bridge
bridge ALL=(ALL) NOPASSWD: /bin/systemctl is-active perfectcue-bridge
EOF
chmod 440 "$SUDOERS_FILE"
# Validate the file — if visudo rejects it, remove it and warn
if ! visudo -cf "$SUDOERS_FILE" &>/dev/null; then
    rm -f "$SUDOERS_FILE"
    warn "sudoers rule failed validation — service control buttons will require manual sudo"
else
    info "sudoers rule written → $SUDOERS_FILE"
fi

# ── Python venv ────────────────────────────────────────────────────────
step "Creating Python virtual environment"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet evdev python-osc
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/venv"
info "Virtual environment ready  (evdev + python-osc installed)"

# ── udev rule ──────────────────────────────────────────────────────────
step "Writing udev rule"
UDEV_RULE='/etc/udev/rules.d/99-perfectcue.rules'
cat > "$UDEV_RULE" << 'EOF'
# PerfectCue HID bridge — allow input group to read all event devices
SUBSYSTEM=="input", GROUP="input", MODE="0660"
EOF
udevadm control --reload-rules
udevadm trigger
info "udev rule written → $UDEV_RULE"

# ── Systemd: bridge ────────────────────────────────────────────────────
step "Installing systemd service: $BRIDGE_SERVICE"
cat > "/etc/systemd/system/${BRIDGE_SERVICE}.service" << EOF
[Unit]
Description=PerfectCue → Companion OSC Bridge
After=network.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=${SERVICE_USER}
Group=input
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python3 ${INSTALL_DIR}/perfectcue_bridge.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${BRIDGE_SERVICE}
PrivateTmp=true
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=${INSTALL_DIR}

[Install]
WantedBy=multi-user.target
EOF
info "Bridge service unit written"

# ── Systemd: web UI ────────────────────────────────────────────────────
step "Installing systemd service: $WEB_SERVICE"
cat > "/etc/systemd/system/${WEB_SERVICE}.service" << EOF
[Unit]
Description=PerfectCue Bridge Web Config UI
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python3 ${INSTALL_DIR}/web_server.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${WEB_SERVICE}
Environment=PORT=8080

[Install]
WantedBy=multi-user.target
EOF
info "Web service unit written"

# ── Enable services ────────────────────────────────────────────────────
step "Enabling services"
systemctl daemon-reload
systemctl enable "$WEB_SERVICE"
systemctl restart "$WEB_SERVICE"
info "Web UI service started  →  http://$(hostname -I | awk '{print $1}'):8080"

systemctl enable "$BRIDGE_SERVICE"

# Only start bridge if an input device is already present
DEVICE_COUNT=$(python3 -c "
import evdev
devs = [evdev.InputDevice(p) for p in evdev.list_devices()]
print(len(devs))
" 2>/dev/null || echo "0")

if [[ "$DEVICE_COUNT" -gt 0 ]]; then
    systemctl restart "$BRIDGE_SERVICE"
    info "Bridge service started"
else
    warn "No input device detected — bridge enabled but not started."
    warn "Attach the PerfectCue via UTM USB menu, then run:"
    warn "  sudo systemctl start $BRIDGE_SERVICE"
fi

# ── Done ───────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo -e "║  ${GREEN}Installation complete!${NC}                  ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  Web UI  →  http://$(hostname -I | awk '{print $1}'):8080"
echo "  Config  →  $INSTALL_DIR/config.json"
echo "  Log     →  sudo journalctl -fu $BRIDGE_SERVICE"
echo ""
echo "  Next steps:"
echo "  1. Attach PerfectCue via UTM USB icon in the VM toolbar"
echo "  2. sudo systemctl start $BRIDGE_SERVICE"
echo "  3. Open the Web UI and configure Companion IP + key mappings"
echo ""
