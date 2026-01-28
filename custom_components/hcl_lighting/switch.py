"""Switch platform for HCL Lighting."""
from __future__ import annotations

import logging
import asyncio
from typing import Any
from datetime import timedelta

from homeassistant.util import dt as dt_util

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.dt import utcnow
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.const import STATE_ON
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.service import async_call_from_config

from .const import (
    DOMAIN,
    CONF_TARGET,
    CONF_SMART_TRANSITION,
    CONF_MIN_BRIGHTNESS,
    CONF_MAX_BRIGHTNESS,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_MAX_BRIGHTNESS,
    UPDATE_INTERVAL_SECONDS,
    HCL_TRANSITION_SECONDS,
    CONF_WAKE_TIME,
    CONF_MIDDAY_TIME,
    CONF_SLEEP_TIME,
    DEFAULT_WAKE_TIME,
    DEFAULT_MIDDAY_TIME,
    DEFAULT_SLEEP_TIME
)

from .logic.hcl_math import HCLCalculator
from .logic.override_manager import OverrideManager
from .logic.light_controller import HCLLightController

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up the HCL Switch from a config entry."""
    
    # Initialize Logic Components
    # Initialize Logic Components
    override_manager = OverrideManager()
    hcl_calc = HCLCalculator()
    
    # Initial Curve Generation
    wake = entry.options.get(CONF_WAKE_TIME) or entry.data.get(CONF_WAKE_TIME) or DEFAULT_WAKE_TIME
    midday = entry.options.get(CONF_MIDDAY_TIME) or entry.data.get(CONF_MIDDAY_TIME) or DEFAULT_MIDDAY_TIME
    sleep = entry.options.get(CONF_SLEEP_TIME) or entry.data.get(CONF_SLEEP_TIME) or DEFAULT_SLEEP_TIME
    
    hcl_calc.generate_curve(wake, midday, sleep)
    
    controller = HCLLightController(hass, override_manager, entry)
    
    switch = HCLSwitch(hass, entry, controller, hcl_calc, override_manager)
    
    async_add_entities([switch])
    
    # NOTE: redundant listener removed to prevent race conditions.
    # __init__.py handles reload on options update.


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

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        
        # Restore State
        if last_state := await self.async_get_last_state():
            if last_state.state == STATE_ON:
                self._is_on = True
                await self.async_turn_on()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        self._is_on = False # Prevent further updates
        if self._timer_remove_callback:
            self._timer_remove_callback()
            self._timer_remove_callback = None
            
        if self._state_listener_remove_callback:
            self._state_listener_remove_callback()
            self._state_listener_remove_callback = None

    async def async_options_updated(self, entry: ConfigEntry) -> None:
        """Handle options update."""
        _LOGGER.debug("HCL Switch options updated. Re-evaluating targets.")
        self._entry = entry # Update the entry reference
        
        # Regenerate Curve
        wake = entry.options.get(CONF_WAKE_TIME, DEFAULT_WAKE_TIME)
        midday = entry.options.get(CONF_MIDDAY_TIME, DEFAULT_MIDDAY_TIME)
        sleep = entry.options.get(CONF_SLEEP_TIME, DEFAULT_SLEEP_TIME)
        
        self.hcl_calc.generate_curve(wake, midday, sleep)
        
        # Re-resolve targets immediately if the switch is on
        if self._is_on:
            await self._re_evaluate_targets_and_listeners()
            await self._update_hcl() # Trigger immediate update with new curve
        self.async_write_ha_state() # Ensure UI updates if needed

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
            name="HCL Lighting",
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
                timedelta(seconds=UPDATE_INTERVAL_SECONDS)
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
                # 1. Calculate Target Values
                # Dynamic Config
                min_b = self._entry.options.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS)
                max_b = self._entry.options.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS)
                
                brightness, kelvin = self.hcl_calc.get_hcl_values(dt_util.now(), min_b, max_b)
                
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
                
                # 3. Check for Re-engagements (Expired Overrides)
                expired_overrides = self.override_manager.get_pending_reengagements()
                for eid in expired_overrides:
                    if eid in all_lights:
                        await self.controller.reengage_light(
                            eid, self._calculated_brightness, self._calculated_kelvin
                        )

                # 4. Filter Active Lights (Not Overridden)
                active_lights = []
                for eid in all_lights:
                    state = self.hass.states.get(eid)
                    # Only control lights that are currently ON
                    if state and state.state == STATE_ON and not self.override_manager.is_overridden(eid):
                        active_lights.append(eid)
                
                # 5. Apply Batch
                if active_lights:
                    await self.controller.apply_batch(
                        active_lights, 
                        self._calculated_brightness, 
                        self._calculated_kelvin,
                        transition=HCL_TRANSITION_SECONDS 
                    )
            except Exception:
                 _LOGGER.exception("Error in HCL update loop")

    @callback
    def _handle_light_state_change(self, event: Event) -> None:
        """Handle state changes of monitored lights."""
        try:
            if not self._is_on:
                return
            
            entity_id = event.data.get("entity_id")
            old_state = event.data.get("old_state")
            new_state = event.data.get("new_state")

            if not entity_id or not new_state:
                return

            # 1. Fast Path (Turn On Event)
            if old_state and old_state.state != STATE_ON and new_state.state == STATE_ON:
                 # Just turned on.
                 if not self.override_manager.is_overridden(entity_id):
                     # RECALCULATE FRESH VALUES IMMEDIATELY
                     min_b = self._entry.options.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS)
                     max_b = self._entry.options.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS)
                     
                     # Use local time for calculation
                     now = dt_util.now()
                     fresh_b, fresh_k = self.hcl_calc.get_hcl_values(now, min_b, max_b)
                     
                     # Update cache while we are at it
                     self._calculated_brightness = fresh_b
                     self._calculated_kelvin = fresh_k

                     # Synchronous Update to Override Manager (Fix Race Condition)
                     self.override_manager.set_last_set_values(entity_id, fresh_b, fresh_k)
                     
                     # Set ignore window SYNCHRONOUSLY before task runs to prevent self-detection
                     self.override_manager.set_ignore_window(entity_id, 2.0)

                     self.hass.async_create_task(
                         self.controller.apply_fast(
                             entity_id, 
                             fresh_b, 
                             fresh_k,
                             state_obj=new_state
                         )
                     )
                     # IMPORTANT: Return here to avoid detecting this initial state as an override
                     return

            # 2. Check for Manual Override
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
