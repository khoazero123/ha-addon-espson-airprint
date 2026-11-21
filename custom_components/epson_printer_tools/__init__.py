"""The Epson Printer Tools integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_TOKEN, DEFAULT_SCAN_INTERVAL
from .coordinator import EpsonPrinterCoordinator

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
]

# Plain alias instead of a PEP 695 `type` statement: works on Python 3.12 and
# 3.13+ (HA 2026.9.x runs 3.13), and avoids runtime typing surprises.
EpsonConfigEntry = ConfigEntry[EpsonPrinterCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: EpsonConfigEntry) -> bool:
    """Set up Epson Printer Tools from a config entry."""
    coordinator = EpsonPrinterCoordinator(
        hass,
        url=entry.data[CONF_URL],
        token=entry.data.get(CONF_TOKEN),
        scan_interval=int(entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)),
        entry=entry,
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EpsonConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: EpsonConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
