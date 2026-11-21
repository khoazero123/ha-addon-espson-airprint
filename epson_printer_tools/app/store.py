"""Persistent state under /data (survives add-on restarts)."""

import json
import os
import threading

DATA_DIR = os.environ.get("DATA_DIR", "/data")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
MAX_HISTORY = 20

_lock = threading.Lock()


def _default():
    return {
        "printer_ip": "",
        "last_print": None,
        "last_clean": None,
        "last_nozzle_check": None,
        "pages_total": None,
        "marks_total": None,
        "printer_state": None,
        "serial": None,
        "model": None,
        "uptime_ticks": None,
        "last_poll": None,
        "history": [],
    }


def load():
    state = _default()
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as handle:
            stored = json.load(handle)
        if isinstance(stored, dict):
            state.update(stored)
    except (OSError, ValueError):
        pass
    return state


def save(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_PATH)


def add_history(state, entry):
    history = state.setdefault("history", [])
    history.insert(0, entry)
    del history[MAX_HISTORY:]
