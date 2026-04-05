# Install Guide

**Platform:** Ubuntu Server 24.04 LTS · UTM (QEMU backend) · macOS host

---

## Prerequisites

- macOS host with [UTM](https://mac.getutm.app/) installed
- Ubuntu Server 24.04 LTS installed in a UTM VM using the **QEMU backend**
- Bitfocus Companion running on the Mac with OSC listener enabled

---

## Part 1 — UTM VM Configuration

> **Critical:** USB passthrough in UTM requires the **QEMU backend**.
> Apple Virtualization does not support USB sharing.

### 1.1 Verify QEMU Backend

In UTM, right-click the VM → **Edit** → click **QEMU** in the sidebar.
Confirm backend shows **QEMU**. If it shows Apple Virtualization, create
a new VM via the Emulate/Virtualize → Linux path.

### 1.2 Enable USB Sharing

1. VM Edit → **Input**
2. Check **Enable USB Sharing**
3. Set **Maximum Shared USB Devices** to `3`
4. **USB Version** → USB 3.0 (xHCI)
5. Save

### 1.3 Network — Host-Only Adapter

1. VM Edit → **Network**
2. **Network Mode** → **Host Only**
3. Optionally add a second device set to **Shared Network (NAT)** for internet access
4. Save

### 1.4 Find the VM IP

```bash
ip addr show
```

Look for `192.168.64.x` on the host-only interface. Note this IP — you'll
use it to open the web UI from your Mac.

---

## Part 2 — Ubuntu Setup

### 2.1 Fix Clock (if needed)

If `apt update` fails with "Release file is not valid yet":

```bash
sudo timedatectl set-ntp true
sudo systemctl restart systemd-timesyncd
sleep 5 && timedatectl status
```

Look for `System clock synchronized: yes`.

### 2.2 Update and install SSH

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
```

From your Mac you can now SSH in:

```bash
ssh user@192.168.64.x
```

---

## Part 3 — Install the Bridge

### 3.1 Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/perfectcue-bridge.git
cd perfectcue-bridge
```

Or copy the files via SCP from your Mac:

```bash
scp -r perfectcue-bridge/ user@192.168.64.x:~/
```

### 3.2 Run the installer

```bash
sudo bash install.sh
```

The installer:
- Installs Python system packages
- Creates a `bridge` service user in the `input` group
- Writes a udev rule for HID device permissions
- Writes a sudoers rule so the web UI can control the service
- Copies files to `/opt/perfectcue-bridge/`
- Creates a Python venv with `evdev` and `python-osc`
- Registers and enables two systemd services

### 3.3 Verify services

```bash
sudo systemctl status perfectcue-web     # should be active
sudo systemctl status perfectcue-bridge  # may be waiting for USB device
```

---

## Part 4 — USB Passthrough

1. Plug the PerfectCue receiver into your Mac
2. Start the Ubuntu VM in UTM
3. Click the **USB icon** in the UTM toolbar
4. Select the PerfectCue receiver from the dropdown
5. Confirm inside the VM:

```bash
lsusb
```

You should see a DSAN entry. Then start the bridge:

```bash
sudo systemctl start perfectcue-bridge
sudo journalctl -fu perfectcue-bridge
```

Press a button on the PerfectCue. You should see:

```
KEY_RIGHT   → Forward   → /location/1/0/0/press
```

---

## Part 5 — Web UI

Open in your Mac browser:

```
http://192.168.64.x:8080
```

### Config tab

Set `companion_ip` to your Mac's UTM host-only IP:

```bash
# Run on your Mac
ifconfig bridge100 | grep "inet "
```

Click **Save** — config is written to disk and the bridge restarts automatically.

### Learn tab

1. Click **Start Listening**
2. Press one button on the PerfectCue — listening stops automatically
3. Enter label, page, row, column, action
4. Click **Assign Key** — saved and bridge restarted

### Mappings tab

- **⟳ Re-learn** — update a row's key code by pressing the clicker
- **▶ Test** — send that mapping's OSC command immediately

### Activity tab

- **Live Key Events** — real-time stream of clicker presses
- **Manual Test Fire** — send any OSC address to Companion directly

---

## Part 6 — Companion OSC Setup

1. Open Bitfocus Companion
2. **Settings** → **Remote Control** → enable **OSC**
3. Port: `12321`
4. Press a mapped button — the Companion button should flash

---

## Service Commands

```bash
# Status
sudo systemctl status perfectcue-bridge
sudo systemctl status perfectcue-web

# Live log
sudo journalctl -fu perfectcue-bridge

# Restart after manual config edit
sudo systemctl restart perfectcue-bridge

# List detected input devices
sudo /opt/perfectcue-bridge/venv/bin/python3 \
  /opt/perfectcue-bridge/perfectcue_bridge.py --list-devices
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| No device in `lsusb` | Re-attach via UTM USB menu; check QEMU backend |
| VM console keyboard stops working | Bridge grabs device — use SSH instead |
| OSC not reaching Companion | Check `companion_ip` is Mac's host-only IP, not `127.0.0.1` |
| Web UI save triggers download | Old version — redeploy `web/index.html` |
| Service control buttons fail | Re-run `sudo bash install.sh` to write sudoers rule |
| `apt` clock error on fresh VM | Run `sudo timedatectl set-ntp true` |
