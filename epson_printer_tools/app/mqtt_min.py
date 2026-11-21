"""Minimal MQTT 3.1.1 client (stdlib only): CONNECT, PUBLISH QoS0, SUBSCRIBE, PING.

Only what the add-on needs to publish Home Assistant discovery and listen for button
presses. Keeps the container dependency-free so the image builds offline-ish and small.
"""

import socket
import struct
import threading
import time

CONNECT = 0x10
CONNACK = 0x20
PUBLISH = 0x30
SUBSCRIBE = 0x82
SUBACK = 0x90
PINGREQ = 0xC0
PINGRESP = 0xD0
DISCONNECT = 0xE0


def _remaining_length(value):
    out = bytearray()
    while True:
        digit = value % 128
        value //= 128
        if value:
            out.append(digit | 0x80)
        else:
            out.append(digit)
            return bytes(out)


def _string(value):
    raw = value.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


class MiniMqtt:
    def __init__(self, host, port=1883, client_id="epson_printer_tools",
                 username=None, password=None, keepalive=60):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.username = username
        self.password = password
        self.keepalive = keepalive
        self.sock = None
        self.connected = False
        self.on_message = None
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # -- wire helpers -------------------------------------------------
    def _send(self, packet):
        with self._lock:
            if not self.sock:
                raise OSError("not connected")
            self.sock.sendall(packet)

    def _read_exact(self, count):
        chunks = b""
        while len(chunks) < count:
            piece = self.sock.recv(count - len(chunks))
            if not piece:
                raise OSError("connection closed")
            chunks += piece
        return chunks

    def _read_packet(self):
        header = self._read_exact(1)[0]
        multiplier = 1
        length = 0
        while True:
            byte = self._read_exact(1)[0]
            length += (byte & 0x7F) * multiplier
            if not byte & 0x80:
                break
            multiplier *= 128
        body = self._read_exact(length) if length else b""
        return header, body

    # -- public API ---------------------------------------------------
    def connect(self, timeout=6):
        self.sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self.sock.settimeout(1.0)
        flags = 0x02  # clean session
        payload = _string(self.client_id)
        if self.username:
            flags |= 0x80
            payload += _string(self.username)
            if self.password:
                flags |= 0x40
                payload += _string(self.password)
        variable = _string("MQTT") + bytes([4, flags]) + struct.pack(">H", self.keepalive)
        body = variable + payload
        self._send(bytes([CONNECT]) + _remaining_length(len(body)) + body)
        header, reply = self._read_packet()
        if header & 0xF0 != CONNACK or len(reply) < 2 or reply[1] != 0:
            raise OSError("MQTT connection refused")
        self.connected = True
        threading.Thread(target=self._reader, daemon=True).start()
        return True

    def publish(self, topic, payload, retain=False):
        if not self.connected:
            return False
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        body = _string(topic) + data
        header = PUBLISH | (0x01 if retain else 0x00)
        self._send(bytes([header]) + _remaining_length(len(body)) + body)
        return True

    def subscribe(self, topic):
        if not self.connected:
            return False
        body = struct.pack(">H", 1) + _string(topic) + bytes([0])
        self._send(bytes([SUBSCRIBE]) + _remaining_length(len(body)) + body)
        return True

    def _reader(self):
        while self.connected and not self._stop.is_set():
            try:
                header, body = self._read_packet()
            except socket.timeout:
                continue
            except OSError:
                self.connected = False
                break
            kind = header & 0xF0
            if kind == PUBLISH:
                qos = (header >> 1) & 0x03
                topic_len = struct.unpack(">H", body[:2])[0]
                topic = body[2:2 + topic_len].decode("utf-8", "replace")
                offset = 2 + topic_len + (2 if qos else 0)
                payload = body[offset:]
                if self.on_message:
                    try:
                        self.on_message(topic, payload)
                    except Exception:  # noqa: BLE001 - never kill the reader thread
                        pass
            elif kind == PINGRESP:
                continue

    def loop_ping(self):
        while self.connected and not self._stop.is_set():
            self._stop.wait(self.keepalive / 2)
            if not self.connected:
                break
            try:
                self._send(bytes([PINGREQ, 0]))
            except OSError:
                self.connected = False
                break

    def disconnect(self):
        self._stop.set()
        try:
            if self.sock and self.connected:
                self._send(bytes([DISCONNECT, 0]))
        except OSError:
            pass
        self.connected = False
        if self.sock:
            self.sock.close()
            self.sock = None


def sleep_forever():
    while True:
        time.sleep(3600)
