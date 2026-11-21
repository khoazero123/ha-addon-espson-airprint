"""Epson ESC/P-R maintenance jobs over LPR (RFC1179), byte-exact from Smart Panel captures.

Two jobs, both single LPR submissions with job id A1:
  * nozzle_check  - 158 B payload, contains NC, has form feed -> prints one test page
  * head_clean    -  92 B payload, contains CH, no form feed      -> prints nothing

The only variable part between two runs of the same job is the 8-byte TI timestamp
(00 | year BE | month | day | hour | minute | second). Everything else is constant.
"""

import datetime
import socket
import time

JOB_ID = "A1"
CTL_HDR = b"\x0259 cfA1escpr-lib\n"
CTL_DATA = b"Hescpr-lib\nPepson\nvdfA1escpr-lib\nUdfA1escpr-lib\nNepson.prn\n\x00"
DATA_HDR = b"\x031073741824000 dfA1escpr-lib\n"

PREFIX = bytes.fromhex(
    "0000001b0140454a4c20313238342e340a40454a4c20202020200a1b401b401b"
    "285208000052454d4f5445315449"
)

CLEAN_SUFFIX = bytes.fromhex(
    "4348020000001b0000001b401b401b285208000052454d4f5445314a450100001b000000"
)

NOZZLE_SUFFIX = bytes.fromhex(
    "4a53040000000000"
    "505003000001fe"
    "505003000001fa"
    "455808000000000033ff0100"
    "4e4302000000"
    "1b000000"
    "0d0a0d0a"
    "1b285208000052454d4f5445315649020000004c4400001b000000"
    "0c"
    "1b401b40"
    "1b285208000052454d4f5445314a450100001b000000"
)


class LprError(RuntimeError):
    pass


def timestamp_block(now=None):
    now = now or datetime.datetime.now()
    return (
        bytes([0x00])
        + now.year.to_bytes(2, "big")
        + bytes([now.month, now.day, now.hour, now.minute, now.second])
    )


def build_payload(kind, now=None):
    if kind == "nozzle_check":
        suffix = NOZZLE_SUFFIX
    elif kind == "head_clean":
        suffix = CLEAN_SUFFIX
    else:
        raise LprError("unknown job: %s" % kind)
    return PREFIX + b"\x08\x00" + timestamp_block(now) + suffix


def send_job(printer, kind, now=None, timeout=20):
    """Submit one maintenance job. Returns dict with byte sizes and timestamp."""
    now = now or datetime.datetime.now()
    data = build_payload(kind, now)
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect((printer, 515))
        sock.sendall(b"\x02P1\n")
        if sock.recv(1) != b"\x00":
            raise LprError("no ack for printer command")
        sock.sendall(CTL_HDR + CTL_DATA)
        if sock.recv(1) != b"\x00":
            raise LprError("no ack for control file")
        time.sleep(0.4)
        sock.sendall(DATA_HDR + data)
        time.sleep(0.4)
        try:
            sock.recv(1)
        except socket.timeout:
            pass
    except OSError as exc:
        raise LprError(str(exc)) from exc
    finally:
        sock.close()
    return {
        "job": kind,
        "job_id": JOB_ID,
        "data_bytes": len(data),
        "control_bytes": len(CTL_DATA),
        "timestamp": now.isoformat(timespec="seconds"),
    }
