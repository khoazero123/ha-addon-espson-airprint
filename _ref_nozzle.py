#!/usr/bin/env python3
"""
Nozzle Check (Kiem tra kim phun) for Epson L8050 - single LPR job (A1)
Bytes replayed 1:1 from Epson Smart Panel capture (PCAPdroid 2026-11-21).

Flow: TCP 515 -> \x02P1\n -> control file -> \x03P1\n -> data file
Data payload = ESC/P-R "REMOTE1" sequence containing NC (nozzle check).
Printer renders the nozzle pattern internally, so the payload is tiny (158 B).

Usage: python3 nozzle_check.py [--dry-run]
"""

import socket, sys, time

PRINTER = "192.168.1.108"

JOB_ID = "A1"
CTL_HDR = bytes.fromhex(
        "023539206366413165736370722d6c69620a"
)
CTL_DATA = bytes.fromhex(
        "4865736370722d6c69620a506570736f6e0a766466413165736370722d6c6962"
        "0a556466413165736370722d6c69620a4e6570736f6e2e70726e0a00"
)
DATA_HDR = bytes.fromhex(
        "0331303733373431383234303030206466413165736370722d6c69620a"
)
DATA = bytes.fromhex(
        "0000001b0140454a4c20313238342e340a40454a4c20202020200a1b401b401b"
        "285208000052454d4f544531544908000007ea0b150c062a4a53040000000000"
        "505003000001fe505003000001fa455808000000000033ff01004e4302000000"
        "1b0000000d0a0d0a1b285208000052454d4f5445315649020000004c4400001b"
        "0000000c1b401b401b285208000052454d4f5445314a450100001b000000"
)


def send_job(printer=PRINTER):
    s = socket.socket()
    s.settimeout(15)
    s.connect((printer, 515))
    try:
        s.sendall(b"\x02P1\n")
        assert s.recv(1)[0] == 0, "bad ack cmd02"

        s.sendall(CTL_HDR + CTL_DATA)
        assert s.recv(1)[0] == 0, "bad ack control"

        time.sleep(0.5)

        s.sendall(DATA_HDR + DATA)
        time.sleep(0.5)
        try:
            assert s.recv(1)[0] == 0
        except (socket.timeout, AssertionError):
            pass
    finally:
        s.close()


def main():
    if "--dry-run" in sys.argv:
        print("job=%s ctl=%d data=%d bytes" % (JOB_ID, len(CTL_DATA), len(DATA)))
        return
    send_job()
    print("nozzle check job sent to " + PRINTER, flush=True)


if __name__ == "__main__":
    main()
