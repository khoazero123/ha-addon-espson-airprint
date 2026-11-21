"""HTTP server: ingress UI + JSON API + background telemetry poller."""

import datetime
import json
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import discovery
import lpr
import printer
import snmp
import store
from mqtt_bridge import MqttBridge

APP_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(APP_DIR, "web")
OPTIONS_PATH = os.path.join(os.environ.get("DATA_DIR", "/data"), "options.json")
INGRESS_PORT = int(os.environ.get("INGRESS_PORT", "8099"))

_lock = threading.Lock()


def load_options():
    try:
        with open(OPTIONS_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


OPTIONS = load_options()
STATE = store.load()


def log(message):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def local_tz():
    """Fixed-offset local time: the container has no tzdata, the printer has no clock."""
    hours = OPTIONS.get("utc_offset")
    if hours is None:
        hours = int(os.environ.get("LOCAL_UTC_OFFSET", "7"))
    return datetime.timezone(datetime.timedelta(hours=float(hours)))


def local_now():
    return datetime.datetime.now(datetime.timezone.utc).astimezone(local_tz())


def now_iso():
    return local_now().isoformat(timespec="seconds")


def refresh_state(printer_ip=None):
    """Poll the printer once and update derived timestamps."""
    ip = printer_ip or STATE.get("printer_ip")
    if not ip:
        return STATE
    status = printer.get_status(ip)
    meta = snmp.snapshot(ip, timeout=1.8)
    with _lock:
        if status:
            STATE["printer_state"] = status.get("printer-state")
            STATE["printer_reasons"] = status.get("printer-state-reasons")
            STATE["reachable"] = True
        else:
            STATE["reachable"] = False
        pages = meta.get("pages_total")
        if pages is not None:
            previous = STATE.get("pages_total")
            if previous is not None and pages > previous:
                STATE["last_print"] = now_iso()
                store.add_history(
                    STATE,
                    {"at": now_iso(), "event": "print", "pages": pages - previous,
                     "source": "counter"},
                )
            STATE["pages_total"] = pages
        for key, value in (("marks_total", meta.get("marks_total")),
                           ("serial", meta.get("serial")),
                           ("model", meta.get("model")),
                           ("uptime_ticks", meta.get("uptime_ticks"))):
            if value is not None:
                STATE[key] = value
        STATE["last_poll"] = now_iso()
        store.save(STATE)
    return STATE


def run_action(action, printer_ip=None):
    ip = printer_ip or STATE.get("printer_ip")
    if not ip:
        raise RuntimeError("no printer configured")
    result = lpr.send_job(ip, action, now=local_now())
    with _lock:
        key = "last_clean" if action == "head_clean" else "last_nozzle_check"
        STATE[key] = result["timestamp"]
        if action == "nozzle_check":
            STATE["last_print"] = result["timestamp"]
        store.add_history(
            STATE,
            {"at": result["timestamp"], "event": action, "bytes": result["data_bytes"],
             "source": "job"},
        )
        store.save(STATE)
    log(f"{action} job sent to {ip} ({result['data_bytes']} B)")
    if BRIDGE:
        BRIDGE.publish_state(STATE)
    threading.Timer(3.0, refresh_state).start()
    return result


def public_state():
    with _lock:
        snapshot = dict(STATE)
    return {
        "settings": {
            "printer_ip": snapshot.get("printer_ip") or "",
            "poll_interval": OPTIONS.get("poll_interval", 60),
            "mqtt_enabled": bool(OPTIONS.get("mqtt_enabled")),
            "scan_subnet": OPTIONS.get("scan_subnet") or "",
        },
        "printer": {
            "configured": bool(snapshot.get("printer_ip")),
            "reachable": snapshot.get("reachable"),
            "state": snapshot.get("printer_state"),
            "reasons": snapshot.get("printer_reasons"),
            "model": snapshot.get("model"),
            "serial": snapshot.get("serial"),
            "uptime_ticks": snapshot.get("uptime_ticks"),
        },
        "usage": {
            "pages_total": snapshot.get("pages_total"),
            "marks_total": snapshot.get("marks_total"),
            "last_print": snapshot.get("last_print"),
            "last_clean": snapshot.get("last_clean"),
            "last_nozzle_check": snapshot.get("last_nozzle_check"),
            "last_poll": snapshot.get("last_poll"),
        },
        "history": snapshot.get("history", [])[:10],
        "server_time": now_iso(),
    }


BRIDGE = None


def mqtt_command(action):
    try:
        run_action(action)
    except Exception as exc:  # noqa: BLE001 - report back over MQTT state
        log(f"MQTT action {action} failed: {exc}")


def poller():
    interval = max(int(OPTIONS.get("poll_interval") or 60), 15)
    while True:
        try:
            if STATE.get("printer_ip"):
                refresh_state()
                if BRIDGE:
                    BRIDGE.publish_state(STATE)
        except Exception:  # noqa: BLE001 - keep polling after transient errors
            log("poller error: " + traceback.format_exc(limit=2))
        threading.Event().wait(interval)


class Handler(BaseHTTPRequestHandler):
    server_version = "epson_printer_tools"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, payload, content_type="application/json"):
        body = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json")

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return {}

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/api/state", "/state"):
            return self._json(200, public_state())
        if path in ("/healthz",):
            return self._json(200, {"ok": True})
        if path in ("/", "/index.html") or not path.startswith("/api"):
            return self._serve_index()
        return self._json(404, {"error": "not found"})

    def _serve_index(self):
        try:
            with open(os.path.join(WEB_DIR, "index.html"), "rb") as handle:
                self._send(200, handle.read(), "text/html; charset=utf-8")
        except OSError:
            self._send(500, b"UI missing", "text/plain")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        body = self._body()
        try:
            if path == "/api/scan":
                subnet = body.get("subnet") or OPTIONS.get("scan_subnet") or None
                result = discovery.scan(subnet)
                log(f"scan {result['subnet']}: {len(result['printers'])} printer(s)")
                return self._json(200, result)
            if path == "/api/settings":
                ip = (body.get("printer_ip") or "").strip()
                with _lock:
                    STATE["printer_ip"] = ip
                    STATE["pages_total"] = None
                    store.save(STATE)
                log(f"printer set to {ip or '(none)'}")
                if ip:
                    threading.Thread(target=refresh_state, args=(ip,), daemon=True).start()
                return self._json(200, public_state())
            if path == "/api/action":
                action = body.get("action")
                if action not in ("nozzle_check", "head_clean"):
                    return self._json(400, {"error": "action must be nozzle_check or head_clean"})
                result = run_action(action)
                return self._json(200, {"ok": True, "result": result, "state": public_state()})
            if path == "/api/refresh":
                refresh_state()
                return self._json(200, public_state())
        except Exception as exc:  # noqa: BLE001 - surface errors to the UI
            log("request error: " + traceback.format_exc(limit=2))
            return self._json(500, {"error": str(exc)})
        return self._json(404, {"error": "not found"})


def main():
    global BRIDGE
    if STATE.get("printer_ip") == "" and OPTIONS.get("printer_ip"):
        STATE["printer_ip"] = OPTIONS["printer_ip"]
        store.save(STATE)
    log("starting on port %d, printer=%s" % (INGRESS_PORT, STATE.get("printer_ip") or "-"))
    BRIDGE = MqttBridge({**OPTIONS, "slug": os.environ.get("ADDON_SLUG", "epson_printer_tools")},
                        mqtt_command)
    if BRIDGE.start():
        log("MQTT bridge connected, discovery published")
    threading.Thread(target=poller, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", INGRESS_PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if BRIDGE:
            BRIDGE.stop()
        sys.exit(0)


if __name__ == "__main__":
    main()
