# PerfectCue Bridge

Translates DSAN PerfectCue USB HID button presses into Bitfocus Companion
OSC commands using the current `/location/` API. Runs headless inside an
Ubuntu 24.04 VM on UTM (macOS), managed by systemd, with a web UI for
configuration and key learning.

```
PerfectCue Receiver  (USB HID keyboard)
        │
  UTM USB Passthrough  (QEMU backend required)
        │
  Ubuntu 24.04 VM
  ├── perfectcue_bridge.py   evdev → /location/ OSC
  ├── web_server.py          config UI on :8080
  └── systemd                auto-start on boot
        │
        │  UDP OSC  /location/<page>/<row>/<col>/press
        ▼
Bitfocus Companion  (macOS host or LAN machine)
```

---

## Requirements

| Component | Requirement |
|-----------|-------------|
| Host OS | macOS (Apple Silicon or Intel) |
| Hypervisor | UTM — **QEMU backend** (not Apple Virtualization) |
| Guest OS | Ubuntu Server 24.04 LTS |
| Companion | Bitfocus Companion with OSC listener enabled |

---

## Install

Copy this folder into the Ubuntu VM, then:

```bash
sudo bash install.sh
```

The installer creates a `bridge` service user, sets up a Python venv with
`evdev` and `python-osc`, writes a udev rule, and registers two systemd
services that start on boot.

---

## After Install

### 1. Attach the PerfectCue

In the UTM toolbar, click the USB icon and select the PerfectCue receiver.
The bridge service starts automatically when the device is detected.

```bash
sudo systemctl start perfectcue-bridge
sudo journalctl -fu perfectcue-bridge
```

### 2. Open the Web UI

```
http://<vm-ip>:8080
```

Find the VM IP with `ip addr show` inside the VM.

### 3. Configure Companion target

In the **Config** tab, set `companion_ip` to your Mac's IP on the UTM
host-only network (check with `ifconfig bridge100` on the Mac).
Click **Save** — the config is written to disk and the bridge restarts
automatically.

### 4. Map your buttons

Use the **Learn** tab to detect which key code each PerfectCue button sends,
then assign it to a Companion page / row / column.

---

## OSC API

The bridge uses Companion's current `/location/` API (no arguments):

```
/location/<page>/<row>/<column>/press        press and release
/location/<page>/<row>/<column>/down         press and hold
/location/<page>/<row>/<column>/up           release
/location/<page>/<row>/<column>/rotate-left  encoder left
/location/<page>/<row>/<column>/rotate-right encoder right
```

Row and column are **0-based**. On a standard 8×4 Companion grid:
columns 0–7, rows 0–3.

---

## File Layout (installed)

```
/opt/perfectcue-bridge/
├── perfectcue_bridge.py   bridge process (evdev → OSC)
├── web_server.py          HTTP server for web UI
├── config.json            settings and key mappings
├── status.json            runtime state (auto-written by bridge)
├── bridge.log             rolling log
├── venv/                  Python virtual environment
└── web/
    └── index.html         single-file web UI
```

---

## Service Commands

```bash
# Status
sudo systemctl status perfectcue-bridge
sudo systemctl status perfectcue-web

# Logs
sudo journalctl -fu perfectcue-bridge
sudo journalctl -fu perfectcue-web

# Restart after manual config edit
sudo systemctl restart perfectcue-bridge

# List detected input devices
sudo /opt/perfectcue-bridge/venv/bin/python3 \
  /opt/perfectcue-bridge/perfectcue_bridge.py --list-devices
```

---

## Troubleshooting

**USB device not detected in VM**
- Confirm UTM VM uses the QEMU backend (Apple Virtualization does not support USB passthrough)
- Attach device via UTM toolbar USB icon after the VM is running
- Run `lsusb` inside the VM to confirm it appears

**Bridge grabs keyboard, VM console stops responding**
- This is expected — `device.grab()` gives the bridge exclusive access
- Use SSH to manage the VM: `ssh user@<vm-ip>`
- Stop the bridge temporarily: `sudo systemctl stop perfectcue-bridge`

**OSC not reaching Companion**
- Set `companion_ip` to the Mac's host-only adapter IP (not `127.0.0.1`)
- Find it on the Mac: `ifconfig bridge100 | grep inet`
- Confirm Companion OSC listener is enabled: Settings → Remote Control → OSC → port 12321

**Web UI save not persisting**
- Verify `perfectcue-web` service is running
- Check the toast message — it should say "Config saved" not trigger a download
- Try `curl -X POST http://localhost:8080/config.json -d @config.json` from inside the VM
