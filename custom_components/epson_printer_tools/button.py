"""Button platform for the Epson Printer Tools integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import (
    ACTION_HEAD_CLEAN,
    ACTION_NOZZLE_CHECK,
    EpsonApiError,
    EpsonPrinterCoordinator,
)
from .entity import build_device_info

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the maintenance buttons."""
    coordinator: EpsonPrinterCoordinator = entry.runtime_data
    async_add_entities(
        [
            EpsonMaintenanceButton(coordinator, entry, ACTION_NOZZLE_CHECK),
            EpsonMaintenanceButton(coordinator, entry, ACTION_HEAD_CLEAN),
        ]
    )


class EpsonMaintenanceButton(
    CoordinatorEntity[EpsonPrinterCoordinator], ButtonEntity
):
    """Trigger a maintenance job on the printer."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EpsonPrinterCoordinator,
        entry,
        action: str,
    ) -> None:
        super().__init__(coordinator)
        self._action = action
        self._attr_unique_id = f"{entry.entry_id}_{action}"
        self._attr_name = (
            "Nozzle check" if action == ACTION_NOZZLE_CHECK else "Head clean"
        )
        self._attr_icon = (
            "mdi:printer-eye" if action == ACTION_NOZZLE_CHECK else "mdi:water-sync"
        )
        self._attr_device_info = build_device_info(
            entry.entry_id, coordinator.data, coordinator.url
        )

    async def async_press(self) -> None:
        """Send the maintenance job through the add-on API."""
        try:
            await self.coordinator.async_run_action(self._action)
        except EpsonApiError as err:
            raise HomeAssistantError(
                f"{self._attr_name} failed: {err}"
            ) from err
        await self.coordinator.async_request_refresh()
