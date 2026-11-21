"""LAN scan for Epson printers: subnet detection, port probe, identity confirmation."""

import concurrent.futures
import ipaddress
import socket
import struct

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Linux
    fcntl = None

import printer
import snmp

SIOCGIFADDR = 0x8915
PRINTER_PORTS = (515, 9100, 631)


def local_ipv4_interfaces():
    """Return {ifname: ip} for the host's IPv4 interfaces (Linux ioctl, no deps)."""
    result = {}
    if not fcntl:
        return result
    for _idx, name in socket.if_nameindex():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            packed = fcntl.ioctl(
                sock.fileno(), SIOCGIFADDR, struct.pack("256s", name[:15].encode())
            )
            result[name] = socket.inet_ntoa(packed[20:24])
        except OSError:
            continue
        finally:
            sock.close()
    return result


def default_interface():
    """Interface carrying the IPv4 default route (the real LAN, not a VPN or bridge)."""
    try:
        with open("/proc/net/route", "r", encoding="utf-8") as handle:
            next(handle)
            for line in handle:
                fields = line.split()
                if len(fields) > 2 and fields[1] == "00000000":
                    return fields[0]
    except (OSError, StopIteration):
        pass
    return None


def detect_subnets():
    """Candidate /24 networks, default-route LAN first, VPN/bridge interfaces last."""
    skip_prefixes = ("lo", "docker", "br-", "veth", "hassio", "tailscale", "wg", "tun", "tap", "zt", "virbr")
    primary = default_interface()
    ordered = []
    fallback = []
    for name, ip in local_ipv4_interfaces().items():
        if ip.startswith(("127.", "169.254.")):
            continue
        net = str(ipaddress.ip_network(ip + "/24", strict=False))
        if name == primary:
            ordered.append(net)
        elif name.startswith(skip_prefixes):
            continue
        else:
            fallback.append(net)
    return list(dict.fromkeys(ordered + fallback))


def _port_open(host, port, timeout):
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((host, port)) == 0
    finally:
        sock.close()


def _probe_host(host, timeout):
    if not any(_port_open(host, port, timeout) for port in PRINTER_PORTS):
        return None
    ok, status = printer.is_epson(host, timeout=max(timeout * 3, 2.0))
    if not ok:
        return None
    info = {"host": host, "status": status.get("printer-state"), "reasons": status.get("printer-state-reasons")}
    meta = snmp.snapshot(host, timeout=1.8)
    info.update({k: v for k, v in meta.items() if v is not None})
    return info


def scan(subnet=None, timeout=0.35, workers=96):
    """Scan an explicit CIDR, or the LAN behind the default route, for Epson printers.

    Without an explicit subnet the add-on probes the default-route /24 first and stops
    as soon as something answers, so a VPN or docker bridge address does not waste the run.
    """
    if subnet:
        networks = [ipaddress.ip_network(subnet, strict=False)]
    else:
        candidates = detect_subnets()
        if not candidates:
            raise RuntimeError("could not detect a local /24; enter the printer IP manually")
        networks = [ipaddress.ip_network(candidate, strict=False) for candidate in candidates[:3]]

    own = set(local_ipv4_interfaces().values())
    scanned = 0
    found = []
    used = []
    for network in networks:
        hosts = [str(h) for h in network.hosts()]
        if len(hosts) > 1022:
            hosts = hosts[:1022]
        hosts = [h for h in hosts if h not in own]
        scanned += len(hosts)
        used.append(str(network))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_probe_host, host, timeout): host for host in hosts}
            for future in concurrent.futures.as_completed(futures):
                try:
                    info = future.result()
                except Exception:
                    continue
                if info:
                    found.append(info)
        if found or subnet:
            break

    found.sort(key=lambda item: ipaddress.ip_address(item["host"]))
    return {"subnet": ", ".join(used), "scanned": scanned, "printers": found}
