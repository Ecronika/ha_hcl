"""Switch platform for HCL Lighting."""
from __future__ import annotations

import logging
import asyncio
from typing import Any
from datetime import timedelta

from homeassistant.util import dt as dt_util

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.core import Context, HomeAssistant, callback, Event
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.const import EVENT_CALL_SERVICE, ENTITY_MATCH_ALL

from .const import (
    DOMAIN,
    CONF_TARGET,
    COMMAND_TIMEOUT_SECONDS,
    CONF_UPDATE_INTERVAL,
    CONF_TRANSITION,
    CONF_RESPECT_TURN_ON_VALUES,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_TRANSITION,
    DEFAULT_RESPECT_TURN_ON_VALUES,
    CONF_SCENARIO_TRANSITION,
)

from .conflicts import async_check_conflicts
from .logic.hcl_math import HCLCalculator
from .logic.override_manager import OverrideManager
from .logic.light_controller import HCLLightController
from .services import action_context, async_check_lights

_LOGGER = logging.getLogger(__name__)


def configured_target(entry: ConfigEntry) -> dict[str, Any]:
    """Target of an instance (an empty target means no lights, RM-B35)."""
    return entry.options.get(CONF_TARGET) or {}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    """Set up the HCL Switch from a config entry."""
    
    # Retrieve Shared Logic Core
    logic_core = hass.data[DOMAIN][entry.entry_id]
    hcl_calc = logic_core["calculator"]
    controller = logic_core["controller"]
    override_manager = logic_core["override_manager"]
    
    switch = HCLSwitch(hass, entry, controller, hcl_calc, override_manager)
    logic_core["switch"] = switch

    async_add_entities([
        switch,
        HCLAdaptSwitch(entry, controller, "adapt_brightness", "mdi:brightness-6"),
        HCLAdaptSwitch(entry, controller, "adapt_color", "mdi:thermometer"),
    ])


# Light service attributes that change brightness or colour (used to recognise
# manual control through Home Assistant: apps, scenes, automations, voice)
_BRIGHTNESS_ATTRS = {"brightness", "brightness_pct", "brightness_step", "brightness_step_pct"}
_COLOR_ATTRS = {
    "color_temp", "color_temp_kelvin", "kelvin", "xy_color", "hs_color", "rgb_color",
    "rgbw_color", "rgbww_color", "color_name", "white", "effect",
}
_TARGET_KEYS = ("entity_id", "device_id", "area_id", "floor_id", "label_id")

class HCLSwitch(RestoreEntity, SwitchEntity):
    """Representation of a HCL Lighting Switch."""

    _attr_has_entity_name = True
    _attr_translation_key = "hcl_switch"
    # Live state only: the calculated values change with every curve step
    # (history: target value sensors), the light list is large and manual
    # control has its own event and logbook entries. Recording them would
    # store a new attribute row with the full light list many times a day.
    _unrecorded_attributes = frozenset({
        "calculated_brightness", "calculated_color_temp", "target_entities", "manual_control",
    })

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller: HCLLightController, hcl_calc: HCLCalculator, override_manager: OverrideManager) -> None:
        """Initialize the switch."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = entry.entry_id
        
        # State
        self._attr_is_on = False
        self._attr_icon = "mdi:theme-light-dark"
        
        self._timer_remove_callback = None
        self._state_listener_remove_callback = None
        
        self._calculated_brightness = None
        self._calculated_kelvin = None
        
        self._is_on = False # Internal state for update loop control
        # Set while the entity is added to Home Assistant; a disabled main
        # switch is never added and the instance does nothing (RM-B38)
        self._added = False
        self._resolved_targets = set() # Cache for target entities
        
        # Modules
        self.hcl_calc = hcl_calc
        self.override_manager = override_manager
        self.controller = controller

        # Concurrency guard: one light update at a time (periodic cycle,
        # requested update or apply service). The timer skips a cycle while
        # the lock is held; requested updates wait and are coalesced.
        self._update_lock = asyncio.Lock()
        self._update_requested = False
        self._request_context: Context | None = None
        # New target values (scenario, curve) end running transition
        # protections - in request order, i.e. only when the requested update
        # holds the lock (an older apply or cycle may still set a protection)
        self._end_protection_requested = False

        options = entry.options
        self._update_interval = int(options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
        self._transition = float(options.get(CONF_TRANSITION, DEFAULT_TRANSITION))
        # Transition when the scenario changes (default: the update transition)
        self._scenario_transition = float(options.get(CONF_SCENARIO_TRANSITION, self._transition))
        self._respect_turn_on_values = bool(
            options.get(CONF_RESPECT_TURN_ON_VALUES, DEFAULT_RESPECT_TURN_ON_VALUES)
        )
        self._cancel_reresolve = None
        # Light groups among the targets (their member lists are watched)
        self._target_groups: set[str] = set()
        self._group_listener_remove_callback = None

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        self._added = True

        # Restore State: timer and listeners start at once, the first update
        # runs in the background - the setup (also a reload) does not wait
        # for the light commands (RM-B37)
        if last_state := await self.async_get_last_state():
            if last_state.state == STATE_ON:
                await self._async_start()
                self._entry.async_create_background_task(
                    self.hass, self.async_request_update(), f"{DOMAIN} first update"
                )

        # Target groups (and other light platforms) may still be loading during
        # HA startup; resolve the targets again once startup has finished.
        if not self.hass.is_running:
            self.async_on_remove(async_at_started(self.hass, self._async_hass_started))

        # Manual control through Home Assistant (apps, scenes, automations, voice)
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_CALL_SERVICE, self._handle_service_call)
        )

        # Keep the manual_control attribute current
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{DOMAIN}_{self._entry.entry_id}_overrides", self._handle_overrides_changed
            )
        )

        # Targets given as devices, areas, floors, labels or groups can change
        for event_type in (
            er.EVENT_ENTITY_REGISTRY_UPDATED,
            dr.EVENT_DEVICE_REGISTRY_UPDATED,
            ar.EVENT_AREA_REGISTRY_UPDATED,
        ):
            self.async_on_remove(self.hass.bus.async_listen(event_type, self._handle_registry_updated))
        self.async_on_remove(self._cancel_pending_reresolve)

        # Subscribe to global updates (from service)
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, 
                f"{DOMAIN}_{self._entry.entry_id}_update",
                self._handle_global_update
            )
        )

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        self._added = False
        self._is_on = False # Prevent further updates
        if self._group_listener_remove_callback:
            self._group_listener_remove_callback()
            self._group_listener_remove_callback = None
        if self._timer_remove_callback:
            self._timer_remove_callback()
            self._timer_remove_callback = None
            
        if self._state_listener_remove_callback:
            self._state_listener_remove_callback()
            self._state_listener_remove_callback = None

    async def _async_hass_started(self, _hass: HomeAssistant) -> None:
        """Re-resolve targets after HA startup (groups are expanded only when loaded)."""
        if not self._is_on:
            return
        await self._re_evaluate_targets_and_listeners()
        await self.async_request_update()

    @callback
    def _handle_overrides_changed(self) -> None:
        self.async_write_ha_state()

    @callback
    def _cancel_pending_reresolve(self) -> None:
        if self._cancel_reresolve:
            self._cancel_reresolve()
            self._cancel_reresolve = None

    @callback
    def _handle_registry_updated(self, _event) -> None:
        """Re-resolve the targets shortly after registry changes (debounced)."""
        if not self._is_on:
            return
        self._cancel_pending_reresolve()

        async def _reresolve(_now) -> None:
            self._cancel_reresolve = None
            if not self._is_on:
                return
            old_targets = set(self._resolved_targets)
            await self._re_evaluate_targets_and_listeners()
            if self._resolved_targets != old_targets:
                await self.async_request_update()

        self._cancel_reresolve = async_call_later(self.hass, 2, _reresolve)

    @callback
    def _handle_service_call(self, event) -> None:
        """Mark lights as manually controlled when HA changes them with own values.

        HCL's own commands carry an HCL context and are ignored. A command that
        sets brightness or colour on a light that is on pauses HCL for that light
        (only for the attributes HCL adapts). A turn-on command with own values
        for a light that is off is respected only if configured.
        """
        if not self._is_on:
            return
        data = event.data
        if data.get("domain") != "light" or data.get("service") not in ("turn_on", "toggle"):
            return
        if self.controller.is_own_context(event.context):
            return

        service_data = data.get("service_data") or {}
        keys = set(service_data)
        profile = "profile" in keys
        touches_brightness = profile or bool(keys & _BRIGHTNESS_ATTRS)
        touches_color = profile or bool(keys & _COLOR_ATTRS)
        if not (
            (touches_brightness and self.controller.adapt_brightness)
            or (touches_color and self.controller.adapt_color)
        ):
            return

        target = {}
        for key in _TARGET_KEYS:
            value = service_data.get(key)
            if not value:
                continue
            if isinstance(value, str):
                value = [v.strip() for v in value.split(",")]
            target[key] = value
        if ENTITY_MATCH_ALL in target.get("entity_id", []):
            lights = set(self._resolved_targets)
        else:
            lights = self.controller.resolve_targets(target) & self._resolved_targets

        for entity_id in lights:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state == STATE_ON:
                if data["service"] == "toggle":
                    continue  # toggling a light that is on switches it off
                self.override_manager.set_override(entity_id)
            elif self._respect_turn_on_values:
                self.override_manager.set_override(entity_id)

    # async_options_updated is handled by reload in __init__.py

    @callback
    def _handle_global_update(self, context: Context | None = None):
        """Handle global update signal (scenario change, curve preview/apply/save)."""
        # New target values take precedence over a smooth return or a long
        # transition still running. The protection ends when this update runs
        # (after older requests), not now: an older apply or scenario update
        # that is still waiting would otherwise set its protection afterwards
        # and block this update for the length of its transition.
        self._end_protection_requested = True
        self.hass.async_create_task(self.async_request_update(context))

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._is_on

    @property
    def resolved_targets(self) -> set[str]:
        """Lights this instance controls (resolved targets)."""
        return set(self._resolved_targets)

    @property
    def instance_name(self) -> str:
        """Name of the HCL instance (config entry title)."""
        return self._entry.title

    @property
    def device_info(self):
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="HCL Integration",
            model="HCL Controller",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return {
            "calculated_brightness": self._calculated_brightness,
            "calculated_color_temp": self._calculated_kelvin,
            # sorted: resolving the same lights again changes nothing
            "target_entities": sorted(self._resolved_targets or ()),
            "manual_control": self.override_manager.overridden_entities(),
        }

    @property
    def is_added(self) -> bool:
        """Whether the main switch is added (not disabled): the instance runs."""
        return self._added

    def controlled_lights(self) -> set[str]:
        """Lights of this instance, resolved now (for permission checks).

        Not the runtime cache: it is not kept current while HCL is off, so a
        light that joined an area or group meanwhile would be missing (RM-B34).
        """
        return self.controller.resolve_targets(configured_target(self._entry))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        context = action_context(self)
        # A user switching HCL on sends the HCL values to all its lights
        await async_check_lights(self.hass, context, self.hass.data[DOMAIN][self._entry.entry_id])
        await self._async_start()
        # Immediate update (linked to the request that switched HCL on)
        await self.async_request_update(context)

    async def _async_start(self) -> None:
        """Switch the update loop on: timer, targets and listeners."""
        if not self._is_on:
            # Switched on (or set up again): HCL takes its lights back at
            # once. Transition protections from before (a long apply, scenario
            # or turn-on transition) end - in request order, like a scenario
            # change - instead of blocking the lights until they run out.
            self._end_protection_requested = True
        self._is_on = True
        self.async_write_ha_state() # Ensure UI updates immediately
        
        # Start Timer
        if self._timer_remove_callback is None:
            self._timer_remove_callback = async_track_time_interval(
                self.hass,
                self._update_hcl, # Main Loop
                timedelta(seconds=self._update_interval)
            )
        
        await self._re_evaluate_targets_and_listeners()

    async def _re_evaluate_targets_and_listeners(self) -> None:
        """Re-evaluate target entities and update state listeners."""
        # Stop existing listener if any
        if self._state_listener_remove_callback:
            self._state_listener_remove_callback()
            self._state_listener_remove_callback = None

        # Resolve targets dynamically
        groups: set[str] = set()
        self._resolved_targets = self.controller.resolve_targets(
            configured_target(self._entry),
            groups=groups,
        )
        self._watch_groups(groups)
        async_check_conflicts(self.hass)
        
        # Start new listener if targets exist
        if self._resolved_targets and self._state_listener_remove_callback is None:
            self._state_listener_remove_callback = async_track_state_change_event(
                self.hass, list(self._resolved_targets), self._handle_light_state_change
            )
        _LOGGER.debug("HCL Switch targets re-evaluated. Listening to: %s", self._resolved_targets)


    @callback
    def _watch_groups(self, groups: set[str]) -> None:
        """Re-resolve the targets when the members of a target light group change."""
        if groups == self._target_groups and self._group_listener_remove_callback:
            return
        if self._group_listener_remove_callback:
            self._group_listener_remove_callback()
            self._group_listener_remove_callback = None
        self._target_groups = set(groups)
        if not groups:
            return

        @callback
        def _group_changed(event: Event) -> None:
            old = event.data.get("old_state")
            new = event.data.get("new_state")
            members = lambda st: tuple(st.attributes.get("entity_id") or ()) if st else ()  # noqa: E731
            if members(old) != members(new):
                self._handle_registry_updated(event)

        self._group_listener_remove_callback = async_track_state_change_event(
            self.hass, list(groups), _group_changed
        )

    async def async_apply(
        self,
        lights: list[str] | None,
        transition: float | None,
        release_manual_control: bool,
        context: Context | None = None,
    ) -> None:
        """Send the current HCL values now (service hcl_lighting.apply).

        Never switches a light on; lights under manual control are skipped
        unless release_manual_control is set. Runs after an update cycle that
        is still sending. The values are those at the time of the request: a
        scenario change requested later is sent after it, with its own values
        and transition. Raises HomeAssistantError if a light command failed or
        a light did not answer in time.
        """
        brightness, kelvin = self.controller.calculate_target_values(dt_util.now())
        if brightness is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="guest_mode")
        if not self._resolved_targets:
            await self._re_evaluate_targets_and_listeners()
        targets = self._checked_lights(lights)
        async with self._update_lock:
            if release_manual_control:
                for eid in targets:
                    self.override_manager.reset_override(eid)
            active = [
                eid for eid in targets
                if (state := self.hass.states.get(eid)) is not None
                and state.state == STATE_ON
                and not self.override_manager.is_overridden(eid)
            ]
            for eid in active:
                self.override_manager.end_reengaging(eid)
            if not active:
                return
            transition = self._transition if transition is None else float(transition)
            result = await self.controller.apply_batch(
                active, brightness, kelvin, transition=transition, parent=context
            )
            # A transition longer than the update transition must not be cut
            # short by the next update cycles (like a long scenario transition);
            # a scenario change, a new apply or switching the light off ends it.
            if transition > self._transition:
                for eid in result.updated:
                    self.override_manager.set_reengaging(eid, transition)
        if result.failed or result.pending:
            # Like Home Assistant's own light actions: the caller learns about
            # the failure (the other lights have been updated)
            first = next(iter(result.failed.values()), None)
            placeholders = {
                "failed": ", ".join(sorted(result.failed)),
                "error": str(first),
                "pending": ", ".join(sorted(result.pending)),
                "seconds": str(COMMAND_TIMEOUT_SECONDS),
            }
            if result.failed and result.pending:
                key = "lights_failed_and_no_answer"
            else:
                key = "lights_failed" if result.failed else "lights_no_answer"
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key=key, translation_placeholders=placeholders
            ) from first

    async def async_set_manual_control(
        self, lights: list[str] | None, manual_control: bool, context: Context | None = None
    ) -> None:
        """Pause lights (manual control) or hand them back to HCL (service)."""
        if not self._resolved_targets:
            await self._re_evaluate_targets_and_listeners()
        targets = self._checked_lights(lights)
        for eid in targets:
            if manual_control:
                self.override_manager.set_override(eid)
            else:
                self.override_manager.reset_override(eid)
        if not manual_control:
            await self.async_request_update(context)

    def _checked_lights(self, lights: list[str] | None) -> list[str]:
        if not lights:
            return sorted(self._resolved_targets)
        unknown = sorted(set(lights) - self._resolved_targets)
        if unknown:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_controlled",
                translation_placeholders={"lights": ", ".join(unknown)},
            )
        return list(lights)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        self._is_on = False
        self.async_write_ha_state() # Ensure UI updates immediately
        async_check_conflicts(self.hass)
        
        if self._timer_remove_callback:
            self._timer_remove_callback()
            self._timer_remove_callback = None
            
        if self._state_listener_remove_callback:
            self._state_listener_remove_callback()
            self._state_listener_remove_callback = None

        # The member lists of target groups are watched only while HCL is on
        self._watch_groups(set())
        self._cancel_pending_reresolve()

    async def async_request_update(self, context: Context | None = None) -> None:
        """Run an update now (scenario change, curve preview/revert, release of
        manual control, targets changed, HCL switched on).

        Unlike the periodic timer, a request is never dropped: if a cycle is
        still sending, the request waits and runs afterwards. Requests that
        arrive while waiting are combined into one cycle with the newest values.
        """
        if not self._is_on:
            return
        self._update_requested = True
        if context is not None:
            self._request_context = context
        async with self._update_lock:
            if not self._update_requested:
                return  # a cycle that started after this request covered it
            await self._run_cycle()

    async def _update_hcl(self, now=None):
        """Periodic HCL update (timer)."""
        if not self._is_on:
            return
        # A cycle, a requested update or an apply is still sending: the next
        # tick follows anyway, requested updates are not affected.
        if self._update_lock.locked():
            _LOGGER.debug("Periodic update skipped: previous update still running")
            return
        async with self._update_lock:
            await self._run_cycle()

    async def _run_cycle(self) -> None:
        """One update of all lights (caller holds the update lock)."""
        self._update_requested = False
        parent = self._request_context
        self._request_context = None
        if self._end_protection_requested:
            self._end_protection_requested = False
            self.override_manager.end_reengaging()
        if not self._is_on:
            return
        try:
            # 1. Calculate Target Values (Delegate to Controller Priority Stack)
            brightness, kelvin = self.controller.calculate_target_values(dt_util.now())
            
            # Check for "Sleep Mode / Off" or "Guest Mode / Freeze"
            if brightness is None and kelvin is None:
                # GUEST MODE: no updates, no re-engagement
                self.async_write_ha_state()
                return

            # Update State for UI/Debugging
            self._calculated_brightness = brightness
            self._calculated_kelvin = kelvin
            _LOGGER.debug(
                "HCL Update Cycle: Target B=%s%%, K=%sK", 
                self._calculated_brightness, self._calculated_kelvin
            )
            self.async_write_ha_state()

            # 2. Resolve Targets (Cached)
            all_lights = self._resolved_targets
            
            # Prune cache to avoid memory leaks (Both Controller and Override Manager)
            self.controller.prune_cache(all_lights)
            self.override_manager.prune_stale_entities(all_lights)
            
            # Lights that are off are no longer under manual control
            # (covers switch-offs HCL did not see, e.g. while it was off)
            if self.override_manager.reset_on_off:
                for eid in self.override_manager.overridden_entities():
                    eid_state = self.hass.states.get(eid)
                    if eid_state is not None and eid_state.state == STATE_OFF:
                        self.override_manager.reset_override(eid)

            # 3. Check for Re-engagements (Expired Overrides)
            expired_overrides = self.override_manager.get_pending_reengagements()
            for eid in expired_overrides:
                # Only lights that are still on are brought back to HCL;
                # re-engaging must never switch a light on.
                eid_state = self.hass.states.get(eid)
                if eid in all_lights and eid_state and eid_state.state == STATE_ON:
                    await self.controller.reengage_light(
                        eid, self._calculated_brightness, self._calculated_kelvin, parent=parent
                    )

            # 4. Filter Active Lights (not overridden, not in their smooth return)
            active_lights = []
            for eid in all_lights:
                state = self.hass.states.get(eid)
                # Only control lights that are currently ON
                if (
                    state
                    and state.state == STATE_ON
                    and not self.override_manager.own_report_pending(eid, state)
                    and not self.override_manager.is_overridden(eid)
                    and not self.override_manager.is_reengaging(eid)
                ):
                    active_lights.append(eid)
            
            # 5. Apply Batch (a scenario change uses the scenario transition)
            scenario_change = self.controller.consume_mode_change()
            transition = self._scenario_transition if scenario_change else self._transition
            if active_lights:
                result = await self.controller.apply_batch(
                    active_lights, 
                    self._calculated_brightness, 
                    self._calculated_kelvin,
                    transition=transition,
                    parent=parent,
                )
                # The scenario transition may be longer than the update
                # interval: the following cycles must not cut it short
                if scenario_change and transition > self._transition:
                    for eid in result.updated:
                        self.override_manager.set_reengaging(eid, transition)
        except Exception:
             _LOGGER.exception("Error in HCL update loop")

    async def _handle_light_state_change(self, event: Event) -> None:
        """Handle state changes of monitored lights."""
        try:
            if not self._is_on:
                return
            
            entity_id = event.data.get("entity_id")
            old_state = event.data.get("old_state")
            new_state = event.data.get("new_state")

            if not entity_id or not new_state:
                return

            if new_state.state != STATE_ON:
                # A light that is off is no longer returning to HCL
                self.override_manager.end_reengaging(entity_id)

            # Back after unavailable/unknown: the length of the gap decides
            # whether its manual control ends (RM-B24)
            unreachable = (STATE_UNAVAILABLE, STATE_UNKNOWN)
            if (
                old_state is not None
                and old_state.state in unreachable
                and new_state.state not in unreachable
            ):
                self.override_manager.light_returned(entity_id, old_state)

            # 1. Fast Path (Turn On Event)
            if old_state and old_state.state != STATE_ON and new_state.state == STATE_ON:
                 # Just turned on.
                 if not self.override_manager.is_overridden(entity_id):
                     # RECALCULATE FRESH VALUES IMMEDIATELY via Controller
                     fresh_b, fresh_k = self.controller.calculate_target_values(dt_util.now())
                     
                     if fresh_b is None: # Guest mode active
                         return 
                         
                     if fresh_b == 0: # Sleep mode
                         # A light switched on during sleep mode counts as a manual
                         # override: it stays on until it is turned off again
                         # (or the override timeout expires).
                         self.override_manager.set_override(entity_id)
                         return
                     
                     # Update cache while we are at it
                     self._calculated_brightness = fresh_b
                     self._calculated_kelvin = fresh_k

                     # The light gets the values at once, without transition
                     # (RM-R10). apply_fast sets the tracking values and the
                     # ignore window synchronously before the command starts
                     # (no self-detection of the first state report). The
                     # command runs in the background (RM-T17); if it fails,
                     # the tracking is restored.
                     await self.controller.apply_fast(
                         entity_id,
                         fresh_b,
                         fresh_k,
                         state_obj=new_state,
                     )
                     # IMPORTANT: Return here to avoid detecting this initial state as an override
                     return

            # 2. State reports caused by HCL's own commands (also late or
            # intermediate ones during a transition) are no manual control.
            # Home Assistant gives a change on the device within 5 s after a
            # command the same context: one that moved away from the HCL
            # value is manual control (RM-B33).
            if self.controller.is_own_context(new_state.context):
                self.override_manager.check_own_report(entity_id, new_state, old_state)
                return

            # 3. Check for Manual Override
            is_override = self.override_manager.check_override(
                entity_id, 
                new_state,
                (self._calculated_brightness, self._calculated_kelvin), # Fallback Reference
                old_state=old_state
            )
            
            if is_override:
                return
        except Exception:
            _LOGGER.exception("Error handling state change for %s", event.data.get("entity_id", "unknown"))


class HCLAdaptSwitch(RestoreEntity, SwitchEntity):
    """Switch that enables adaptation of brightness or colour temperature."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, controller: HCLLightController, key: str, icon: str) -> None:
        """Initialize (key: adapt_brightness | adapt_color)."""
        self._entry = entry
        self._controller = controller
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        """Return true if HCL adapts this attribute."""
        return getattr(self._controller, self._key)

    @property
    def device_info(self):
        """Return device info (same HCL device as the main switch)."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="HCL Integration",
            model="HCL Controller",
        )

    async def _async_set(self, value: bool) -> None:
        context = action_context(self)
        # The change is applied to all lights at once
        await async_check_lights(self.hass, context, self.hass.data[DOMAIN][self._entry.entry_id])
        setattr(self._controller, self._key, value)
        self.async_write_ha_state()
        async_check_conflicts(self.hass)
        async_dispatcher_send(self.hass, f"{DOMAIN}_{self._entry.entry_id}_update", context)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Let HCL adapt this attribute."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop adapting this attribute (it stays as it is)."""
        await self._async_set(False)
