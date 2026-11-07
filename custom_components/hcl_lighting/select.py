"""Select platform for HCL Lighting."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from collections.abc import Mapping
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.restore_state import ExtraStoredData, RestoredExtraData, RestoreEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .const import (
    HCL_MODES,
    MODE_AUTO,
    TIMED_MODES,
    CONF_SCENARIO_DURATION,
    DEFAULT_SCENARIO_DURATION,
    NIGHT_MODES,
    CONF_WAKE_TIME,
    DEFAULT_WAKE_TIME,
    anchor_time,
    signal_update,
)
from .logic.light_controller import HCLLightController
from .entity import HCLEntity
from .runtime import HCLConfigEntry
from .ha_internals import action_context
from .services import async_check_lights

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: HCLConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the HCL Select entity."""
    select = HCLModeSelect(entry, entry.runtime_data.controller)
    entry.runtime_data.mode_select = select
    async_add_entities([select])

def wake_occurrence(local_date: date, wake: time) -> datetime:
    """The wake time on a local date in the Home Assistant time zone (fold=0:
    a doubled hour at the change from summer time is its first occurrence, a
    missing hour counts as summer time, e.g. 02:30 becomes 03:30)."""
    return datetime.combine(local_date, wake.replace(second=0, microsecond=0), tzinfo=dt_util.get_default_time_zone())


def restored_scenario(state: State | None, extra: Mapping[str, Any] | None) -> tuple[str, datetime | None]:
    """Scenario and end time from the stored state of the mode select: Auto if
    unknown (also the removed Guest, RM-R12) or the timed scenario has ended; an
    end time that is not a time is
    ignored. The only rule for both the mode select and the first light command
    after a setup (RM-T27, see _restored_mode in __init__)."""
    if state is None or state.state not in HCL_MODES:
        return MODE_AUTO, None
    until_iso = (extra or {}).get("until")
    until = dt_util.parse_datetime(until_iso) if isinstance(until_iso, str) else None
    if until is not None and until <= dt_util.utcnow():
        # The timed scenario ended while Home Assistant was not running
        return MODE_AUTO, None
    return state.state, until


class HCLModeSelect(HCLEntity, SelectEntity, RestoreEntity):
    """Select entity for the HCL scenario (mode)."""

    _attr_translation_key = "hcl_mode"

    def __init__(self, entry: ConfigEntry, controller: HCLLightController) -> None:
        """Initialize."""
        super().__init__(entry, "mode")
        self._controller = controller
        self._attr_options = HCL_MODES
        self._attr_current_option = controller.active_mode
        # End of a timed scenario (Focus/Relax/Cleaning with a configured duration)
        self._until: datetime | None = None
        # The end is the wake time (Sleep/Night light without duration): it
        # follows a new wake time (RM-E05)
        self._ends_at_wake = False
        self._cancel_timer = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """End time of a timed scenario (None if the mode has no end)."""
        return {"until": self._until.isoformat() if self._until else None}

    @property
    def extra_restore_state_data(self) -> ExtraStoredData:
        """Keep the end time of a timed scenario across restarts."""
        return RestoredExtraData(
            {"until": self._until.isoformat() if self._until else None, "ends_at_wake": self._ends_at_wake}
        )

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        self.async_on_remove(self._stop_timer)

        # Restore State (same rule as for the first light command, RM-T27)
        if last_state := await self.async_get_last_state():
            extra = await self.async_get_last_extra_data()
            extra_data = extra.as_dict() if extra is not None else None
            mode, until = restored_scenario(last_state, extra_data)
            self._set_mode(mode, announce=False)
            if until is not None:
                self._schedule_end(until)
                # Data of older versions without the field: the end stays
                self._ends_at_wake = (extra_data or {}).get("ends_at_wake") is True
            _LOGGER.debug("Restored HCL Mode to %s", self._attr_current_option)

    def _set_mode(self, option: str, announce: bool = True) -> None:
        self._controller.set_active_mode(option, announce=announce)
        self._attr_current_option = option

    def _wake_time(self) -> time:
        return dt_util.parse_time(anchor_time(self._entry.options, CONF_WAKE_TIME)) or dt_util.parse_time(
            DEFAULT_WAKE_TIME
        )

    def _next_wake_time(self) -> datetime:
        """Next occurrence of the wake time (UTC) in the Home Assistant time zone."""
        wake = self._wake_time()
        today = dt_util.now().date()
        candidate = dt_util.as_utc(wake_occurrence(today, wake))
        if candidate <= dt_util.utcnow():
            candidate = dt_util.as_utc(wake_occurrence(today + timedelta(days=1), wake))
        return candidate

    @callback
    def async_wake_time_changed(self) -> None:
        """The wake time changed: move an end that comes from it (RM-O23-3).

        The new end is the occurrence of the new wake time closest to the old
        end (a tie: the later one); if it is not in the future, the scenario
        ends now. No signal: the caller sends one for the scenario change and
        the new curve.
        """
        if not self._ends_at_wake or self._until is None:
            return
        wake = self._wake_time()
        day = dt_util.as_local(self._until).date()
        candidates = [dt_util.as_utc(wake_occurrence(day + timedelta(days=k), wake)) for k in (-1, 0, 1)]
        old_end = self._until
        new_end = min(candidates, key=lambda c: (abs(c - old_end), -c.timestamp()))
        self._stop_timer()
        if new_end <= dt_util.utcnow():
            self._cancel()
            self._ends_at_wake = False
            self._set_mode(MODE_AUTO)
        else:
            self._schedule_end(new_end)
        self.async_write_ha_state()

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
        after this time (0 = until changed) instead of the default end
        (configured duration for Focus/Relax/Cleaning, the next wake time for
        Sleep and Night light).
        """
        # A user's choice sends the scenario values to all lights at once; the
        # automatic end of a scenario (timer) is no action of that user
        context = action_context(self)
        await async_check_lights(self.hass, context, self._entry.runtime_data)
        self._cancel()
        self._ends_at_wake = False
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
        elif option in NIGHT_MODES:
            # Sleep and Night light end at the next wake time (back to the curve)
            self._schedule_end(self._next_wake_time())
            self._ends_at_wake = True
        self.async_write_ha_state()

        # Apply the new mode immediately (the switch and the curve sensor listen);
        # the context of the request is passed on to the light commands
        async_dispatcher_send(self.hass, signal_update(self._entry.entry_id), context)
