"""Switch platform for HCL Lighting."""
from __future__ import annotations

import logging
import asyncio
from typing import Any
from datetime import timedelta
import voluptuous as vol

from homeassistant.util import dt as dt_util

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback, async_get_current_platform
from homeassistant.util.dt import utcnow
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.service import async_call_from_config
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.const import EVENT_CALL_SERVICE, ENTITY_MATCH_ALL

from .const import (
    DOMAIN,
    CONF_TARGET,
    CONF_SMART_TRANSITION,
    CONF_MIN_BRIGHTNESS,
    CONF_MAX_BRIGHTNESS,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_MAX_BRIGHTNESS,
    CONF_WAKE_TIME,
    CONF_MIDDAY_TIME,
    CONF_SLEEP_TIME,
    DEFAULT_WAKE_TIME,
    DEFAULT_MIDDAY_TIME,
    DEFAULT_SLEEP_TIME,
    SERVICE_UPDATE_CURVE,
    CONF_CURVE_CONFIG,
    IGNORE_WINDOW_SECONDS,
    CONF_UPDATE_INTERVAL,
    CONF_TRANSITION,
    CONF_TURN_ON_TRANSITION,
    CONF_RESPECT_TURN_ON_VALUES,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_TRANSITION,
    DEFAULT_TURN_ON_TRANSITION,
    DEFAULT_RESPECT_TURN_ON_VALUES,
)

from .logic.hcl_math import HCLCalculator
from .logic.override_manager import OverrideManager
from .logic.light_controller import HCLLightController

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    """Set up the HCL Switch from a config entry."""
    
    # Retrieve Shared Logic Core
    logic_core = hass.data[DOMAIN][entry.entry_id]
    hcl_calc = logic_core["calculator"]
    controller = logic_core["controller"]
    override_manager = logic_core["override_manager"]
    
    switch = HCLSwitch(hass, entry, controller, hcl_calc, override_manager)

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
        self._resolved_targets = set() # Cache for target entities
        
        # Modules
        self.hcl_calc = hcl_calc
        self.override_manager = override_manager
        self.controller = controller

        # Concurrency Guard
        self._update_lock = asyncio.Lock()

        options = entry.options
        self._update_interval = int(options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
        self._transition = float(options.get(CONF_TRANSITION, DEFAULT_TRANSITION))
        self._turn_on_transition = float(options.get(CONF_TURN_ON_TRANSITION, DEFAULT_TURN_ON_TRANSITION))
        self._respect_turn_on_values = bool(
            options.get(CONF_RESPECT_TURN_ON_VALUES, DEFAULT_RESPECT_TURN_ON_VALUES)
        )
        self._cancel_reresolve = None

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        
        # Restore State
        if last_state := await self.async_get_last_state():
            if last_state.state == STATE_ON:
                self._is_on = True
                await self.async_turn_on()

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
        self._is_on = False # Prevent further updates
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
        await self._update_hcl()

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
                await self._update_hcl()

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
    def _handle_global_update(self):
        """Handle global update signal (scenario change, curve preview/apply/save)."""
        # New target values take precedence over a smooth return still running
        self.override_manager.end_reengaging()
        self.hass.async_create_task(self._update_hcl())

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._is_on

    @property
    def device_info(self):
        """Return device info."""
        from homeassistant.helpers.entity import DeviceInfo
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="HCL Integration",
            model="HCL Controller",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        targets = self._resolved_targets or []
        return {
            "calculated_brightness": self._calculated_brightness,
            "calculated_color_temp": self._calculated_kelvin,
            "target_entities": list(targets),
            "manual_control": self.override_manager.overridden_entities(),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
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

        # Immediate update
        await self._update_hcl()

    async def _re_evaluate_targets_and_listeners(self) -> None:
        """Re-evaluate target entities and update state listeners."""
        # Stop existing listener if any
        if self._state_listener_remove_callback:
            self._state_listener_remove_callback()
            self._state_listener_remove_callback = None

        # Resolve targets dynamically
        self._resolved_targets = self.controller.resolve_targets(
            self._entry.options.get(CONF_TARGET) or self._entry.data.get(CONF_TARGET) or {}
        )
        
        # Start new listener if targets exist
        if self._resolved_targets and self._state_listener_remove_callback is None:
            self._state_listener_remove_callback = async_track_state_change_event(
                self.hass, list(self._resolved_targets), self._handle_light_state_change
            )
        _LOGGER.debug("HCL Switch targets re-evaluated. Listening to: %s", self._resolved_targets)


    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        self._is_on = False
        self.async_write_ha_state() # Ensure UI updates immediately
        
        if self._timer_remove_callback:
            self._timer_remove_callback()
            self._timer_remove_callback = None
            
        if self._state_listener_remove_callback:
            self._state_listener_remove_callback()
            self._state_listener_remove_callback = None

    async def _update_hcl(self, now=None):
        """Main HCL Update Loop."""
        if not self._is_on:
             return
             
        # prevent reentrancy
        if self._update_lock.locked():
             _LOGGER.warning("Update loop skipped: Previous cycle still running!")
             return

        async with self._update_lock:
            try:
                # 1. Calculate Target Values (Delegate to Controller Priority Stack)
                brightness, kelvin = self.controller.calculate_target_values(dt_util.now())
                
                # Check for "Sleep Mode / Off" or "Guest Mode / Freeze"
                if brightness is None and kelvin is None:
                    # GUEST MODE: no updates, no re-engagement
                    self.async_write_ha_state()
                    return

                # Special Case: Sleep Mode handling (If brightness is 0)
                # calculate_target_values returns 0, 2000 for sleep
                is_sleep = (brightness == 0)
                
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
                            eid, self._calculated_brightness, self._calculated_kelvin
                        )

                # 4. Filter Active Lights (not overridden, not in their smooth return)
                active_lights = []
                for eid in all_lights:
                    state = self.hass.states.get(eid)
                    # Only control lights that are currently ON
                    if (
                        state
                        and state.state == STATE_ON
                        and not self.override_manager.is_overridden(eid)
                        and not self.override_manager.is_reengaging(eid)
                    ):
                        active_lights.append(eid)
                
                # 5. Apply Batch
                if active_lights:
                    await self.controller.apply_batch(
                        active_lights, 
                        self._calculated_brightness, 
                        self._calculated_kelvin,
                        transition=self._transition
                    )
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

                     # Synchronous Update to Override Manager (Fix Race Condition)
                     self.override_manager.set_last_set_values(
                         entity_id, fresh_b, self.controller.reachable_kelvin(entity_id, fresh_k, new_state)
                     )
                     
                     # Set ignore window SYNCHRONOUSLY before task runs to prevent self-detection
                     self.override_manager.set_ignore_window(
                         entity_id, IGNORE_WINDOW_SECONDS + self._turn_on_transition
                     )

                     # Await immediately to block handling of subsequent events until command is sent
                     await self.controller.apply_fast(
                         entity_id, 
                         fresh_b, 
                         fresh_k,
                         state_obj=new_state,
                         transition=self._turn_on_transition,
                     )
                     # IMPORTANT: Return here to avoid detecting this initial state as an override
                     return

            # 2. State reports caused by HCL's own commands (also late or
            # intermediate ones during a transition) are never manual control
            if self.controller.is_own_context(new_state.context):
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
        from homeassistant.helpers.entity import DeviceInfo
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="HCL Integration",
            model="HCL Controller",
        )

    async def _async_set(self, value: bool) -> None:
        setattr(self._controller, self._key, value)
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, f"{DOMAIN}_{self._entry.entry_id}_update")

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Let HCL adapt this attribute."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop adapting this attribute (it stays as it is)."""
        await self._async_set(False)
