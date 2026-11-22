"""Data update coordinator for the Epson Printer Tools integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_ACTION,
    API_STATE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

ACTION_NOZZLE_CHECK = "nozzle_check"
ACTION_HEAD_CLEAN = "head_clean"


class EpsonApiError(Exception):
    """Raised when the add-on API cannot be reached or rejects a request."""


class EpsonAuthError(EpsonApiError):
    """Raised when the add-on API rejects the configured token."""


class EpsonPrinterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll the Epson Printer Tools add-on REST API."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        url: str,
        token: str | None,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        entry: Any | None = None,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval or DEFAULT_SCAN_INTERVAL),
        )
        self._url = url.rstrip("/")
        self._token = token or ""
        self._entry = entry
        self._session: ClientSession = async_get_clientsession(hass)

    @property
    def url(self) -> str:
        """Base URL of the add-on."""
        return self._url

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _async_get_json(self, path: str) -> dict[str, Any]:
        try:
            async with self._session.get(
                f"{self._url}{path}",
                headers=self._headers(),
                timeout=ClientTimeout(total=DEFAULT_TIMEOUT),
            ) as resp:
                if resp.status in (401, 403):
                    raise EpsonAuthError(f"token rejected (HTTP {resp.status})")
                if resp.status != 200:
                    raise EpsonApiError(f"unexpected HTTP {resp.status} from {path}")
                payload = await resp.json(content_type=None)
        except (ClientError, asyncio.TimeoutError) as err:
            raise EpsonApiError(f"cannot reach {self._url}: {err}") from err
        except ValueError as err:
            raise EpsonApiError(f"invalid JSON from {path}") from err
        if not isinstance(payload, dict):
            raise EpsonApiError(f"unexpected payload from {path}")
        return payload

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._async_get_json(API_STATE)
        except EpsonAuthError as err:
            if self._entry is not None:
                self._entry.async_start_reauth(self.hass)
            raise UpdateFailed(str(err)) from err
        except EpsonApiError as err:
            raise UpdateFailed(str(err)) from err

    async def async_run_action(self, action: str) -> dict[str, Any]:
        """Send a maintenance action; raises EpsonApiError on failure."""
        if action not in (ACTION_NOZZLE_CHECK, ACTION_HEAD_CLEAN):
            raise EpsonApiError(f"unsupported action: {action}")
        try:
            async with self._session.post(
                f"{self._url}{API_ACTION}",
                json={"action": action},
                headers=self._headers(),
                timeout=ClientTimeout(total=DEFAULT_TIMEOUT + 20),
            ) as resp:
                if resp.status in (401, 403):
                    raise EpsonAuthError(f"token rejected (HTTP {resp.status})")
                payload: Any
                try:
                    payload = await resp.json(content_type=None)
                except ValueError:
                    payload = {}
                if resp.status != 200:
                    message = ""
                    if isinstance(payload, dict):
                        message = str(payload.get("error") or "")
                    raise EpsonApiError(
                        f"{action} failed (HTTP {resp.status})"
                        + (f": {message}" if message else "")
                    )
        except (ClientError, asyncio.TimeoutError) as err:
            raise EpsonApiError(f"cannot reach {self._url}: {err}") from err
        return payload if isinstance(payload, dict) else {}

    async def async_validate(self) -> dict[str, Any]:
        """Fetch the state once, used by the config flow."""
        return await self._async_get_json(API_STATE)


def state_snapshot(data: dict[str, Any] | None) -> dict[str, Any]:
    """Return a flat, defensive view over the add-on state payload."""
    if not isinstance(data, dict):
        return {}
    printer = data.get("printer") or {}
    usage = data.get("usage") or {}
    settings = data.get("settings") or {}
    airprint = data.get("airprint") or {}
    history = data.get("history") or []
    last_job = next(
        (item for item in history if isinstance(item, dict)
         and item.get("event") in (ACTION_NOZZLE_CHECK, ACTION_HEAD_CLEAN)
         and item.get("source") == "job"),
        None,
    ) if isinstance(history, list) else None

    return {
        "configured": printer.get("configured"),
        "reachable": printer.get("reachable"),
        "raw_state": printer.get("state"),
        "reasons": printer.get("reasons"),
        "model": printer.get("model"),
        "serial": printer.get("serial"),
        "printer_ip": settings.get("printer_ip"),
        "poll_interval": settings.get("poll_interval"),
        "pages_total": usage.get("pages_total"),
        "marks_total": usage.get("marks_total"),
        "last_print": usage.get("last_print"),
        "last_clean": usage.get("last_clean"),
        "last_nozzle_check": usage.get("last_nozzle_check"),
        "last_job": last_job,
        "last_poll": usage.get("last_poll"),
        "airprint_enabled": airprint.get("enabled"),
        "airprint_queue": airprint.get("queue"),
        "airprint_ipp_uri": airprint.get("ipp_uri"),
        "airprint_error": airprint.get("error"),
        "server_time": data.get("server_time"),
    }
