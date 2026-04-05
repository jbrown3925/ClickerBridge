# PerfectCue Bridge

Translates DSAN PerfectCue USB HID button presses into Bitfocus Companion OSC
commands. Runs headless inside an Ubuntu 24.04 VM on UTM (macOS), managed by
systemd, with a browser-based web UI for configuration, key learning, and
live activity monitoring.

```
PerfectCue Receiver  (USB HID keyboard)
        │
  UTM USB Passthrough  (QEMU backend)
        │
  Ubuntu 24.04 VM
  ├── perfectcue_bridge.py   evdev → /location/ OSC
  ├── web_server.py          config UI + REST API  :8080
  └── systemd                auto-start on boot
        │
        │  UDP  /location/<page>/<row>/<col>/press
        ▼
Bitfocus Companion  (macOS host or LAN)
```

## Features

- **Zero-config HID reading** — bridge reads the PerfectCue as a standard
  USB keyboard via `evdev`; no custom drivers
- **Current Companion OSC API** — uses `/location/<page>/<row>/<col>/<action>`
  (press, down, up, rotate-left, rotate-right)
- **Web UI** — config editor, live keypress stream, manual OSC test fire,
  per-mapping test buttons, service start/stop/restart
- **Single-shot Learn mode** — press a clicker button once to capture its key
  code; bridge keeps running and firing OSC throughout
- **Re-learn per row** — update any mapping's key code from the Mappings table
  without touching other settings
- **Auto-save** — saving from the web UI writes `config.json` directly to the
  VM and restarts the bridge service automatically

## Requirements

| Component | Requirement |
|-----------|-------------|
| Host OS | macOS (Apple Silicon or Intel) |
| Hypervisor | UTM — **QEMU backend** (not Apple Virtualization) |
| Guest OS | Ubuntu Server 24.04 LTS |
| Companion | Bitfocus Companion with OSC listener enabled |

> **USB passthrough note:** UTM's USB sharing only works with the QEMU backend.
> If your VM was created with Apple Virtualization, USB passthrough is not
> available. Create a new VM using the Emulate/Virtualize → Linux path.

## Quick Start

### 1. Clone

```bash
git clone https://github.com/YOUR_USERNAME/perfectcue-bridge.git
```

### 2. Copy to VM

```bash
scp -r perfectcue-bridge/ user@<vm-ip>:~/
```

### 3. Install

```bash
cd ~/perfectcue-bridge
sudo bash install.sh
```

### 4. Attach PerfectCue

In the UTM toolbar, click the USB icon and select the PerfectCue receiver.
Then start the bridge:

```bash
sudo systemctl start perfectcue-bridge
```

### 5. Open Web UI

```
http://<vm-ip>:8080
```

Set `companion_ip` to your Mac's host-only adapter IP
(`ifconfig bridge100 | grep inet` on the Mac).

## OSC API

The bridge uses Companion's current `/location/` API — no arguments:

```
/location/<page>/<row>/<column>/press        press and release
/location/<page>/<row>/<column>/down         press and hold
/location/<page>/<row>/<column>/up           release
/location/<page>/<row>/<column>/rotate-left  encoder left
/location/<page>/<row>/<column>/rotate-right encoder right
```

Row and column are **0-based**. On a standard 8×4 Companion grid:
columns 0–7, rows 0–3.

## File Layout

```
perfectcue-bridge/
├── perfectcue_bridge.py   bridge process (evdev → OSC)
├── web_server.py          HTTP server (config UI + /osc + /service API)
├── install.sh             one-command installer
├── config.json            default settings (empty mappings)
├── web/
│   └── index.html         single-file web UI
└── docs/
    ├── INSTALL.md         full install guide (UTM + Ubuntu setup)
    └── UTM_SETUP.md       UTM VM configuration reference
```

After install, files live at `/opt/perfectcue-bridge/`.

## Service Commands

```bash
# Status
sudo systemctl status perfectcue-bridge
sudo systemctl status perfectcue-web

# Live log
sudo journalctl -fu perfectcue-bridge

# List detected input devices
sudo /opt/perfectcue-bridge/venv/bin/python3 \
  /opt/perfectcue-bridge/perfectcue_bridge.py --list-devices

# Restart after manual config edit
sudo systemctl restart perfectcue-bridge
```

## Web API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/config.json` | Read current config |
| `POST` | `/config.json` | Write config, restart bridge |
| `GET` | `/status.json` | Bridge runtime state |
| `GET` | `/bridge.log` | Last 300 log lines |
| `POST` | `/osc` | Send test OSC to Companion |
| `POST` | `/service` | `{"cmd":"start"\|"stop"\|"restart"}` |

## Troubleshooting

**USB device not detected in VM**
- Confirm UTM VM uses QEMU backend (not Apple Virtualization)
- Attach via UTM toolbar USB icon after VM is running
- Confirm with `lsusb` inside VM

**Bridge grabs keyboard, VM console stops responding**
- Expected — `device.grab()` gives bridge exclusive access
- Use SSH instead: `ssh user@<vm-ip>`
- Stop temporarily: `sudo systemctl stop perfectcue-bridge`

**OSC not reaching Companion**
- Set `companion_ip` to Mac's UTM host-only IP, not `127.0.0.1`
- Find it: `ifconfig bridge100 | grep inet`
- Confirm Companion OSC: Settings → Remote Control → OSC → port 12321

**Service control buttons fail**
- Ensure sudoers rule was written by installer:
  `cat /etc/sudoers.d/perfectcue-bridge`
- Re-apply: `sudo bash install.sh`

## Clock skew on fresh VM

If `apt update` fails with "Release file is not valid yet":

```bash
sudo timedatectl set-ntp true
sudo systemctl restart systemd-timesyncd
```

## License

MIT
