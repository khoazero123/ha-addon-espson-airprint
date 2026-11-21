"""Minimal SNMPv1 GET client (stdlib only) for Pratt Printer-MIB counters."""

import socket

OID_LIFE_COUNT = "1.3.6.1.2.1.43.10.2.1.4.1.1"     # prtMarkerLifeCount, total pages
OID_MARK_COUNT = "1.3.6.1.2.1.43.10.2.1.5.1.1"     # prtMarkerMarkLifeCount
OID_SERIAL = "1.3.6.1.2.1.43.5.1.1.17.1"           # prtGeneralSerialNumber
OID_MODEL = "1.3.6.1.2.1.25.3.2.1.3.1"             # hrDeviceDescr
OID_UPTIME = "1.3.6.1.2.1.1.3.0"                   # sysUpTime (timeticks)

_TAG_INT = 0x02
_TAG_OCTETS = 0x04
_TAG_NULL = 0x05
_TAG_OID = 0x06
_TAG_COUNTER = 0x41
_TAG_TIMETICKS = 0x43


def _encode_len(n):
    if n < 0x80:
        return bytes([n])
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def _tlv(tag, value):
    return bytes([tag]) + _encode_len(len(value)) + value


def _encode_int(value):
    if value == 0:
        body = b"\x00"
    else:
        body = value.to_bytes((value.bit_length() + 8) // 8, "big", signed=True)
    return _tlv(_TAG_INT, body)


def _encode_oid(oid):
    parts = [int(p) for p in oid.split(".")]
    body = bytes([parts[0] * 40 + parts[1]])
    for part in parts[2:]:
        chunk = [part & 0x7F]
        part >>= 7
        while part:
            chunk.append((part & 0x7F) | 0x80)
            part >>= 7
        body += bytes(reversed(chunk))
    return _tlv(_TAG_OID, body)


def _read_tlv(buf, pos):
    tag = buf[pos]
    pos += 1
    length = buf[pos]
    pos += 1
    if length & 0x80:
        count = length & 0x7F
        length = int.from_bytes(buf[pos:pos + count], "big")
        pos += count
    return tag, buf[pos:pos + length], pos + length


def _decode_int(body):
    return int.from_bytes(body, "big", signed=True)


def get(host, oid, community="public", timeout=3.0, retries=1):
    """Return the value of one OID, or None when the agent has no answer."""
    request_id = 0x4E4554
    varbind = _tlv(0x30, _encode_oid(oid) + _tlv(_TAG_NULL, b""))
    pdu = _tlv(0xA0, _encode_int(request_id) + _encode_int(0) + _encode_int(0) + _tlv(0x30, varbind))
    packet = _tlv(0x30, _encode_int(0) + _tlv(_TAG_OCTETS, community.encode()) + pdu)

    for _ in range(retries + 1):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(packet, (host, 161))
            data, _addr = sock.recvfrom(4096)
        except OSError:
            continue
        finally:
            sock.close()
        try:
            _tag, msg, _end = _read_tlv(data, 0)
            pos = 0
            _t, _version, pos = _read_tlv(msg, pos)
            _t, _comm, pos = _read_tlv(msg, pos)
            _t, pdu_body, pos = _read_tlv(msg, pos)
            p = 0
            _t, rid, p = _read_tlv(pdu_body, p)
            _t, err, p = _read_tlv(pdu_body, p)
            _t, _eidx, p = _read_tlv(pdu_body, p)
            _t, vblist, p = _read_tlv(pdu_body, p)
            q = 0
            _t, vb, q = _read_tlv(vblist, q)
            r = 0
            _t, _oid_body, r = _read_tlv(vb, r)
            vtag, vbody, r = _read_tlv(vb, r)
            if _decode_int(err) != 0:
                return None
            if vtag in (_TAG_INT, _TAG_COUNTER, _TAG_TIMETICKS):
                return _decode_int(vbody)
            if vtag == _TAG_OCTETS:
                try:
                    return vbody.decode("utf-8", "replace").strip("\x00")
                except Exception:
                    return vbody.hex()
            return vbody.hex()
        except (IndexError, ValueError):
            return None
    return None


def snapshot(host, community="public", timeout=2.5):
    """Read the counters that matter for usage telemetry."""
    return {
        "pages_total": get(host, OID_LIFE_COUNT, community, timeout),
        "marks_total": get(host, OID_MARK_COUNT, community, timeout),
        "serial": get(host, OID_SERIAL, community, timeout),
        "model": get(host, OID_MODEL, community, timeout),
        "uptime_ticks": get(host, OID_UPTIME, community, timeout),
    }
