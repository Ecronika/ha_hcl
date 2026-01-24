"""Config flow for HCL Lighting integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    DOMAIN, CONF_TARGET, CONF_SMART_TRANSITION,
    CONF_MIN_BRIGHTNESS, CONF_MAX_BRIGHTNESS,
    DEFAULT_MIN_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS
)

_LOGGER = logging.getLogger(__name__)

# CONFIG_SCHEMA moved inside step for safety

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HCL Lighting."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", 
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_TARGET): selector.TargetSelector(
                            {
                                "entity": {
                                    "domain": ["light"]
                                },
                            }
                        )
                    }
                )
            )

        return self.async_create_entry(title="HCL Lighting", data=user_input)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a options flow for HCL Lighting."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry_proxy = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors = {}
        if user_input is not None:
            min_b = user_input.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS)
            max_b = user_input.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS)

            if min_b >= max_b:
                errors["base"] = "min_greater_max"
            else:
                return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_TARGET): selector.TargetSelector(
                            {
                                "entity": {
                                    "domain": ["light"]
                                },
                             }
                        ),
                        vol.Optional(CONF_SMART_TRANSITION, default=False): selector.BooleanSelector(),
                        vol.Optional(CONF_MIN_BRIGHTNESS, default=DEFAULT_MIN_BRIGHTNESS): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
                        vol.Optional(CONF_MAX_BRIGHTNESS, default=DEFAULT_MAX_BRIGHTNESS): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
                    }
                ),
                user_input or self.config_entry_proxy.options or self.config_entry_proxy.data
            ),
            errors=errors
        )
