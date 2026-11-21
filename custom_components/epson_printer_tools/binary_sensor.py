"""Binary sensor platform for the Epson Printer Tools integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_AIRPRINT_ERROR, ATTR_IPP_URI, ATTR_QUEUE
from .coordinator import EpsonPrinterCoordinator, state_snapshot
from .entity import build_device_info

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the AirPrint bridge binary sensor."""
    coordinator: EpsonPrinterCoordinator = entry.runtime_data
    async_add_entities([EpsonAirPrintBinarySensor(coordinator, entry)])


class EpsonAirPrintBinarySensor(
    CoordinatorEntity[EpsonPrinterCoordinator], BinarySensorEntity
):
    """AirPrint bridge availability inside the add-on."""

    _attr_has_entity_name = True
    _attr_name = "AirPrint"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:apple-airplay"

    def __init__(self, coordinator: EpsonPrinterCoordinator, entry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_airprint"
        self._attr_device_info = build_device_info(
            entry.entry_id, coordinator.data, coordinator.url
        )

    @property
    def is_on(self) -> bool | None:
        snapshot = state_snapshot(self.coordinator.data)
        enabled = snapshot.get("airprint_enabled")
        if enabled is None:
            return None
        return bool(enabled) and bool(snapshot.get("airprint_queue"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        snapshot = state_snapshot(self.coordinator.data)
        return {
            ATTR_QUEUE: snapshot.get("airprint_queue"),
            ATTR_IPP_URI: snapshot.get("airprint_ipp_uri"),
            ATTR_AIRPRINT_ERROR: snapshot.get("airprint_error"),
        }
