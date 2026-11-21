"""Constants for the Epson Printer Tools integration."""

from __future__ import annotations

DOMAIN = "epson_printer_tools"
TITLE = "Epson Printer Tools"

CONF_URL = "url"
CONF_TOKEN = "token"

DEFAULT_SCAN_INTERVAL = 60
DEFAULT_TIMEOUT = 10

API_STATE = "/api/state"
API_ACTION = "/api/action"

# IPP printer-state values, mapped to a readable device state.
PRINTER_STATES = {
    3: "idle",
    4: "processing",
    5: "stopped",
}

ATTR_REASONS = "reasons"
ATTR_REACHABLE = "reachable"
ATTR_RAW_STATE = "raw_state"
ATTR_MODEL = "model"
ATTR_SERIAL = "serial"
ATTR_SERVER_TIME = "server_time"
ATTR_LAST_POLL = "last_poll"

ATTR_QUEUE = "queue"
ATTR_IPP_URI = "ipp_uri"
ATTR_AIRPRINT_ERROR = "error"
