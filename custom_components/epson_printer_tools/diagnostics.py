"""Diagnostics support for the Epson Printer Tools integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_TOKEN, DEFAULT_SCAN_INTERVAL

TO_REDACT = {CONF_TOKEN, "token"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry,
) -> dict[str, Any]:
    """Return diagnostics without the API token."""
    coordinator = getattr(entry, "runtime_data", None)
    data = coordinator.data if coordinator is not None else None
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(
                {
                    "scan_interval": entry.options.get(
                        "scan_interval", DEFAULT_SCAN_INTERVAL
                    )
                },
                TO_REDACT,
            ),
        },
        "coordinator": {
            "url": coordinator.url if coordinator is not None else None,
            "last_update_success": (
                coordinator.last_update_success if coordinator is not None else None
            ),
            "update_interval": (
                coordinator.update_interval.total_seconds()
                if coordinator is not None and coordinator.update_interval
                else None
            ),
            "state": async_redact_data(data, TO_REDACT) if data else None,
        },
    }
