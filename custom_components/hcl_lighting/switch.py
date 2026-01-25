"""Switch platform for HCL Lighting."""
from __future__ import annotations

import logging
from typing import Any
from datetime import timedelta

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.const import STATE_ON
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOMAIN, 
    CONF_TARGET, 
    UPDATE_INTERVAL_SECONDS,
    CONF_MIN_BRIGHTNESS,
    CONF_MAX_BRIGHTNESS,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_MAX_BRIGHTNESS,
    HCL_TRANSITION_SECONDS
)

from .logic.hcl_math import HCLCalculator
from .logic.override_manager import OverrideManager
from .logic.light_controller import HCLLightController

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the HCL Lighting switch."""
    async_add_entities([HCLSwitch(hass, entry)])


from homeassistant.helpers.restore_state import RestoreEntity

class HCLSwitch(SwitchEntity, RestoreEntity):
    """Representation of a HCL Lighting Switch."""

    _attr_has_entity_name = True
    _attr_translation_key = "hcl_switch"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the switch."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = entry.entry_id
        
        # State
        self._is_on = False
        self._calculated_brightness = 0
        self._calculated_kelvin = 2700
        self._timer_remove_callback = None
        self._state_listener_remove_callback = None
        self._resolved_targets = set()
        
        # Modules
        self.calculator = HCLCalculator()
        self.override_manager = OverrideManager()
        self.controller = HCLLightController(hass, self.override_manager, entry)

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        
        # Restore State
        if last_state := await self.async_get_last_state():
            if last_state.state == STATE_ON:
                self._is_on = True
                await self.async_turn_on()
        
        self._entry.async_on_unload(self._entry.add_update_listener(self._async_update_callback))

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        self._is_on = False # Prevent further updates
        if self._timer_remove_callback:
            self._timer_remove_callback()
            self._timer_remove_callback = None
            
        if self._state_listener_remove_callback:
            self._state_listener_remove_callback()
            self._state_listener_remove_callback = None

    async def _async_update_callback(self, hass, entry):
        """Callback for config enty updates."""
        # Re-initialize controller with new config options if needed
        self.controller.config_entry = entry
        # Invalidate target cache
        self._resolved_targets = self.controller.resolve_targets(self._entry.options.get(CONF_TARGET, {}))

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
        
        # Start Timer
        self._timer_remove_callback = async_track_time_interval(
            self.hass,
            self._update_hcl, # Main Loop
            timedelta(seconds=UPDATE_INTERVAL_SECONDS)
        )
        
        # Start State Listener (Fast Path + Override)
        # Note: We need to know WHICH entities to listen to.
        # Originally we listened to "all" target entities.
        # This requires resolving targets dynamically.
        # Ideally, we should update the listener when config changes, but for now:
        # Ideally, we should update the listener when config changes, but for now:
        self._resolved_targets = self.controller.resolve_targets(self._entry.options.get(CONF_TARGET, {}))
        
        if self._resolved_targets:
            self._state_listener_remove_callback = async_track_state_change_event(
                self.hass, list(self._resolved_targets), self._handle_light_state_change
            )

        # Immediate update
        await self._update_hcl()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        self._is_on = False
        
        if self._timer_remove_callback:
            self._timer_remove_callback()
            self._timer_remove_callback = None
            
        if self._state_listener_remove_callback:
            self._state_listener_remove_callback()
            self._state_listener_remove_callback = None

    async def _update_hcl(self, now=None) -> None:
        """Update the switch state and calculated values."""
        if not self._is_on:
            return
            
        if now is None:
            now = dt_util.now()
        else:
            now = dt_util.as_local(now)

        # 1. Calculate Target Values
        min_b = self._entry.options.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS)
        max_b = self._entry.options.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS)
        
        self._calculated_brightness, self._calculated_kelvin = self.calculator.get_hcl_values(
            now, min_b, max_b
        )
        _LOGGER.debug(
            "HCL Update Cycle: Target B=%s%%, K=%sK", 
            self._calculated_brightness, self._calculated_kelvin
        )
        self.async_write_ha_state()

        # 2. Resolve Targets (Cached)
        all_lights = self._resolved_targets
        
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

    @callback
    def _handle_light_state_change(self, event: Event) -> None:
        """Handle state changes of monitored lights."""
        if not self._is_on:
            return

        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        
        if not new_state:
            return

        # 1. Fast Path (Turn On Event)
        # Check this BEFORE override to handle "Restore Last State" correctly.
        # If a light turns on, we want to capture it immediately into HCL, 
        # ignoring whatever brightness it "remembered" from last time.
        if old_state and old_state.state != STATE_ON and new_state.state == STATE_ON:
             # Just turned on.
             # Only apply if not persistently overridden (though we usually reset on OFF)
             if not self.override_manager.is_overridden(entity_id):
                 # RECALCULATE FRESH VALUES IMMEDIATELY
                 # Stored self._calculated_brightness might be up to UPDATE_INTERVAL old.
                 min_b = self._entry.options.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS)
                 max_b = self._entry.options.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS)
                 now = dt_util.now()
                 fresh_b, fresh_k = self.calculator.get_hcl_values(now, min_b, max_b)
                 
                 # Update cache while we are at it
                 self._calculated_brightness = fresh_b
                 self._calculated_kelvin = fresh_k

                 # Synchronous Update to Override Manager (Fix Race Condition)
                 self.override_manager.set_last_set_values(entity_id, fresh_b, fresh_k)

                 self.hass.async_create_task(
                     self.controller.apply_fast(
                         entity_id, 
                         fresh_b, 
                         fresh_k
                     )
                 )
                 # IMPORTANT: Return here to avoid detecting this initial state as an override
                 return

        # 2. Check for Manual Override
        # This now only processes changes happening WHILE the light is already ON,
        # OR the Turn-Off event (to reset).
        is_override = self.override_manager.check_override(entity_id, new_state, None)
        
        if is_override:
            return
