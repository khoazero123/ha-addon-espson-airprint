"""Sensor platform for the Epson Printer Tools integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_LAST_POLL,
    ATTR_MODEL,
    ATTR_RAW_STATE,
    ATTR_REACHABLE,
    ATTR_REASONS,
    ATTR_SERIAL,
    ATTR_SERVER_TIME,
    PRINTER_STATES,
)
from .coordinator import EpsonPrinterCoordinator, state_snapshot
from .entity import build_device_info

PARALLEL_UPDATES = 0


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    coordinator: EpsonPrinterCoordinator = entry.runtime_data
    async_add_entities(
        [
            EpsonPrinterStatusSensor(coordinator, entry),
            EpsonMaintenanceJobSensor(coordinator, entry),
            EpsonPagesTotalSensor(coordinator, entry),
            EpsonLastPrintSensor(coordinator, entry),
            EpsonLastCleanSensor(coordinator, entry),
        ]
    )


class EpsonBaseSensor(CoordinatorEntity[EpsonPrinterCoordinator], SensorEntity):
    """Common coordinator-backed sensor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: EpsonPrinterCoordinator, entry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = build_device_info(
            entry.entry_id, coordinator.data, coordinator.url
        )

    @property
    def _snapshot(self) -> dict[str, Any]:
        return state_snapshot(self.coordinator.data)


class EpsonPrinterStatusSensor(EpsonBaseSensor):
    """Printer state as reported by the add-on."""

    _attr_name = "Status"
    _attr_icon = "mdi:printer"

    def __init__(self, coordinator: EpsonPrinterCoordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_status"

    @property
    def native_value(self) -> str | None:
        snapshot = self._snapshot
        if not snapshot.get("configured"):
            return None
        if snapshot.get("reachable") is False:
            return "unreachable"
        raw = snapshot.get("raw_state")
        if raw is None:
            return None
        try:
            return PRINTER_STATES.get(int(raw), str(raw))
        except (TypeError, ValueError):
            return str(raw)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        snapshot = self._snapshot
        return {
            ATTR_RAW_STATE: snapshot.get("raw_state"),
            ATTR_REASONS: snapshot.get("reasons"),
            ATTR_REACHABLE: snapshot.get("reachable"),
            ATTR_MODEL: snapshot.get("model"),
            ATTR_SERIAL: snapshot.get("serial"),
            ATTR_SERVER_TIME: snapshot.get("server_time"),
            ATTR_LAST_POLL: snapshot.get("last_poll"),
        }

class EpsonMaintenanceJobSensor(EpsonBaseSensor):
    """Last maintenance command submitted; not a completion/progress signal."""

    _attr_name = "Maintenance command"
    _attr_icon = "mdi:printer-alert"

    def __init__(self, coordinator: EpsonPrinterCoordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_maintenance_command"

    @property
    def native_value(self) -> str | None:
        job = self._snapshot.get("last_job")
        return job.get("event") if job else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        job = self._snapshot.get("last_job") or {}
        return {"submitted_at": job.get("at"), "submission_only": True}


class EpsonPagesTotalSensor(EpsonBaseSensor):
    """Total printed pages counter."""

    _attr_name = "Pages printed"
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "pages"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: EpsonPrinterCoordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_pages_total"

    @property
    def native_value(self) -> int | None:
        value = self._snapshot.get("pages_total")
        return value if isinstance(value, int) else None


class _TimestampSensor(EpsonBaseSensor):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    _key: str = ""

    @property
    def native_value(self) -> datetime | None:
        return _parse_timestamp(self._snapshot.get(self._key))


class EpsonLastPrintSensor(_TimestampSensor):
    """Timestamp of the last printed job."""

    _attr_name = "Last print"
    _key = "last_print"

    def __init__(self, coordinator: EpsonPrinterCoordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_print"


class EpsonLastCleanSensor(_TimestampSensor):
    """Timestamp of the last head cleaning."""

    _attr_name = "Last clean"
    _attr_icon = "mdi:water"
    _key = "last_clean"

    def __init__(self, coordinator: EpsonPrinterCoordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_clean"
