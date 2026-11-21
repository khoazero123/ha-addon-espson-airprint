"""Config and options flow for the Epson Printer Tools integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_URL
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import CONF_TOKEN, DEFAULT_SCAN_INTERVAL, DOMAIN, TITLE
from .coordinator import EpsonApiError, EpsonAuthError, EpsonPrinterCoordinator

_LOGGER = logging.getLogger(__name__)

DEFAULT_URL = "http://homeassistant.local:8099"


def normalize_url(value: str) -> str:
    """Return a base URL with scheme and without trailing slash."""
    url = (value or "").strip()
    if not url:
        raise vol.Invalid("empty url")
    if "://" not in url:
        url = f"http://{url}"
    return url.rstrip("/")


DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL, default=DEFAULT_URL): str,
        vol.Optional(CONF_TOKEN, default=""): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)


async def _validate(hass, url: str, token: str | None) -> None:
    coordinator = EpsonPrinterCoordinator(hass, url=url, token=token)
    await coordinator.async_validate()


class EpsonPrinterToolsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the add-on URL and API token."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
            except vol.Invalid:
                errors["base"] = "invalid_url"
            else:
                token = (user_input.get(CONF_TOKEN) or "").strip()
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                try:
                    await _validate(self.hass, url, token)
                except EpsonAuthError:
                    errors["base"] = "invalid_auth"
                except EpsonApiError as err:
                    _LOGGER.debug("validation failed for %s: %s", url, err)
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(
                        title=TITLE,
                        data={CONF_URL: url, CONF_TOKEN: token},
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(DATA_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            token = (user_input.get(CONF_TOKEN) or "").strip()
            try:
                await _validate(self.hass, entry.data[CONF_URL], token)
            except EpsonAuthError:
                errors["base"] = "invalid_auth"
            except EpsonApiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, CONF_TOKEN: token}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_TOKEN, default=""): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    )
                }
            ),
            errors=errors,
            description_placeholders={"url": entry.data[CONF_URL]},
        )

    @callback
    def async_get_options_flow(self, config_entry) -> OptionsFlow:
        return EpsonPrinterToolsOptionsFlow()


class EpsonPrinterToolsOptionsFlow(OptionsFlow):
    """Adjust URL, token and poll interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry

        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
            except vol.Invalid:
                errors["base"] = "invalid_url"
            else:
                token = (user_input.get(CONF_TOKEN) or "").strip()
                try:
                    await _validate(self.hass, url, token)
                except EpsonAuthError:
                    errors["base"] = "invalid_auth"
                except EpsonApiError:
                    errors["base"] = "cannot_connect"
                else:
                    for other in self.hass.config_entries.async_entries(DOMAIN):
                        if other.entry_id != entry.entry_id and other.unique_id == url:
                            errors["base"] = "already_configured"
                            break
                    else:
                        self.hass.config_entries.async_update_entry(
                            entry,
                            data={**entry.data, CONF_URL: url, CONF_TOKEN: token},
                            unique_id=url,
                        )
                        return self.async_create_entry(
                            title="",
                            data={
                                "scan_interval": int(
                                    user_input.get(
                                        "scan_interval", DEFAULT_SCAN_INTERVAL
                                    )
                                )
                            },
                        )

        schema = vol.Schema(
            {
                vol.Required(CONF_URL, default=entry.data[CONF_URL]): str,
                vol.Optional(
                    CONF_TOKEN, default=entry.data.get(CONF_TOKEN, "")
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Required(
                    "scan_interval",
                    default=int(
                        entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=15, max=3600)),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )
