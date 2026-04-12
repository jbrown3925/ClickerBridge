#!/usr/bin/env python3
"""
PerfectCue Bridge — Web Config Server
======================================
Serves the web UI and provides a simple HTTP API so the browser
can read and write config.json and read status/log files directly
on the VM — no manual SCP needed.

Endpoints:
    GET  /              → web/index.html
    GET  /config.json   → read current config
    POST /config.json   → write config (JSON body), restarts bridge service
    GET  /status.json   → bridge runtime state
    GET  /bridge.log    → last 300 lines of the rolling log
    GET  /input-devices → JSON list of evdev input devices (path, name, has_keyboard)
    POST /osc           → send a test OSC message to Companion
                          body: {"page":1,"row":0,"column":0,"action":"press"}
    POST /service       → control the bridge systemd service
                          body: {"cmd":"start"|"stop"|"restart"}

Runs on port 8080 (override with PORT env var).
"""

import json
import logging
import os
import socket
import struct
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE    = Path(__file__).parent
WEB     = BASE / "web"
CONFIG  = BASE / "config.json"
STATUS  = BASE / "status.json"
LOG     = BASE / "bridge.log"
LOG_TAIL = 300  # lines served to the browser


def list_input_devices():
    """
    Return {"devices": [...], "error": null} for the web UI.
    Each device: path, name, has_keyboard (bool or null if unknown), optional error.
    """
    try:
        import evdev
        from evdev import InputDevice, ecodes
    except ImportError:
        return {"devices": [], "error": "evdev is not installed"}

    out = []
    for p in evdev.list_devices():
        try:
            dev = InputDevice(p)
            try:
                caps = dev.capabilities()
                has_kb = ecodes.EV_KEY in caps
            except Exception:
                has_kb = None
            out.append({"path": dev.path, "name": dev.name, "has_keyboard": has_kb})
            try:
                dev.close()
            except Exception:
                pass
        except OSError as e:
            out.append({
                "path": p,
                "name": "",
                "has_keyboard": None,
                "error": str(e),
            })
        except Exception as e:
            out.append({
                "path": p,
                "name": "",
                "has_keyboard": None,
                "error": str(e),
            })
    return {"devices": out, "error": None}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s"
)
log = logging.getLogger("web")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Suppress per-request stdout noise; errors still show
        if "404" in str(args) or "500" in str(args):
            log.warning(fmt % args)

    # ── CORS + headers ─────────────────────────────────────────────────
    def _headers(self, content_type="application/json", status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.end_headers()

    def do_OPTIONS(self):
        self._headers()
        self.wfile.write(b"")

    # ── GET ────────────────────────────────────────────────────────────
    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path in ("/", "/index.html"):
            self._serve_file(WEB / "index.html", "text/html; charset=utf-8")

        elif path == "/config.json":
            self._serve_file(CONFIG, "application/json")

        elif path == "/status.json":
            if STATUS.exists():
                self._serve_file(STATUS, "application/json")
            else:
                self._headers()
                self.wfile.write(json.dumps({
                    "state": "unknown",
                    "last_key": "",
                    "last_osc": "",
                    "error": "status.json not found — bridge may not have started yet",
                    "timestamp": 0
                }).encode())

        elif path == "/bridge.log":
            if LOG.exists():
                lines = LOG.read_text(errors="replace").splitlines()
                text  = "\n".join(lines[-LOG_TAIL:])
                self._headers("text/plain; charset=utf-8")
                self.wfile.write(text.encode())
            else:
                self._headers("text/plain; charset=utf-8")
                self.wfile.write(b"(no log yet - bridge has not run)")

        elif path == "/input-devices":
            payload = list_input_devices()
            self._headers()
            self.wfile.write(json.dumps(payload).encode())

        elif path in ("/companion-variable", "/companion-diag"):
            # Proxy a Companion HTTP variable GET to avoid CORS issues.
            # Query params: ip, port, variable, ns (namespace: 'internal' or 'custom')
            # Companion API: GET http://<ip>:<port>/api/variable/<ns>/<varname>/value
            from urllib.parse import parse_qs, quote
            import urllib.request
            qs       = parse_qs(urlparse(self.path).query)
            comp_ip  = qs.get("ip",       ["127.0.0.1"])[0]
            comp_port= qs.get("port",     ["8888"])[0]
            var_name = qs.get("variable", [""])[0]
            ns       = qs.get("ns",       ["internal"])[0]

            if ns not in ("internal", "custom"):
                ns = "internal"

            # /companion-diag with no variable — test basic Companion reachability
            if path == "/companion-diag" and not var_name:
                results = []
                test_urls = [
                    f"http://{comp_ip}:{comp_port}/api/variable/internal/foo/value",
                    f"http://{comp_ip}:{comp_port}/",
                ]
                for test_url in test_urls:
                    try:
                        with urllib.request.urlopen(test_url, timeout=2) as r:
                            body = r.read().decode(errors="replace").strip()
                            results.append({"url": test_url, "status": r.status, "body": body[:200]})
                    except Exception as e:
                        results.append({"url": test_url, "error": str(e)})
                self._headers()
                self.wfile.write(json.dumps({"diag": results, "ip": comp_ip, "port": comp_port}).encode())
                return

            if not var_name:
                self._headers(status=400)
                self.wfile.write(json.dumps({"error": "missing variable param"}).encode())
                return

            # Correct Companion HTTP API paths:
            #   Module/internal variable: GET /api/variable/<connection_label>/<name>/value
            #   Custom variable:          GET /api/custom-variable/<name>/value
            if ns == "custom":
                url = f"http://{comp_ip}:{comp_port}/api/custom-variable/{quote(var_name)}/value"
            else:
                url = f"http://{comp_ip}:{comp_port}/api/variable/{ns}/{quote(var_name)}/value"
            try:
                with urllib.request.urlopen(url, timeout=1.5) as r:
                    raw  = r.read().decode(errors="replace").strip()
                    # Companion wraps the value in JSON: {"value": "OK"}
                    # Try to parse it, fall back to raw string
                    try:
                        parsed = json.loads(raw)
                        value  = parsed.get("value", raw) if isinstance(parsed, dict) else raw
                    except Exception:
                        value = raw
                self._headers()
                self.wfile.write(json.dumps({
                    "value":    value,
                    "raw":      raw,
                    "variable": var_name,
                    "ns":       ns,
                    "url":      url,
                }).encode())
            except Exception as e:
                self._headers()
                self.wfile.write(json.dumps({
                    "value":    "",
                    "variable": var_name,
                    "ns":       ns,
                    "url":      url,
                    "error":    str(e),
                }).encode())

        else:
            self._headers(status=404)
            self.wfile.write(json.dumps({"error": f"not found: {path}"}).encode())

    # ── POST ───────────────────────────────────────────────────────────
    def do_POST(self):
        path   = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)

        if path == "/config.json":
            try:
                # Validate JSON before writing
                data = json.loads(body)
                CONFIG.write_text(json.dumps(data, indent=2))
                log.info("config.json updated via web UI")

                # Attempt a non-blocking bridge restart so new settings take effect
                try:
                    subprocess.Popen(
                        ["sudo", "systemctl", "restart", "perfectcue-bridge"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    log.info("Triggered bridge service restart")
                except Exception as e:
                    log.warning(f"Could not restart bridge service: {e}")

                self._headers()
                self.wfile.write(json.dumps({"ok": True}).encode())

            except json.JSONDecodeError as e:
                self._headers(status=400)
                self.wfile.write(json.dumps({"error": f"Invalid JSON: {e}"}).encode())
            except Exception as e:
                log.error(f"Failed to write config: {e}")
                self._headers(status=500)
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        elif path == "/osc":
            try:
                data   = json.loads(body)
                pg     = int(data.get("page",   1))
                row    = int(data.get("row",    0))
                col    = int(data.get("column", 0))
                action = str(data.get("action", "press"))
                valid  = {"press", "down", "up", "rotate-left", "rotate-right"}
                if action not in valid:
                    action = "press"

                # Read companion target from config
                cfg       = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
                settings  = cfg.get("settings", {})
                comp_ip   = settings.get("companion_ip",   "127.0.0.1")
                comp_port = int(settings.get("companion_port", 12321))

                osc_addr = f"/location/{pg}/{row}/{col}/{action}"
                self._send_osc(comp_ip, comp_port, osc_addr)
                log.info(f"Test OSC sent: {osc_addr} → {comp_ip}:{comp_port}")

                self._headers()
                self.wfile.write(json.dumps({
                    "ok": True,
                    "address": osc_addr,
                    "target": f"{comp_ip}:{comp_port}"
                }).encode())

            except Exception as e:
                log.error(f"OSC send failed: {e}")
                self._headers(status=500)
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        elif path == "/service":
            try:
                data = json.loads(body) if body else {}
                cmd  = data.get("cmd", "").strip().lower()

                ALLOWED = {"start", "stop", "restart"}
                if cmd not in ALLOWED:
                    self._headers(status=400)
                    self.wfile.write(json.dumps({
                        "error": f"Invalid command '{cmd}'. Must be one of: {', '.join(ALLOWED)}"
                    }).encode())
                    return

                result = subprocess.run(
                    ["sudo", "systemctl", cmd, "perfectcue-bridge"],
                    capture_output=True, text=True, timeout=10
                )

                # Give systemd a moment then check actual state
                import time; time.sleep(0.8)
                status_result = subprocess.run(
                    ["sudo", "systemctl", "is-active", "perfectcue-bridge"],
                    capture_output=True, text=True, timeout=5
                )
                active = status_result.stdout.strip()

                log.info(f"Service command '{cmd}' → exit {result.returncode}, state={active}")

                self._headers()
                self.wfile.write(json.dumps({
                    "ok":       result.returncode == 0,
                    "cmd":      cmd,
                    "state":    active,
                    "stdout":   result.stdout.strip(),
                    "stderr":   result.stderr.strip(),
                }).encode())

            except subprocess.TimeoutExpired:
                self._headers(status=504)
                self.wfile.write(json.dumps({"error": "systemctl timed out"}).encode())
            except Exception as e:
                log.error(f"Service command failed: {e}")
                self._headers(status=500)
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        else:
            self._headers(status=404)
            self.wfile.write(json.dumps({"error": "not found"}).encode())

    # ── File helper ────────────────────────────────────────────────────
    def _serve_file(self, path: Path, content_type: str):
        if path.exists():
            self._headers(content_type)
            self.wfile.write(path.read_bytes())
        else:
            self._headers(status=404)
            self.wfile.write(json.dumps({"error": f"{path.name} not found"}).encode())

    # ── OSC send helper ────────────────────────────────────────────────
    def _send_osc(self, ip: str, port: int, address: str):
        """Send a no-argument OSC UDP packet to Companion."""
        def pad(b):
            return b + b'\x00' * (4 - len(b) % 4) if len(b) % 4 != 0 else b + b'\x00\x00\x00\x00'
        packet = pad(address.encode() + b'\x00') + pad(b',\x00')
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(packet, (ip, port))
        finally:
            sock.close()


if __name__ == "__main__":
    port   = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), Handler)
    log.info(f"PerfectCue Bridge web UI → http://0.0.0.0:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Web server stopped")
