"""Select platform for HCL Lighting."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.restore_state import ExtraStoredData, RestoredExtraData, RestoreEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    HCL_MODES,
    MODE_AUTO,
    TIMED_MODES,
    CONF_SCENARIO_DURATION,
    DEFAULT_SCENARIO_DURATION,
    NIGHT_MODES,
    CONF_NIGHT_END_AT_WAKE,
    DEFAULT_NIGHT_END_AT_WAKE,
    CONF_WAKE_TIME,
    DEFAULT_WAKE_TIME,
)
from .logic.light_controller import HCLLightController

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the HCL Select entity."""
    logic_core = hass.data[DOMAIN][entry.entry_id]
    controller: HCLLightController = logic_core["controller"]
    
    select = HCLModeSelect(entry, controller)
    logic_core["mode_select"] = select
    async_add_entities([select])

class HCLModeSelect(SelectEntity, RestoreEntity):
    """Select entity for the HCL scenario (mode)."""

    _attr_has_entity_name = True
    _attr_translation_key = "hcl_mode"
    _attr_icon = "mdi:theme-light-dark"

    def __init__(self, entry: ConfigEntry, controller: HCLLightController) -> None:
        """Initialize."""
        self._entry = entry
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_mode"
        self._attr_options = HCL_MODES
        self._attr_current_option = controller.active_mode
        # End of a timed scenario (Focus/Relax/Cleaning with a configured duration)
        self._until: datetime | None = None
        self._cancel_timer = None

    @property
    def device_info(self):
        """Return device info (same HCL device as the switch and the sensor)."""
        from homeassistant.helpers.entity import DeviceInfo
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="HCL Integration",
            model="HCL Controller",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """End time of a timed scenario (None if the mode has no end)."""
        return {"until": self._until.isoformat() if self._until else None}

    @property
    def extra_restore_state_data(self) -> ExtraStoredData:
        """Keep the end time of a timed scenario across restarts."""
        return RestoredExtraData({"until": self._until.isoformat() if self._until else None})

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        self.async_on_remove(self._stop_timer)

        # Restore State
        if last_state := await self.async_get_last_state():
            if last_state.state in HCL_MODES:
                until = None
                if (extra := await self.async_get_last_extra_data()) is not None:
                    until_iso = extra.as_dict().get("until")
                    until = dt_util.parse_datetime(until_iso) if until_iso else None
                if until is not None and until <= dt_util.utcnow():
                    # The timed scenario ended while Home Assistant was not running
                    self._set_mode(MODE_AUTO, announce=False)
                else:
                    self._set_mode(last_state.state, announce=False)
                    if until is not None:
                        self._schedule_end(until)
                _LOGGER.debug("Restored HCL Mode to %s", self._attr_current_option)

    def _set_mode(self, option: str, announce: bool = True) -> None:
        self._controller.set_active_mode(option, announce=announce)
        self._attr_current_option = option

    def _next_wake_time(self) -> datetime:
        """Next occurrence of the wake time (UTC) in the Home Assistant time zone."""
        entry = self._entry
        wake = dt_util.parse_time(
            str(entry.options.get(CONF_WAKE_TIME) or entry.data.get(CONF_WAKE_TIME) or DEFAULT_WAKE_TIME)
        ) or dt_util.parse_time(DEFAULT_WAKE_TIME)
        now = dt_util.now()
        candidate = now.replace(hour=wake.hour, minute=wake.minute, second=0, microsecond=0)
        if candidate <= now:
            candidate = dt_util.as_local(
                dt_util.start_of_local_day(now + timedelta(days=1))
            ).replace(hour=wake.hour, minute=wake.minute)
        return dt_util.as_utc(candidate)

    def _stop_timer(self) -> None:
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None

    def _cancel(self) -> None:
        self._stop_timer()
        self._until = None

    def _schedule_end(self, until: datetime) -> None:
        self._until = until

        async def _end(_now) -> None:
            self._cancel_timer = None
            await self.async_select_option(MODE_AUTO)

        self._cancel_timer = async_track_point_in_utc_time(self.hass, _end, until)

    async def async_select_option(self, option: str, duration: int | None = None) -> None:
        """Change the selected option.

        duration (minutes, service hcl_lighting.set_scenario): end the scenario
        after this time (0 = until changed) instead of the configured behaviour.
        """
        self._cancel()
        self._set_mode(option)
        options = self._entry.options
        if option == MODE_AUTO:
            pass
        elif duration is not None:
            if duration > 0:
                self._schedule_end(dt_util.utcnow() + timedelta(minutes=duration))
        elif option in TIMED_MODES and int(options.get(CONF_SCENARIO_DURATION, DEFAULT_SCENARIO_DURATION)) > 0:
            minutes = int(options.get(CONF_SCENARIO_DURATION, DEFAULT_SCENARIO_DURATION))
            self._schedule_end(dt_util.utcnow() + timedelta(minutes=minutes))
        elif option in NIGHT_MODES and options.get(CONF_NIGHT_END_AT_WAKE, DEFAULT_NIGHT_END_AT_WAKE):
            self._schedule_end(self._next_wake_time())
        self.async_write_ha_state()

        # Apply the new mode immediately (the switch and the curve sensor listen)
        async_dispatcher_send(self.hass, f"{DOMAIN}_{self._entry.entry_id}_update")
