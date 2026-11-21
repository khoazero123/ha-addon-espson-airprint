"""Shared entity helpers for the Epson Printer Tools integration."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import state_snapshot


def build_device_info(entry_id: str, data: dict[str, Any] | None, url: str) -> DeviceInfo:
    """Device info built from the live add-on state."""
    snapshot = state_snapshot(data)
    model = snapshot.get("model")
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        manufacturer="Epson",
        name=f"Epson {model}" if model else "Epson printer",
        model=model,
        serial_number=snapshot.get("serial"),
        configuration_url=url,
    )
