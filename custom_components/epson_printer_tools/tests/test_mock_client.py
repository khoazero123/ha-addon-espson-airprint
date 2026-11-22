"""Mock-API tests for the Epson Printer Tools integration.

Runs without Home Assistant installed: the few HA symbols used by the
coordinator are stubbed, then the real request/parsing code is exercised
against a local aiohttp server that mimics the add-on API.

    python3 custom_components/epson_printer_tools/tests/test_mock_client.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STATE_FIXTURE = {
    "settings": {
        "printer_ip": "192.168.1.108",
        "poll_interval": 60,
        "mqtt_enabled": False,
        "scan_subnet": "",
    },
    "printer": {
        "configured": True,
        "reachable": True,
        "state": 3,
        "reasons": "none",
        "model": "EPSON L8050 Series",
        "serial": "ABC123",
        "uptime_ticks": 1000,
    },
    "usage": {
        "pages_total": 1234,
        "marks_total": 5000,
        "last_print": "2026-11-21T10:00:00+07:00",
        "last_clean": "2026-11-20T09:00:00+07:00",
        "last_nozzle_check": "2026-11-19T09:00:00+07:00",
        "last_poll": "2026-11-21T17:00:00+07:00",
    },
    "airprint": {
        "available": True,
        "enabled": True,
        "queue": "Epson_L8050",
        "ipp_uri": "ipp://host:631/printers/Epson_L8050",
        "error": None,
    },
    "history": [],
    "server_time": "2026-11-21T17:00:00+07:00",
}


def _stub_homeassistant() -> None:
    ha = types.ModuleType("homeassistant")
    ha.__path__ = []  # namespace package

    core = types.ModuleType("homeassistant.core")

    class HomeAssistant:  # noqa: D401 - stub
        pass

    core.HomeAssistant = HomeAssistant

    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []

    uc = types.ModuleType("homeassistant.helpers.update_coordinator")

    class UpdateFailed(Exception):
        pass

    class DataUpdateCoordinator:
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, hass, logger, name, update_interval=None):
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.data = None
            self.last_update_success = True

        async def async_request_refresh(self):
            return None

    uc.UpdateFailed = UpdateFailed
    uc.DataUpdateCoordinator = DataUpdateCoordinator

    aio = types.ModuleType("homeassistant.helpers.aiohttp_client")
    _session_holder = types.SimpleNamespace(session=None)

    def async_get_clientsession(hass, verify_ssl=True):
        return _session_holder.session

    aio.async_get_clientsession = async_get_clientsession

    sys.modules.update(
        {
            "homeassistant": ha,
            "homeassistant.core": core,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.update_coordinator": uc,
            "homeassistant.helpers.aiohttp_client": aio,
        }
    )
    return _session_holder


def _load_package():
    pkg = types.ModuleType("ept")
    pkg.__path__ = [str(ROOT)]
    sys.modules["ept"] = pkg
    for name in ("const", "coordinator"):
        spec = importlib.util.spec_from_file_location(
            f"ept.{name}", ROOT / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"ept.{name}"] = module
        spec.loader.exec_module(module)
    return sys.modules["ept.coordinator"], sys.modules["ept.const"]


async def _make_server(seen: dict):
    from aiohttp import web

    async def state(request):
        seen["auth"] = request.headers.get("Authorization")
        seen["path"] = request.path
        return web.json_response(STATE_FIXTURE)

    async def action(request):
        seen["action_body"] = await request.json()
        seen["action_auth"] = request.headers.get("Authorization")
        return web.json_response({"ok": True, "result": {"timestamp": "x"}})

    async def unauthorized(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    async def broken(request):
        return web.json_response({"error": "boom"}, status=500)

    app = web.Application()
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/action", action)
    app.router.add_get("/bad/api/state", unauthorized)
    app.router.add_post("/bad/api/action", broken)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    return runner, f"http://127.0.0.1:{port}"


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"ok - {message}")


async def main() -> None:
    import aiohttp

    holder = _stub_homeassistant()
    coordinator_mod, const = _load_package()

    runner, base = await _make_server(seen := {})
    async with aiohttp.ClientSession() as session:
        holder.session = session

        coord = coordinator_mod.EpsonPrinterCoordinator(
            None, url=base + "/", token="secret-token", scan_interval=30
        )
        check(coord.update_interval == timedelta(seconds=30), "scan interval applied")

        data = await coord._async_update_data()
        check(seen["path"] == "/api/state", "GET /api/state used, no double slash")
        check(seen["auth"] == "Bearer secret-token", "Bearer token sent")
        check(data["printer"]["state"] == 3, "state payload returned")

        snap = coordinator_mod.state_snapshot(data)
        check(snap["pages_total"] == 1234, "pages_total mapped")
        check(snap["last_print"] == "2026-11-21T10:00:00+07:00", "last_print mapped")
        check(snap["last_clean"] == "2026-11-20T09:00:00+07:00", "last_clean mapped")
        check(snap["airprint_enabled"] is True, "airprint enabled mapped")
        check(snap["airprint_queue"] == "Epson_L8050", "airprint queue mapped")
        check(snap["model"] == "EPSON L8050 Series", "model mapped")
        check(snap["last_job"] is None, "no job without history")
        with_job = dict(data, history=[{"event": "print", "source": "counter"},
                                       {"event": "head_clean", "source": "job", "at": "2026-11-22T08:20:00+07:00"}])
        check(coordinator_mod.state_snapshot(with_job)["last_job"]["event"] == "head_clean",
              "last submitted maintenance command mapped")
        check(coordinator_mod.state_snapshot(dict(data, history="bad"))["last_job"] is None,
              "invalid history ignored")

        await coord.async_run_action("nozzle_check")
        check(
            seen["action_body"] == {"action": "nozzle_check"},
            "POST /api/action body",
        )
        check(
            seen["action_auth"] == "Bearer secret-token", "token on action request"
        )

        # Auth rejection surfaces as EpsonAuthError.
        bad = coordinator_mod.EpsonPrinterCoordinator(None, url=base + "/bad", token="secret-token")
        try:
            await bad._async_update_data()
        except coordinator_mod.UpdateFailed as err:
            check("401" in str(err), "401 becomes UpdateFailed")
            check(
                "secret-token" not in str(err) and "Bearer" not in str(err),
                "error text never contains the token",
            )
        else:
            raise AssertionError("401 did not fail")

        try:
            await bad.async_run_action("head_clean")
        except coordinator_mod.EpsonApiError as err:
            check("500" in str(err), "500 action error surfaces message")
        else:
            raise AssertionError("action 500 did not raise")

    await runner.cleanup()

    # Connection failure semantics: coordinator reports UpdateFailed so HA marks
    # entities unavailable.
    async with aiohttp.ClientSession() as session:
        holder.session = session
        dead = coordinator_mod.EpsonPrinterCoordinator(
            None, url="http://127.0.0.1:9", token=None
        )
        try:
            await dead._async_update_data()
        except coordinator_mod.UpdateFailed as err:
            check("cannot reach" in str(err), "unreachable API -> UpdateFailed")
        else:
            raise AssertionError("dead endpoint did not fail")

    # action whitelist and empty snapshot tolerance
    try:
        await dead.async_run_action("factory_reset")
    except coordinator_mod.EpsonApiError as err:
        check("unsupported action" in str(err), "unknown action rejected locally")
    else:
        raise AssertionError("unknown action accepted")

    check(coordinator_mod.state_snapshot(None) == {}, "empty state safe")
    check(coordinator_mod.state_snapshot({"printer": {}})["pages_total"] is None, "partial state safe")

    print("\nall checks passed")


if __name__ == "__main__":
    asyncio.run(main())
