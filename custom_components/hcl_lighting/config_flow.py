"""Config flow for HCL Lighting integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult, section
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN, CONF_TARGET, CONF_SMART_TRANSITION,
    CONF_MIN_BRIGHTNESS, CONF_MAX_BRIGHTNESS,
    DEFAULT_MIN_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS,
    CONF_WAKE_TIME, CONF_SLEEP_TIME, ANCHOR_DEFAULTS, anchor_time,
    CONF_CURVE_CONFIG,
    CONF_UPDATE_INTERVAL, CONF_TRANSITION,
    CONF_OVERRIDE_TIMEOUT, CONF_OVERRIDE_RESET_ON_OFF, CONF_PERSIST_OVERRIDES,
    CONF_RESPECT_TURN_ON_VALUES, CONF_SCENARIO_DURATION,
    DEFAULT_UPDATE_INTERVAL, DEFAULT_TRANSITION,
    MIN_UPDATE_INTERVAL, MAX_UPDATE_INTERVAL,
    DEFAULT_OVERRIDE_TIMEOUT, DEFAULT_OVERRIDE_RESET_ON_OFF, DEFAULT_PERSIST_OVERRIDES,
    DEFAULT_RESPECT_TURN_ON_VALUES, DEFAULT_SCENARIO_DURATION,
    SCENARIO_DEFAULTS, CONFIGURABLE_SCENARIOS, scenario_option_keys,
    CONF_SCENARIO_TRANSITION,
)

from homeassistant.const import CONF_NAME

_LOGGER = logging.getLogger(__name__)

# The curve needs more than 6 hours between wake and sleep time
MIN_ACTIVE_SPAN_MINUTES = 360
# Collapsible section of the timing options (RM-R11)
SECTION_ADVANCED = "advanced"


def _anchor_errors(values: dict[str, Any]) -> dict[str, str]:
    """Validate the wake/sleep anchor times of a form."""
    wake = dt_util.parse_time(anchor_time(values, CONF_WAKE_TIME))
    sleep = dt_util.parse_time(anchor_time(values, CONF_SLEEP_TIME))
    if wake is None or sleep is None:
        return {"base": "invalid_time"}
    span = ((sleep.hour * 60 + sleep.minute) - (wake.hour * 60 + wake.minute)) % 1440
    if span <= MIN_ACTIVE_SPAN_MINUTES:
        return {"base": "active_span_too_short"}
    return {}


def _target_errors(values: dict[str, Any]) -> dict[str, str]:
    """An instance needs at least one target (RM-B35: an empty target must
    not fall back to the lights of the first setup)."""
    target = values.get(CONF_TARGET) or {}
    if not any(target.values()):
        return {CONF_TARGET: "no_lights"}
    return {}


def _anchor_schema(defaults: dict[str, Any]) -> dict:
    return {
        vol.Required(key, default=anchor_time(defaults, key)): selector.TimeSelector()
        for key in (CONF_WAKE_TIME, CONF_SLEEP_TIME)
    }


def _number(min_value: float, max_value: float, step: float = 1, unit: str | None = None):
    config = {"min": min_value, "max": max_value, "step": step, "mode": "box"}
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HCL Lighting."""

    VERSION = 1
    # 1.2 (0.8.0): all settings in the options (see async_migrate_entry)
    MINOR_VERSION = 2

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
            errors = _target_errors(user_input) or _anchor_errors(user_input)
            if not errors:
                options = {k: v for k, v in user_input.items() if k != CONF_NAME}
                return self.async_create_entry(title=user_input[CONF_NAME], data={}, options=options)

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
        """Current settings (all in the options since entry version 1.2)."""
        return dict(self.config_entry_proxy.options)

    def _merged_options(self, user_input: dict[str, Any]) -> dict[str, Any]:
        """Merge the form into the existing options.

        Options not shown in this form (e.g. the curve saved by the dashboard
        card) are kept. A saved curve is only discarded when an anchor time
        (wake/sleep) is changed, so the curve is regenerated from the new
        anchors.
        """
        entry = self.config_entry_proxy
        new_options = {**entry.options, **user_input}
        for key in ANCHOR_DEFAULTS:
            old = anchor_time(entry.options, key)
            new = anchor_time(user_input, key)
            if dt_util.parse_time(old) != dt_util.parse_time(new):
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
                errors = _target_errors(user_input) or _anchor_errors(user_input)
            if not errors:
                self._pending.update(user_input)
                return await self.async_step_behavior()

        # Current options/data as defaults if user_input is None
        schema_defaults = user_input or self._current()
        
        # Defaults in the schema; suggested values below show the current settings
        base_schema = vol.Schema(
            {
                vol.Required(CONF_TARGET, default=schema_defaults.get(CONF_TARGET) or {}): selector.TargetSelector(
                    {"entity": {"domain": ["light"]}}
                ),
                **_anchor_schema(schema_defaults),
                vol.Optional(CONF_SMART_TRANSITION, default=schema_defaults.get(CONF_SMART_TRANSITION, False)): selector.BooleanSelector(),
                vol.Optional(CONF_MIN_BRIGHTNESS, default=schema_defaults.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS)): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
                vol.Optional(CONF_MAX_BRIGHTNESS, default=schema_defaults.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS)): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
            }
        )

        # Available in every supported Home Assistant version (2024.7+); an
        # error here is a real bug and is not hidden behind a fallback.
        data_schema = self.add_suggested_values_to_schema(base_schema, schema_defaults)

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
        flat: dict[str, Any] = {}
        if user_input is not None:
            # the timing options come in their own section (RM-R11)
            flat = {k: v for k, v in user_input.items() if k != SECTION_ADVANCED}
            flat.update(user_input.get(SECTION_ADVANCED) or {})
            if flat[CONF_TRANSITION] >= flat[CONF_UPDATE_INTERVAL]:
                errors["base"] = "transition_too_long"
            else:
                self._pending.update(flat)
                return await self.async_step_scenarios()

        current = {**self._current(), **flat}
        advanced = vol.Schema(
            {
                vol.Required(CONF_UPDATE_INTERVAL, default=current.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)): _number(MIN_UPDATE_INTERVAL, MAX_UPDATE_INTERVAL, unit="s"),
                vol.Required(CONF_TRANSITION, default=current.get(CONF_TRANSITION, DEFAULT_TRANSITION)): _number(0, 300, unit="s"),
                # Default: the update transition (behaviour up to 0.6)
                vol.Required(CONF_SCENARIO_TRANSITION, default=current.get(CONF_SCENARIO_TRANSITION, current.get(CONF_TRANSITION, DEFAULT_TRANSITION))): _number(0, 300, unit="s"),
            }
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_OVERRIDE_TIMEOUT, default=current.get(CONF_OVERRIDE_TIMEOUT, DEFAULT_OVERRIDE_TIMEOUT)): _number(0, 1440, unit="min"),
                vol.Required(CONF_OVERRIDE_RESET_ON_OFF, default=current.get(CONF_OVERRIDE_RESET_ON_OFF, DEFAULT_OVERRIDE_RESET_ON_OFF)): selector.BooleanSelector(),
                vol.Required(CONF_PERSIST_OVERRIDES, default=current.get(CONF_PERSIST_OVERRIDES, DEFAULT_PERSIST_OVERRIDES)): selector.BooleanSelector(),
                vol.Required(CONF_RESPECT_TURN_ON_VALUES, default=current.get(CONF_RESPECT_TURN_ON_VALUES, DEFAULT_RESPECT_TURN_ON_VALUES)): selector.BooleanSelector(),
                # collapsed unless the form is shown again with an error in it
                vol.Required(SECTION_ADVANCED): section(advanced, {"collapsed": not errors}),
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
        return self.async_show_form(step_id="scenarios", data_schema=vol.Schema(fields))
