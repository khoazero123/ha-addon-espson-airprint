#!/usr/bin/env python3
"""
Head Cleaning for Epson L8050 - single LPR job (A1), Smart Panel parity
Bytes from PCAP 2026-11-21: payload = ESC/P-R REMOTE1 TI (timestamp) + CH (clean head).
CH = cleaning, no form feed -> nothing is printed. App has NO levels (1/2/3).

Usage: python3 head_clean.py [--dry-run]
"""

import datetime, socket, sys, time

PRINTER = "192.168.1.108"
CTL_HDR = b"\x0259 cfA1escpr-lib\n"
CTL_DATA = b"Hescpr-lib\nPepson\nvdfA1escpr-lib\nUdfA1escpr-lib\nNepson.prn\n\x00"
DATA_HDR = b"\x031073741824000 dfA1escpr-lib\n"

PREFIX = bytes.fromhex("0000001b0140454a4c20313238342e340a40454a4c20202020200a1b401b401b285208000052454d4f5445315449")
SUFFIX = bytes.fromhex("4348020000001b0000001b401b401b285208000052454d4f5445314a450100001b000000")


def ti_timestamp(now=None):
    now = now or datetime.datetime.now()
    return bytes([0x00]) + now.year.to_bytes(2, "big") + bytes(
        [now.month, now.day, now.hour, now.minute, now.second]
    )


def build_data(now=None):
    body = ti_timestamp(now)
    return PREFIX + b"\x08\x00" + body + SUFFIX


def send_job(data, printer=PRINTER):
    s = socket.socket()
    s.settimeout(15)
    s.connect((printer, 515))
    try:
        s.sendall(b"\x02P1\n")
        assert s.recv(1)[0] == 0, "bad ack cmd02"
        s.sendall(CTL_HDR + CTL_DATA)
        assert s.recv(1)[0] == 0, "bad ack control"
        time.sleep(0.5)
        s.sendall(DATA_HDR + data)
        time.sleep(0.5)
        try:
            assert s.recv(1)[0] == 0
        except (socket.timeout, AssertionError):
            pass
    finally:
        s.close()


def main():
    data = build_data()
    if "--dry-run" in sys.argv:
        print("data=%d bytes hex=%s" % (len(data), data.hex()))
        return
    send_job(data)
    print("head clean job sent to " + PRINTER, flush=True)


if __name__ == "__main__":
    main()
