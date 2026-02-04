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
    DEFAULT_SLEEP_TIME,
    SERVICE_UPDATE_CURVE,
    SERVICE_UPDATE_CURVE,
    CONF_CURVE_CONFIG,
    IGNORE_WINDOW_SECONDS
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
    
    async_add_entities([switch])

    # Service is now registered globally in __init__.py

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

        # Subscribe to global updates (from service)
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
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

    # async_options_updated is handled by reload in __init__.py

    @callback
    def _handle_global_update(self):
        """Handle global update signal (e.g. from Preview/Apply)."""
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
                # 1. Calculate Target Values (Delegate to Controller Priority Stack)
                brightness, kelvin = self.controller.calculate_target_values(dt_util.now())
                
                # Check for "Sleep Mode / Off" or "Guest Mode / Freeze"
                if brightness is None and kelvin is None:
                    # GUEST MODE: Freeze/No-Op
                    # We still define brightness/kelvin as None for the state attributes below?
                    # Or just return?
                    # If we return, we don't prune cache or re-engage.
                    # Pruning is safe. Re-engage... maybe we shouldn't re-engage in Guest mode.
                    # Let's update state to reflect "Guest" or "Hold"?
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

            # 1. Fast Path (Turn On Event)
            if old_state and old_state.state != STATE_ON and new_state.state == STATE_ON:
                 # Just turned on.
                 if not self.override_manager.is_overridden(entity_id):
                     # RECALCULATE FRESH VALUES IMMEDIATELY via Controller
                     fresh_b, fresh_k = self.controller.calculate_target_values(dt_util.now())
                     
                     if fresh_b is None: # Guest mode active
                         return 
                         
                     if fresh_b == 0: # Sleep mode
                         # Don't turn on if sleep mode
                         return
                     
                     # Update cache while we are at it
                     self._calculated_brightness = fresh_b
                     self._calculated_kelvin = fresh_k

                     # Synchronous Update to Override Manager (Fix Race Condition)
                     self.override_manager.set_last_set_values(entity_id, fresh_b, fresh_k)
                     
                     # Set ignore window SYNCHRONOUSLY before task runs to prevent self-detection
                     self.override_manager.set_ignore_window(entity_id, IGNORE_WINDOW_SECONDS)

                     # Await immediately to block handling of subsequent events until command is sent
                     await self.controller.apply_fast(
                         entity_id, 
                         fresh_b, 
                         fresh_k,
                         state_obj=new_state
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
