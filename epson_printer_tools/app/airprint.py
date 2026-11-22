"""AirPrint bridge: expose the LAN printer through CUPS (IPP) + mDNS/DNS-SD.

CUPS renders the job locally with the Epson ESC/P-R driver, then relays it to the
printer's raw port 9100. The queue and the advertisement live inside this add-on, so
no separate print server is involved.
"""

import hashlib
import os
import re
import shutil
import socket
import subprocess
import threading
import time

CUPS_PORT = 631
AVAHI_CONF = "/etc/avahi/avahi-daemon.conf"
DRIVER = "/usr/lib/cups/driver/escpr"
PPD_DIR = os.path.join(os.environ.get("DATA_DIR", "/data"), "airprint")
DEFAULT_QUEUE = "L8050"
# The L8050 ships with no own PPD in escpr 1.7.x; the L805 Series PPD is the
# ESC/P-R model Epson's own driver maps a L8050 to, verified on real hardware.
MODEL_HINTS = ("L8050", "L805 Series", "L805", "ET-1810", "L18050")
MONO_PRESET = ('*APPrinterPreset Gray_with_Paper_Auto-Detect/Black and White: '
               '"*Ink MONO com.apple.print.preset.graphicsType General '
               'com.apple.print.preset.quality mid '
               'com.apple.print.preset.output-mode monochrome"')
COLOR_PRESET = ('*APPrinterPreset Color_with_Paper_Auto-Detect/Color: '
                '"*Ink COLOR com.apple.print.preset.graphicsType General '
                'com.apple.print.preset.quality mid '
                'com.apple.print.preset.output-mode color"')

_lock = threading.Lock()
STATE = {
    "available": False,
    "enabled": False,
    "cupsd": False,
    "queue": None,
    "device_uri": None,
    "ipp_uri": None,
    "info": None,
    "location": None,
    "error": None,
    "updated": None,
}


def _run(cmd, timeout=30):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)


def available():
    return os.path.exists("/usr/sbin/cupsd") and shutil.which("lpadmin") is not None


def cupsd_up(host="127.0.0.1"):
    sock = socket.socket()
    sock.settimeout(0.4)
    try:
        sock.connect((host, CUPS_PORT))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _proc_running(marker):
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as handle:
                cmd = handle.read().replace(b"\x00", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if marker in cmd:
            return True
    return False


def start_dbus():
    """CUPS talks to avahi over the system bus, so the bus has to exist first."""
    os.makedirs("/run/dbus", exist_ok=True)
    if os.path.exists("/run/dbus/system_bus_socket"):
        return True
    os.makedirs("/var/lib/dbus", exist_ok=True)
    if not os.path.exists("/var/lib/dbus/machine-id"):
        try:
            with open("/etc/machine-id", "r", encoding="utf-8") as src, \
                 open("/var/lib/dbus/machine-id", "w", encoding="utf-8") as dst:
                dst.write(src.read().strip() + "\n")
        except OSError:
            with open("/var/lib/dbus/machine-id", "w", encoding="utf-8") as dst:
                dst.write(hashlib.md5(str(time.time()).encode()).hexdigest() + "\n")
    _run(["dbus-daemon", "--system", "--fork"])
    for _ in range(20):
        if os.path.exists("/run/dbus/system_bus_socket"):
            return True
        time.sleep(0.2)
    return False


def configure_avahi(host_name, iface=None):
    host_name = re.sub(r"[^A-Za-z0-9-]+", "-", host_name or "epson-airprint").strip("-").lower()
    host_name = host_name or "epson-airprint"
    iface_line = f"allow-interfaces={iface}\n" if iface else ""
    conf = (
        "[server]\n"
        f"host-name={host_name}\n"
        f"{iface_line}"
        "use-ipv4=yes\n"
        "use-ipv6=no\n"
        "enable-dbus=yes\n"
        "ratelimit-interval-usec=1000000\n"
        "ratelimit-burst=1000\n"
        "\n[wide-area]\nenable-wide-area=no\n"
        "\n[publish]\ndisable-publishing=no\ndisable-user-service-publishing=no\n"
    )
    os.makedirs("/etc/avahi", exist_ok=True)
    try:
        with open(AVAHI_CONF, "r", encoding="utf-8") as handle:
            if handle.read() == conf:
                return host_name
    except OSError:
        pass
    with open(AVAHI_CONF, "w", encoding="utf-8") as handle:
        handle.write(conf)
    return host_name


def start_avahi(host_name="epson-airprint", iface=None):
    if not shutil.which("avahi-daemon"):
        return False, "avahi-daemon missing"
    if _proc_running("avahi-daemon"):
        return True, None
    configure_avahi(host_name, iface)
    os.makedirs("/run/avahi-daemon", exist_ok=True)
    code, out = _run(["avahi-daemon", "--daemonize", "--no-chroot"])
    for _ in range(20):
        if _proc_running("avahi-daemon"):
            return True, None
        time.sleep(0.25)
    return False, (out.strip()[:200] or f"exit {code}")


def _kill_cupsd():
    try:
        with open("/run/cups/cupsd.pid", "r", encoding="utf-8") as handle:
            pid = int(handle.read().strip())
        os.kill(pid, 15)
    except (OSError, ValueError):
        return False
    for _ in range(30):
        if not cupsd_up():
            return True
        time.sleep(0.1)
    return not cupsd_up()


def _restart_cupsd():
    _kill_cupsd()
    return start_cupsd()


def start_cupsd():
    if cupsd_up():
        return True
    os.makedirs("/run/cups", exist_ok=True)
    _run(["/usr/sbin/cupsd"])
    for _ in range(24):
        if cupsd_up():
            return True
        time.sleep(0.25)
    return False


def _ppd_path(queue):
    os.makedirs(PPD_DIR, exist_ok=True)
    return os.path.join(PPD_DIR, f"{queue}.ppd")


def _driver_uri(hints=MODEL_HINTS):
    if not os.path.exists(DRIVER):
        return None
    code, out = _run([DRIVER, "list"])
    if code != 0 or not out.strip():
        return None
    candidates = []
    for line in out.splitlines():
        parts = [chunk.strip() for chunk in line.split('"') if chunk.strip()]
        if not parts or "escpr:" not in parts[0]:
            continue
        if parts[0].startswith("drv:///"):
            parts[0] = parts[0][len("drv:///"):]
        label = parts[1] if len(parts) > 1 else ""
        candidates.append((parts[0], label))
    for hint in hints:
        low = hint.lower()
        for uri, label in candidates:
            if low in label.lower() or low in uri.lower():
                return uri
    return None


def ensure_ppd(queue):
    path = _ppd_path(queue)
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        with open(path, "r", encoding="utf-8") as handle:
            current = handle.read()
        if MONO_PRESET in current and COLOR_PRESET in current:
            return path
    uri = _driver_uri()
    if not uri:
        return None
    code, out = _run([DRIVER, "cat", uri])
    if code != 0 or len(out) < 500:
        return None
    if "*Ink MONO/" not in out or "*Ink COLOR/" not in out:
        return None
    marker = "*CloseUI: *Ink\n"
    if out.count(marker) != 1:
        return None
    out = out.replace(marker, marker + MONO_PRESET + "\n" + COLOR_PRESET + "\n", 1)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(out)
    return path

def _queue_has_mono_preset(queue):
    try:
        with open(f"/etc/cups/ppd/{queue}.ppd", "r", encoding="utf-8") as handle:
            return MONO_PRESET in handle.read()
    except OSError:
        return False


def _queue_exists(queue):
    code, _ = _run(["lpstat", "-p", queue], timeout=15)
    return code == 0


def _queue_device(queue):
    code, out = _run(["lpstat", "-v", queue], timeout=15)
    if code != 0:
        return None
    for line in out.splitlines():
        if "device for" in line and ":" in line:
            return line.split(":", 1)[1].strip()
    return None


def _queue_accepting(queue):
    code, out = _run(["lpstat", "-a", queue], timeout=15)
    return code == 0 and "not accepting" not in out.lower()


def sync(printer_ip, queue=DEFAULT_QUEUE, info=None, location=None):
    """Create/refresh the CUPS queue and the mDNS advertisement for printer_ip."""
    queue = (queue or DEFAULT_QUEUE).strip() or DEFAULT_QUEUE
    info = (info or "Epson EcoTank L8050").strip()
    location = (location or "").strip()
    with _lock:
        STATE["queue"] = queue
        STATE["info"] = info
        STATE["location"] = location or None
        STATE["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        STATE.setdefault("dbus", False)
        STATE.setdefault("avahi", False)

        if not available():
            STATE.update(available=False, cupsd=False, enabled=False,
                         error="CUPS not installed in this image")
            return dict(STATE)
        STATE["available"] = True

        if not printer_ip:
            STATE.update(enabled=False, error="no printer IP configured")
            return dict(STATE)

        avahi_was_running = _proc_running("avahi-daemon")
        bus_ok = start_dbus()
        try:
            import discovery  # the LAN interface with the default route
            iface = discovery.default_interface()
        except Exception:  # noqa: BLE001 - publish on every interface if unknown
            iface = None
        avahi_ok, avahi_err = start_avahi(_avahi_host(queue), iface)
        STATE["dbus"] = bool(bus_ok)
        STATE["avahi"] = bool(avahi_ok)
        if not avahi_ok:
            STATE["error"] = f"mDNS unavailable: {avahi_err or 'dbus not started'}"
        if not cupsd_up():
            if not start_cupsd():
                STATE.update(cupsd=False, enabled=False, error="cupsd did not start")
                return dict(STATE)
        elif avahi_ok and not avahi_was_running:
            # cupsd only looks for avahi at startup: restart it once the daemon is up
            _restart_cupsd()
        STATE["cupsd"] = True

        ppd = ensure_ppd(queue)
        if not ppd:
            STATE.update(enabled=False, error="ESC/P-R PPD not available (printer-driver-escpr)")
            return dict(STATE)

        uri = f"socket://{printer_ip}:9100"
        if _queue_exists(queue):
            current = _queue_device(queue)
            if current and current != uri:
                _run(["lpadmin", "-p", queue, "-v", uri])
            if not _queue_has_mono_preset(queue):
                code, out = _run(["lpadmin", "-p", queue, "-P", ppd])
                if code != 0:
                    STATE.update(enabled=False, error=f"PPD update failed: {out.strip()[:300]}")
                    return dict(STATE)
        else:
            code, out = _run(["lpadmin", "-p", queue, "-E", "-v", uri, "-P", ppd])
            if code != 0:
                STATE.update(enabled=False, error=f"lpadmin failed: {out.strip()[:300]}")
                return dict(STATE)

        _run(["lpadmin", "-p", queue, "-E", "-D", info, "-L", location,
              "-o", "printer-is-shared=true", "-o", "printer-error-policy=retry-job"])
        _run(["cupsctl", "--share-printers", "--remote-admin"])
        if not _queue_accepting(queue):
            _run(["cupsaccept", queue])
            _run(["cupsenable", queue])

        STATE.update(enabled=_queue_accepting(queue), device_uri=uri,
                     ipp_uri=f"ipp://{{host}}:{CUPS_PORT}/printers/{queue}", error=None)
        return dict(STATE)


def _avahi_host(queue):
    return re.sub(r"[^A-Za-z0-9-]+", "-", (queue or DEFAULT_QUEUE)).strip("-").lower() or "epson-airprint"


def status(host=None):
    with _lock:
        snapshot = dict(STATE)
    if snapshot.get("available"):
        snapshot["cupsd"] = cupsd_up()
    if snapshot.get("queue"):
        snapshot["ipp_uri"] = (snapshot.get("ipp_uri") or "").replace("{host}", host or "")
    return snapshot


def disable(queue=DEFAULT_QUEUE):
    queue = (queue or DEFAULT_QUEUE).strip() or DEFAULT_QUEUE
    with _lock:
        if available() and cupsd_up():
            _run(["lpadmin", "-x", queue])
        STATE.update(enabled=False, device_uri=None, ipp_uri=None, error=None)
        return dict(STATE)
