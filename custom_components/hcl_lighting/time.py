"""Time platform for HCL Lighting: wake and sleep time of an instance (RM-E05)."""
from __future__ import annotations

import dataclasses
import logging
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CURVE_CONFIG,
    CONF_SLEEP_TIME,
    CONF_WAKE_TIME,
    DOMAIN,
    anchor_time,
    signal_update,
)
from .entity import HCLEntity
from .ha_internals import action_context
from .logic.hcl_math import anchor_pair_error, saved_points
from .runtime import HCLConfigEntry
from .services import async_check_lights

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: HCLConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the wake and sleep time entities."""
    async_add_entities([HCLAnchorTime(entry, CONF_WAKE_TIME), HCLAnchorTime(entry, CONF_SLEEP_TIME)])


async def async_set_anchor_time(
    hass: HomeAssistant, entry: HCLConfigEntry, key: str, value: time, context: Context | None
) -> bool:
    """Set the wake or sleep time of an instance without a reload (RM-E05).

    The permission check is the only step that waits; reading, checking and
    writing the options follow in one step of the event loop, so overlapping
    calls (two time changes, a time change and a saved curve) always leave a
    valid pair with matching reference curve and reference times. Returns
    False if the value is the stored time.
    """
    runtime = entry.runtime_data
    value = value.replace(second=0, microsecond=0)
    # A user changing the time sends new values to all lights of the instance
    await async_check_lights(hass, context, runtime)

    # From here without await (one step of the event loop)
    options = entry.options
    if dt_util.parse_time(anchor_time(options, key)) == value:
        return False
    other_key = CONF_SLEEP_TIME if key == CONF_WAKE_TIME else CONF_WAKE_TIME
    other = dt_util.parse_time(anchor_time(options, other_key)) or value
    wake, sleep = (value, other) if key == CONF_WAKE_TIME else (other, value)
    if error := anchor_pair_error(wake, sleep):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key=error,
            translation_placeholders={"wake": wake.strftime("%H:%M"), "sleep": sleep.strftime("%H:%M")},
        )

    new_value = value.strftime("%H:%M:00")
    new_options = {**options, key: new_value}
    curve = options.get(CONF_CURVE_CONFIG)
    lifted = bool(curve) and not (curve.get(CONF_WAKE_TIME) and curve.get(CONF_SLEEP_TIME))
    if lifted:
        # Version 2 counts as drawn for the times so far: keep them as reference
        new_options[CONF_CURVE_CONFIG] = {
            "version": 3,
            "points": curve.get("points") or [],
            CONF_WAKE_TIME: anchor_time(options, CONF_WAKE_TIME),
            CONF_SLEEP_TIME: anchor_time(options, CONF_SLEEP_TIME),
        }
    # Only what this change sets: another change still waiting for the update
    # listener (e.g. options just saved) must reload as before
    applied = runtime.applied_config
    changes = {"options": {**applied.options, key: new_value}}
    if lifted:
        changes["curve"] = new_options[CONF_CURVE_CONFIG]
    runtime.applied_config = dataclasses.replace(applied, **changes)
    hass.config_entries.async_update_entry(entry, options=new_options)

    calculator = runtime.calculator
    if not calculator.preview_active:
        # A running preview stays until it is saved, reverted or reloaded
        calculator.calculate_curve_from_points(saved_points(new_options))
    if key == CONF_WAKE_TIME and runtime.mode_select is not None:
        runtime.mode_select.async_wake_time_changed()
    _LOGGER.debug("%s of %s set to %s", key, entry.title, new_value)
    # Lights, sensors and card (also for a scenario that ended just now)
    async_dispatcher_send(hass, signal_update(entry.entry_id), context)
    return True


class HCLAnchorTime(HCLEntity, TimeEntity):
    """Wake or sleep time of an instance (stored in its options)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, entry: HCLConfigEntry, key: str) -> None:
        """Initialize."""
        super().__init__(entry, key)
        self._key = key
        self._attr_translation_key = key

    @property
    def native_value(self) -> time | None:
        """The stored time (the options are the only storage, no restore needed)."""
        return dt_util.parse_time(anchor_time(self._entry.options, self._key))

    async def async_set_value(self, value: time) -> None:
        """Set the time (action time.set_value)."""
        if await async_set_anchor_time(self.hass, self._entry, self._key, value, action_context(self)):
            self.async_write_ha_state()
