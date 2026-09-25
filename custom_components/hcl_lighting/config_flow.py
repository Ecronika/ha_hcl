"""Config flow for HCL Lighting integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN, CONF_TARGET, CONF_SMART_TRANSITION,
    CONF_MIN_BRIGHTNESS, CONF_MAX_BRIGHTNESS,
    DEFAULT_MIN_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS,
    CONF_WAKE_TIME, CONF_MIDDAY_TIME, CONF_SLEEP_TIME,
    DEFAULT_WAKE_TIME, DEFAULT_MIDDAY_TIME, DEFAULT_SLEEP_TIME,
    CONF_CURVE_CONFIG,
    CONF_UPDATE_INTERVAL, CONF_TRANSITION, CONF_TURN_ON_TRANSITION,
    CONF_OVERRIDE_TIMEOUT, CONF_OVERRIDE_RESET_ON_OFF, CONF_PERSIST_OVERRIDES,
    CONF_RESPECT_TURN_ON_VALUES, CONF_SCENARIO_DURATION,
    DEFAULT_UPDATE_INTERVAL, DEFAULT_TRANSITION, DEFAULT_TURN_ON_TRANSITION,
    DEFAULT_OVERRIDE_TIMEOUT, DEFAULT_OVERRIDE_RESET_ON_OFF, DEFAULT_PERSIST_OVERRIDES,
    DEFAULT_RESPECT_TURN_ON_VALUES, DEFAULT_SCENARIO_DURATION,
    SCENARIO_DEFAULTS, CONFIGURABLE_SCENARIOS, scenario_option_keys,
    CONF_BRIGHTNESS_SCALING, DEFAULT_BRIGHTNESS_SCALING,
    CONF_SCENARIO_LIMITS, DEFAULT_SCENARIO_LIMITS,
    CONF_SCENARIO_TRANSITION,
    CONF_NIGHT_END_AT_WAKE, DEFAULT_NIGHT_END_AT_WAKE,
)

from homeassistant.const import CONF_NAME

_LOGGER = logging.getLogger(__name__)

# The curve needs more than 6 hours between wake and sleep time
MIN_ACTIVE_SPAN_MINUTES = 360


def _anchor_errors(values: dict[str, Any]) -> dict[str, str]:
    """Validate the wake/sleep anchor times of a form."""
    wake = dt_util.parse_time(str(values.get(CONF_WAKE_TIME) or DEFAULT_WAKE_TIME))
    sleep = dt_util.parse_time(str(values.get(CONF_SLEEP_TIME) or DEFAULT_SLEEP_TIME))
    if wake is None or sleep is None:
        return {"base": "invalid_time"}
    span = ((sleep.hour * 60 + sleep.minute) - (wake.hour * 60 + wake.minute)) % 1440
    if span <= MIN_ACTIVE_SPAN_MINUTES:
        return {"base": "active_span_too_short"}
    return {}


def _anchor_schema(defaults: dict[str, Any]) -> dict:
    return {
        vol.Required(CONF_WAKE_TIME, default=defaults.get(CONF_WAKE_TIME, DEFAULT_WAKE_TIME)): selector.TimeSelector(),
        vol.Required(CONF_MIDDAY_TIME, default=defaults.get(CONF_MIDDAY_TIME, DEFAULT_MIDDAY_TIME)): selector.TimeSelector(),
        vol.Required(CONF_SLEEP_TIME, default=defaults.get(CONF_SLEEP_TIME, DEFAULT_SLEEP_TIME)): selector.TimeSelector(),
    }


def _number(min_value: float, max_value: float, step: float = 1, unit: str | None = None):
    config = {"min": min_value, "max": max_value, "step": step, "mode": "box"}
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


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
        errors = {}
        if user_input is not None:
            errors = _anchor_errors(user_input)
            if not errors:
                return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        defaults = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "HCL Lighting")): str,
                    vol.Required(CONF_TARGET, default=defaults.get(CONF_TARGET) or {}): selector.TargetSelector(
                        {
                            "entity": {
                                "domain": ["light"]
                            },
                        }
                    ),
                    **_anchor_schema(defaults),
                }
            ),
            errors=errors,
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a options flow for HCL Lighting."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry_proxy = config_entry
        self._pending: dict[str, Any] = {}

    def _current(self) -> dict[str, Any]:
        """Effective settings: entry data overridden by the options."""
        entry = self.config_entry_proxy
        return {**entry.data, **entry.options}

    def _merged_options(self, user_input: dict[str, Any]) -> dict[str, Any]:
        """Merge the form into the existing options.

        Options not shown in this form (e.g. the curve saved by the dashboard
        card) are kept. A saved curve is only discarded when an anchor time
        (wake/midday/sleep) is changed, so the curve is regenerated from the
        new anchors.
        """
        entry = self.config_entry_proxy
        defaults = {
            CONF_WAKE_TIME: DEFAULT_WAKE_TIME,
            CONF_MIDDAY_TIME: DEFAULT_MIDDAY_TIME,
            CONF_SLEEP_TIME: DEFAULT_SLEEP_TIME,
        }
        new_options = {**entry.options, **user_input}
        for key, default in defaults.items():
            old = entry.options.get(key) or entry.data.get(key) or default
            new = user_input.get(key) or default
            if dt_util.parse_time(str(old)) != dt_util.parse_time(str(new)):
                new_options.pop(CONF_CURVE_CONFIG, None)
                break
        return new_options

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
                errors = _anchor_errors(user_input)
            if not errors:
                self._pending.update(user_input)
                return await self.async_step_behavior()

        # Compatibility wrapper for older HA versions
        # Use current options/data as defaults if user_input is None
        schema_defaults = user_input or self._current()
        
        # Manually inject defaults into base schema for fallback compatibility
        base_schema = vol.Schema(
            {
                vol.Required(CONF_TARGET, default=schema_defaults.get(CONF_TARGET) or {}): selector.TargetSelector(
                    {"entity": {"domain": ["light"]}}
                ),
                **_anchor_schema(schema_defaults),
                vol.Optional(CONF_SMART_TRANSITION, default=schema_defaults.get(CONF_SMART_TRANSITION, False)): selector.BooleanSelector(),
                vol.Optional(CONF_MIN_BRIGHTNESS, default=schema_defaults.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS)): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
                vol.Optional(CONF_MAX_BRIGHTNESS, default=schema_defaults.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS)): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
                vol.Optional(CONF_BRIGHTNESS_SCALING, default=schema_defaults.get(CONF_BRIGHTNESS_SCALING, DEFAULT_BRIGHTNESS_SCALING)): selector.BooleanSelector(),
            }
        )

        if hasattr(self, "add_suggested_values_to_schema"):
            try:
                # Provide the defaults object to HA helper
                data_schema = self.add_suggested_values_to_schema(base_schema, schema_defaults)
            except Exception:
                _LOGGER.exception("Failed to apply suggested schema defaults, falling back to base schema")
                data_schema = base_schema
        else:
            # Fallback for old HA: use the base_schema which already has defaults injected manually above
            data_schema = base_schema

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_behavior(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Update timing and manual-control behaviour."""
        errors = {}
        if user_input is not None:
            if user_input[CONF_TRANSITION] >= user_input[CONF_UPDATE_INTERVAL]:
                errors["base"] = "transition_too_long"
            else:
                self._pending.update(user_input)
                return await self.async_step_scenarios()

        current = {**self._current(), **(user_input or {})}
        schema = vol.Schema(
            {
                vol.Required(CONF_UPDATE_INTERVAL, default=current.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)): _number(10, 600, unit="s"),
                vol.Required(CONF_TRANSITION, default=current.get(CONF_TRANSITION, DEFAULT_TRANSITION)): _number(0, 300, unit="s"),
                vol.Required(CONF_TURN_ON_TRANSITION, default=current.get(CONF_TURN_ON_TRANSITION, DEFAULT_TURN_ON_TRANSITION)): _number(0, 30, unit="s"),
                # Default: the update transition (behaviour up to 0.6)
                vol.Required(CONF_SCENARIO_TRANSITION, default=current.get(CONF_SCENARIO_TRANSITION, current.get(CONF_TRANSITION, DEFAULT_TRANSITION))): _number(0, 300, unit="s"),
                vol.Required(CONF_OVERRIDE_TIMEOUT, default=current.get(CONF_OVERRIDE_TIMEOUT, DEFAULT_OVERRIDE_TIMEOUT)): _number(0, 1440, unit="min"),
                vol.Required(CONF_OVERRIDE_RESET_ON_OFF, default=current.get(CONF_OVERRIDE_RESET_ON_OFF, DEFAULT_OVERRIDE_RESET_ON_OFF)): selector.BooleanSelector(),
                vol.Required(CONF_PERSIST_OVERRIDES, default=current.get(CONF_PERSIST_OVERRIDES, DEFAULT_PERSIST_OVERRIDES)): selector.BooleanSelector(),
                vol.Required(CONF_RESPECT_TURN_ON_VALUES, default=current.get(CONF_RESPECT_TURN_ON_VALUES, DEFAULT_RESPECT_TURN_ON_VALUES)): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="behavior", data_schema=schema, errors=errors)

    async def async_step_scenarios(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Values of the fixed scenarios and their duration."""
        if user_input is not None:
            self._pending.update(user_input)
            return self.async_create_entry(title="", data=self._merged_options(self._pending))

        current = self._current()
        fields = {}
        for mode in CONFIGURABLE_SCENARIOS:
            key_b, key_k = scenario_option_keys(mode)
            fields[vol.Required(key_b, default=current.get(key_b, SCENARIO_DEFAULTS[mode]["brightness"]))] = _number(1, 100, unit="%")
            fields[vol.Required(key_k, default=current.get(key_k, SCENARIO_DEFAULTS[mode]["kelvin"]))] = _number(2000, 7000, step=50, unit="K")
        fields[vol.Required(CONF_SCENARIO_DURATION, default=current.get(CONF_SCENARIO_DURATION, DEFAULT_SCENARIO_DURATION))] = _number(0, 1440, unit="min")
        fields[vol.Required(CONF_SCENARIO_LIMITS, default=current.get(CONF_SCENARIO_LIMITS, DEFAULT_SCENARIO_LIMITS))] = selector.BooleanSelector()
        fields[vol.Required(CONF_NIGHT_END_AT_WAKE, default=current.get(CONF_NIGHT_END_AT_WAKE, DEFAULT_NIGHT_END_AT_WAKE))] = selector.BooleanSelector()
        return self.async_show_form(step_id="scenarios", data_schema=vol.Schema(fields))
