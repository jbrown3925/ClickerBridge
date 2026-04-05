# Changelog

## [Unreleased]

### Added
- GitHub repository structure with docs and scripts directories
- `docs/INSTALL.md` — full UTM + Ubuntu setup guide
- `docs/UTM_SETUP.md` — UTM VM configuration reference
- `CHANGELOG.md`
- `.gitignore`

---

## [1.0.0] — Initial Release

### Core Bridge
- `perfectcue_bridge.py` — evdev HID reader → Companion OSC sender
- Uses current Companion `/location/<page>/<row>/<col>/<action>` API (no arguments)
- Supports actions: `press`, `down`, `up`, `rotate-left`, `rotate-right`
- `device.grab()` for exclusive HID access — bridge gets all events
- `--list-devices`, `--learn`, `--verbose` CLI flags
- Writes `status.json` on every keypress for web UI polling
- Clean shutdown on SIGTERM / SIGINT

### Web Server
- `web_server.py` — single-file Python HTTP server, no dependencies beyond stdlib
- `GET /config.json` — read config
- `POST /config.json` — write config, trigger bridge restart
- `GET /status.json` — bridge runtime state
- `GET /bridge.log` — last 300 log lines
- `POST /osc` — send test OSC directly to Companion
- `POST /service` — `start` / `stop` / `restart` bridge via sudo systemctl

### Web UI (`web/index.html`)
- **Config tab** — companion IP/port, device filter, timing, service control buttons
- **Mappings tab** — live table of key→location assignments; per-row Test and Re-learn buttons
- **Learn tab** — single-shot key detection (stops after first press); assign form auto-saves
- **Activity tab** — live keypress stream, manual OSC test fire panel, bridge log viewer
- **Reference tab** — PerfectCue key map, Companion OSC API docs, UTM setup checklist
- All saves (config + mappings) sync full state before posting — no partial overwrites

### Installer (`install.sh`)
- Supports Ubuntu 24.04 LTS
- Creates `bridge` system user in `input` group
- Python 3 venv with `evdev` and `python-osc`
- udev rule: `SUBSYSTEM=="input", GROUP="input", MODE="0660"`
- sudoers rule: `bridge` user gets passwordless sudo for exactly 4 systemctl commands
- Systemd services: `perfectcue-bridge` and `perfectcue-web`
- Re-runnable: never overwrites existing `config.json`

### Configuration (`config.json`)
- Empty mappings by default — use Learn tab or `--learn` CLI to build from scratch
- Settings: `companion_ip`, `companion_port`, `device_name_filter`, `osc_press_delay_ms`, `log_level`
