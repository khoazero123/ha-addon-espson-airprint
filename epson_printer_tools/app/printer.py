"""Printer status over the same local API the Epson Smart Panel app uses."""

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid

CLIENT_ID = str(uuid.uuid4())
STATUS_PATH = "/remote_operation/v1/device/get_status"


def _request(url, timeout):
    body = urllib.parse.urlencode(
        {"keys": "printer-state,printer-state-reasons", "client-id": CLIENT_ID}
    ).encode()
    req = urllib.request.Request(
        url + STATUS_PATH,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def get_status(host, timeout=4.0):
    """Return {'success':..., 'printer-state':..., 'printer-state-reasons':...} or None."""
    for scheme in ("http", "https"):
        try:
            data = _request("%s://%s" % (scheme, host), timeout)
        except (urllib.error.URLError, OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("success"):
            data["via"] = scheme
            return data
    return None


def is_epson(host, timeout=2.5):
    data = get_status(host, timeout)
    return data is not None, data
