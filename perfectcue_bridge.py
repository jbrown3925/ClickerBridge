#!/usr/bin/env python3
"""
PerfectCue → Bitfocus Companion OSC Bridge
===========================================
Reads USB HID keyboard events from a DSAN PerfectCue receiver
passed through via UTM/VirtualBox, then sends OSC messages to
Bitfocus Companion using the current /location/ API.

OSC format used:
    /location/<page>/<row>/<column>/press   — press and release
    /location/<page>/<row>/<column>/down    — press and hold
    /location/<page>/<row>/<column>/up      — release

Usage:
    python3 perfectcue_bridge.py [--config config.json] [--learn] [--verbose]
"""

import argparse
import json
import logging
import os
import signal
import socket
import struct
import sys
import time
from pathlib import Path

# --- Dependency check ---
try:
    import evdev
    from evdev import InputDevice, ecodes, categorize
except ImportError:
    sys.exit("[ERROR] 'evdev' not found. Run: pip install evdev")

try:
    from pythonosc import udp_client
    from pythonosc.osc_message_builder import OscMessageBuilder
except ImportError:
    sys.exit("[ERROR] 'python-osc' not found. Run: pip install python-osc")

# --- Defaults ---
DEFAULT_CONFIG = Path(__file__).parent / "config.json"
LOG_FILE = Path(__file__).parent / "bridge.log"

DEFAULT_SETTINGS = {
    "companion_ip": "127.0.0.1",
    "companion_port": 12321,
    "device_name_filter": "DSAN",
    "osc_press_delay_ms": 50,
    "log_level": "INFO"
}

# Key mappings are loaded exclusively from config.json.
# Use the web UI Learn tab or --learn CLI flag to create mappings.
# An empty mapping set is valid — unmapped keys are logged but ignored.
DEFAULT_MAPPINGS = {}


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    """Load config.json, creating it with defaults if missing."""
    if not path.exists():
        config = {
            "settings": DEFAULT_SETTINGS,
            "mappings": DEFAULT_MAPPINGS
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(config, f, indent=2)
        print(f"[INFO] Created default config at {path}")
    else:
        with open(path) as f:
            config = json.load(f)

    # Merge any missing default settings
    for k, v in DEFAULT_SETTINGS.items():
        config["settings"].setdefault(k, v)

    return config


def save_config(path: Path, config: dict):
    with open(path, "w") as f:
        json.dump(config, f, indent=2)


# ---------------------------------------------------------------------------
# Device discovery
# ---------------------------------------------------------------------------

def find_device(name_filter: str) -> InputDevice | None:
    """Find first evdev device whose name contains name_filter (case-insensitive)."""
    devices = [InputDevice(p) for p in evdev.list_devices()]
    for dev in devices:
        if name_filter.lower() in dev.name.lower():
            return dev
    return None


def list_devices():
    """Print all available input devices."""
    devices = [InputDevice(p) for p in evdev.list_devices()]
    if not devices:
        print("  (no input devices found — check group membership or USB passthrough)")
        return
    for dev in devices:
        caps = dev.capabilities()
        has_keys = ecodes.EV_KEY in caps
        print(f"  {dev.path:25s}  {dev.name}  {'[keyboard]' if has_keys else ''}")


# ---------------------------------------------------------------------------
# OSC helpers
# ---------------------------------------------------------------------------

def build_osc_packet(address: str, value: int) -> bytes:
    """Build a raw OSC UDP packet with a single int argument (legacy use)."""
    def pad(s: bytes) -> bytes:
        return s + b'\x00' * (4 - len(s) % 4) if len(s) % 4 != 0 else s + b'\x00\x00\x00\x00'

    addr_bytes = pad(address.encode() + b'\x00')
    type_tag = pad(b',i\x00')
    value_bytes = struct.pack('>i', value)
    return addr_bytes + type_tag + value_bytes


def build_osc_packet_no_args(address: str) -> bytes:
    """Build a raw OSC UDP packet with no arguments (used by /location/ API)."""
    def pad(s: bytes) -> bytes:
        return s + b'\x00' * (4 - len(s) % 4) if len(s) % 4 != 0 else s + b'\x00\x00\x00\x00'

    addr_bytes = pad(address.encode() + b'\x00')
    type_tag = pad(b',\x00')
    return addr_bytes + type_tag


class OSCSender:
    VALID_ACTIONS = {"press", "down", "up", "rotate-left", "rotate-right"}

    def __init__(self, ip: str, port: int, press_delay_ms: int = 50):
        self.ip = ip
        self.port = port
        self.delay = press_delay_ms / 1000.0
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._client = udp_client.SimpleUDPClient(ip, port)
            self._use_pythonosc = True
        except Exception:
            self._client = None
            self._use_pythonosc = False

    def trigger(self, page: int, row: int, column: int, action: str = "press") -> str:
        """
        Send a /location/ OSC command to Companion.
        Returns the OSC address used (for logging).

        action: "press"        → single no-arg message (Companion handles down+up)
                "down"         → hold button
                "up"           → release button
                "rotate-left"  → encoder rotate left
                "rotate-right" → encoder rotate right
        """
        if action not in self.VALID_ACTIONS:
            action = "press"

        address = f"/location/{page}/{row}/{column}/{action}"
        # press/down/up/rotate-* take no arguments in the new API
        self._send_no_args(address)
        return address

    def _send_no_args(self, address: str):
        """Send an OSC message with no arguments."""
        if self._use_pythonosc:
            builder = OscMessageBuilder(address=address)
            msg = builder.build()
            self._client.send(msg)
        else:
            self._sock.sendto(build_osc_packet_no_args(address), (self.ip, self.port))

    def _send_int(self, address: str, value: int):
        """Send an OSC message with a single integer argument (legacy / style commands)."""
        if self._use_pythonosc:
            builder = OscMessageBuilder(address=address)
            builder.add_arg(value, arg_type='i')
            msg = builder.build()
            self._client.send(msg)
        else:
            packet = build_osc_packet(address, value)
            self._sock.sendto(packet, (self.ip, self.port))

    def close(self):
        self._sock.close()


# ---------------------------------------------------------------------------
# Learn mode
# ---------------------------------------------------------------------------

def learn_mode(device: InputDevice, config_path: Path, config: dict):
    """
    Interactive learn mode: press each PerfectCue button and assign it to a
    Companion location. Updates config.json in place.
    """
    print("\n╔══════════════════════════════════════════╗")
    print("║         LEARN MODE — PerfectCue          ║")
    print("╚══════════════════════════════════════════╝")
    print("Press each button on the clicker when prompted.")
    print("Enter the Companion page, row, column, and action.")
    print("Press Ctrl+C to exit learn mode.\n")

    mappings = config.get("mappings", {})
    device.grab()
    try:
        for event in device.read_loop():
            if event.type == ecodes.EV_KEY:
                key_event = categorize(event)
                if key_event.keystate == key_event.key_down:
                    key_name = ecodes.KEY[event.code] if event.code in ecodes.KEY else f"KEY_{event.code}"
                    print(f"\n  ► Detected key: {key_name}")
                    label  = input("    Label (e.g. Forward): ").strip()
                    page   = input("    Companion page   [1]: ").strip() or "1"
                    row    = input("    Companion row    [0]: ").strip() or "0"
                    column = input("    Companion column [0]: ").strip() or "0"
                    action = input("    Action (press/down/up) [press]: ").strip() or "press"
                    if action not in OSCSender.VALID_ACTIONS:
                        action = "press"
                    mappings[key_name] = {
                        "label":  label,
                        "page":   int(page),
                        "row":    int(row),
                        "column": int(column),
                        "action": action,
                    }
                    config["mappings"] = mappings
                    save_config(config_path, config)
                    osc_addr = f"/location/{page}/{row}/{column}/{action}"
                    print(f"    ✓ Saved: {key_name} → {osc_addr}")
                    another = input("    Map another button? [Y/n]: ").strip().lower()
                    if another == 'n':
                        break
    except KeyboardInterrupt:
        pass
    finally:
        device.ungrab()

    print(f"\n[INFO] Learn mode complete. Config saved to {config_path}")


# ---------------------------------------------------------------------------
# Status file (read by web UI)
# ---------------------------------------------------------------------------

STATUS_FILE = Path(__file__).parent / "status.json"
_status_seq = 0   # monotonic counter — increments on every keypress

def write_status(state: str, last_key: str = "", last_osc: str = "", error: str = ""):
    global _status_seq
    if last_key:          # only increment on real key events
        _status_seq += 1
    status = {
        "state":    state,
        "last_key": last_key,
        "last_osc": last_osc,
        "error":    error,
        "seq":      _status_seq,
        "timestamp": time.time()
    }
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(status, f)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main bridge loop
# ---------------------------------------------------------------------------

def run_bridge(config: dict, config_path: Path, verbose: bool):
    settings = config["settings"]
    mappings = config.get("mappings", DEFAULT_MAPPINGS)

    logging.basicConfig(
        level=getattr(logging, settings.get("log_level", "INFO")),
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout)
        ]
    )
    log = logging.getLogger("bridge")

    log.info("PerfectCue OSC Bridge starting...")
    log.info(f"  Companion target : {settings['companion_ip']}:{settings['companion_port']}")
    log.info(f"  Device filter    : '{settings['device_name_filter']}'")
    log.info(f"  Key mappings     : {len(mappings)} mapped")

    write_status("starting")

    # Discover device
    device = find_device(settings["device_name_filter"])
    if device is None:
        log.error("No matching input device found. Use --list-devices to debug.")
        write_status("error", error="No matching input device found")
        sys.exit(1)

    log.info(f"  Device           : {device.name} ({device.path})")

    osc = OSCSender(
        settings["companion_ip"],
        settings["companion_port"],
        settings.get("osc_press_delay_ms", 50)
    )

    # Grab device so events don't leak to the host
    device.grab()
    write_status("running")
    log.info("Bridge running. Ctrl+C to stop.\n")

    # Handle clean shutdown
    def shutdown(sig, frame):
        log.info("Shutting down...")
        write_status("stopped")
        try:
            device.ungrab()
        except Exception:
            pass
        osc.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        for event in device.read_loop():
            if event.type != ecodes.EV_KEY:
                continue
            key_event = categorize(event)
            # Only act on key-down (state 1); ignore hold (2) and up (0)
            if key_event.keystate != key_event.key_down:
                continue

            key_name = ecodes.KEY.get(event.code, f"KEY_{event.code}")
            mapping = mappings.get(key_name)

            if mapping:
                page   = mapping["page"]
                row    = mapping.get("row", 0)
                column = mapping.get("column", 0)
                action = mapping.get("action", "press")
                label  = mapping.get("label", key_name)
                osc_addr = osc.trigger(page, row, column, action)
                log.info(f"  {key_name:20s} → {label:15s} → {osc_addr}")
                write_status("running", last_key=key_name, last_osc=osc_addr)
            else:
                if verbose:
                    log.debug(f"  {key_name:20s} → (unmapped)")
                write_status("running", last_key=key_name, last_osc="(unmapped)")

    except OSError as e:
        log.error(f"Device read error: {e}")
        write_status("error", error=str(e))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="PerfectCue → Companion OSC Bridge"
    )
    parser.add_argument("--config",  default=str(DEFAULT_CONFIG), help="Path to config.json")
    parser.add_argument("--learn",   action="store_true", help="Run interactive key-learn mode")
    parser.add_argument("--verbose", action="store_true", help="Log unmapped keys")
    parser.add_argument("--list-devices", action="store_true", help="List available input devices and exit")
    args = parser.parse_args()

    if args.list_devices:
        print("\nAvailable input devices:")
        list_devices()
        sys.exit(0)

    config_path = Path(args.config)
    config = load_config(config_path)

    if args.learn:
        settings = config["settings"]
        device = find_device(settings["device_name_filter"])
        if device is None:
            print("[ERROR] No device matched device_name_filter. Check USB passthrough and --list-devices.")
            sys.exit(1)
        learn_mode(device, config_path, config)
    else:
        run_bridge(config, config_path, args.verbose)


if __name__ == "__main__":
    main()
