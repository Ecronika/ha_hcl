"""Controller for interacting with Light entities."""
from __future__ import annotations

import logging
import asyncio
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.components.light import ATTR_SUPPORTED_COLOR_MODES, ColorMode
from homeassistant.helpers import entity_registry as er, device_registry as dr
from homeassistant.util.color import color_temperature_to_rgb, color_RGB_to_xy
from homeassistant.const import ATTR_ENTITY_ID

from ..const import (
    CONF_SMART_TRANSITION,
    REENGAGE_INTERVAL_SECONDS,
    REENGAGE_STEPS,
    BRIGHTNESS_THRESHOLD,
    KELVIN_THRESHOLD,
    XY_COLOR_SENSITIVITY,
    KELVIN_RANGE,
    CAPABILITY_CACHE_VERSION
)

from .override_manager import OverrideManager

from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    STATE_OFF,
    STATE_ON,
    ATTR_ENTITY_ID
)

_LOGGER = logging.getLogger(__name__)

class HCLLightController:
    """Controller for applying HCL settings to lights."""

    def __init__(self, hass: HomeAssistant, override_manager: OverrideManager, config_entry):
        self.hass = hass
        self.override_manager = override_manager
        self.config_entry = config_entry
        self._capability_cache = {}
        self._cache_version = CAPABILITY_CACHE_VERSION

    async def apply_batch(
        self, 
        lights: list[str], 
        brightness: int, 
        kelvin: int, 
        transition: float | None = None,
        fast_mode: bool = False
    ):
        """Apply settings to a batch of lights (Parallel Execution)."""
        if not lights:
            return

        # 1. Update Tracking (Immediate to prevent Race Conditions)
        # Delegate to OverrideManager
        if transition is None:
            # Default transition not defined here? Passed from switch.py usually.
            # If None, assume 0 or handle upstream.
            transition_val = 0
        else:
            transition_val = transition

        for eid in lights:
             self.override_manager.set_last_set_values(eid, brightness, kelvin)
             self.override_manager.set_ignore_window(eid, transition_val)

        # 2. Filter & Grouping
        lights_ct = []
        lights_dim = []
        lights_xy_sim = []

        # -- Capability Resolution & Threshold Check --
        for entity_id in lights:
            # Check Thresholds to avoid redundant traffic
            if not self._needs_update(entity_id, brightness, kelvin):
                continue

            cap_type = self._get_capability(entity_id, kelvin)
            if cap_type == "ct":
                lights_ct.append(entity_id)
            elif cap_type == "xy_sim":
                lights_xy_sim.append(entity_id)
            elif cap_type == "dim":
                lights_dim.append(entity_id)

        # 3. Task Collection for Parallel Execution
        tasks = []
        smart_transition = self.config_entry.options.get(CONF_SMART_TRANSITION, False)
        
        # Helper wrappers
        async def _smart_xy_single(entity_id, x, y):
             await self._apply_smart_xy_single(entity_id, x, y, brightness, transition_val)
        
        async def _smart_ct_single(entity_id):
             await self._apply_smart_ct_single(entity_id, kelvin, brightness, transition_val)

        # Group 1: XY Simulation
        if lights_xy_sim:
            rgb = color_temperature_to_rgb(kelvin)
            x, y = color_RGB_to_xy(*rgb)
            
            if transition_val == 0 or not smart_transition:
                # Bulk Update
                tasks.append(self.hass.services.async_call(
                    "light", "turn_on",
                    {"entity_id": lights_xy_sim, "brightness_pct": brightness, "xy_color": (x, y), "transition": transition_val},
                    blocking=True
                ))
            else:
                # Parallel Smart Transitions
                for eid in lights_xy_sim:
                    tasks.append(_smart_xy_single(eid, x, y))

        # Group 2: Standard CT
        if lights_ct:
            if transition_val == 0 or not smart_transition:
                # Bulk Update
                tasks.append(self.hass.services.async_call(
                    "light", "turn_on",
                    {"entity_id": lights_ct, "brightness_pct": brightness, "color_temp_kelvin": kelvin, "transition": transition_val},
                    blocking=True
                ))
            else:
                # Parallel Smart Transitions
                for eid in lights_ct:
                    tasks.append(_smart_ct_single(eid))

        # Group 3: Dimmer Only
        if lights_dim:
            tasks.append(self.hass.services.async_call(
                "light", "turn_on",
                {"entity_id": lights_dim, "brightness_pct": brightness, "transition": transition_val},
                blocking=True
            ))

        # 4. EXECUTE ALL IN PARALLEL
        if tasks:
            if fast_mode:
                # Fire-and-forget: schedule all tasks without waiting
                for t in tasks:
                    self.hass.async_create_task(t)
            else:

                # Standard Mode: Wait for all to finish, catch individual failures
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for res in results:
                    if isinstance(res, Exception):
                        _LOGGER.error("Error applying HCL to light batch: %s", res)

    async def apply_fast(self, entity_id: str, brightness: int, kelvin: int):
        """Ultra-fast HCL application for turn-on events."""
        _LOGGER.debug("Applying Fast-HCL to %s (B:%s%%, K:%sK)", entity_id, brightness, kelvin)
        
        state = self.hass.states.get(entity_id)
        if self._is_group(entity_id):
             _LOGGER.debug("Ignoring Fast-HCL for Group/Hue Group: %s", entity_id)
             return

        # Update Tracking
        self.override_manager.set_last_set_values(entity_id, brightness, kelvin)
        # NOTE: override_manager.set_ignore_window must be called by the caller 
        # (synchronously) before scheduling this task to avoid race conditions.

        cap_type = self._get_capability(entity_id, kelvin)
        
        coro = None
        
        if cap_type == "ct":
             coro = self.hass.services.async_call(
                "light", "turn_on",
                {"entity_id": entity_id, "brightness_pct": brightness, "color_temp_kelvin": kelvin, "transition": 0},
                blocking=True
            )
        elif cap_type == "xy_sim":
            rgb = color_temperature_to_rgb(kelvin)
            x, y = color_RGB_to_xy(*rgb)
            coro = self.hass.services.async_call(
                "light", "turn_on",
                {"entity_id": entity_id, "brightness_pct": brightness, "xy_color": (x, y), "transition": 0},
                blocking=True
            )
        elif cap_type == "dim":
            coro = self.hass.services.async_call(
                "light", "turn_on",
                {"entity_id": entity_id, "brightness_pct": brightness, "transition": 0},
                blocking=True
            )
            
        if coro:
             self.hass.async_create_task(coro)

    async def reengage_light(self, entity_id: str, target_brightness: int, target_kelvin: int):
        """Smoothly re-engage a light back to HCL values."""
        _LOGGER.debug("Re-engaging %s (Smooth Transition)", entity_id)
        
        # We perform a stepwise transition to avoid sudden jumps
        # This is a simplifed logic: Just one long transition is usually better supported by HA light 
        # than manual steps, BUT manual steps allow us to update the "last_set" tracking more accurately?
        # No, HA transition is fine, but we must set override last_set to TARGET.
        
        # Actually, let's use the explicit logic from before if we want steps, 
        # or simplified long transition. The original code did steps.
        # Let's use a nice single transition for simplicity and reliance on HA.
        # Wait, original code used steps because of the "Override Delta" check?
        # If we just fade, the override manager might think the user is changing it during fade?
        # We set ignore_window for the duration!
        
        duration = REENGAGE_STEPS * REENGAGE_INTERVAL_SECONDS
        
        await self.apply_batch(
            [entity_id], 
            target_brightness, 
            target_kelvin, 
            transition=duration,
            fast_mode=True # Don't block main loop
        )

    def _get_capability(self, entity_id: str, kelvin: int) -> str:
        """Determine capabilities of a light (Cached with Migration Safety)."""
        
        # 1. Check Cache + Version Migration
        if entity_id in self._capability_cache:
            cached = self._capability_cache[entity_id]
            
            # Version Mismatch = Invalidate (Migration from v0.2.0)
            cached_version = cached.get("version")
            if cached_version != self._cache_version:
                _LOGGER.debug(
                    "Cache invalidated for %s (v%s->v%s, forcing recalc)", 
                    entity_id, 
                    cached_version or "none", 
                    self._cache_version
                )
                del self._capability_cache[entity_id]
            else:
                # Valid Cache: Check Dynamic XY
                if (cached["type"] == "ct" and 
                    cached.get("min_kelvin") and 
                    kelvin < cached["min_kelvin"] and 
                    cached.get("supports_color")):
                    return "xy_sim"
                return cached["type"]

        # 2. Get Current State
        state = self.hass.states.get(entity_id)
        if not state:
            # Not loaded yet?
            return "onoff"
        
        if state.state is None:
             _LOGGER.warning("Entity %s has NULL state, treating as unavailable", entity_id)
             return "onoff"

        # 3. Safe State Check (NO CACHE)
        # Avoid caching if light is unavailable, unknown, or OFF (often missing attributes)
        if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, STATE_OFF):
            _LOGGER.debug(
                "Entity %s in unsafe state '%s' - calculating without cache", 
                entity_id, 
                state.state
            )
            # Calculate live but DON'T cache
            return self._calculate_capability_from_state(state)

        # 4. Attribute Validation (NO CACHE if invalid)
        supported_modes = state.attributes.get(ATTR_SUPPORTED_COLOR_MODES)
        
        # None or Empty List = Invalid (Warn if ON, Debug if others)
        if supported_modes is None or (isinstance(supported_modes, (list, tuple)) and len(supported_modes) == 0):
             if state.state == STATE_ON:
                  _LOGGER.warning("Entity %s is ON but has no 'supported_color_modes' - not caching", entity_id)
             else:
                  _LOGGER.debug("Entity %s has no 'supported_color_modes' - not caching", entity_id)
             return "onoff"

        # 5. Safe to Cache (State=ON + Valid Attributes)
        min_kelvin = state.attributes.get("min_color_temp_kelvin")
        supports_color = any(
            mode in supported_modes 
            for mode in (ColorMode.XY, ColorMode.HS, ColorMode.RGB)
        )

        # Calculate Capability
        if ColorMode.COLOR_TEMP in supported_modes:
            cap_type = "ct"
        elif supports_color:
            cap_type = "xy_sim"
        elif (ColorMode.BRIGHTNESS in supported_modes or 
              (supported_modes and ColorMode.ONOFF not in supported_modes)):
            cap_type = "dim"
        else:
            cap_type = "onoff"

        # Store in Cache with Version
        cap_data = {
            "type": cap_type,
            "min_kelvin": min_kelvin,
            "supports_color": supports_color,
            "version": self._cache_version  # MIGRATION TAG
        }
        self._capability_cache[entity_id] = cap_data

        _LOGGER.debug(
            "Capability cached for %s: %s (v%s, modes=%s)", 
            entity_id, 
            cap_type, 
            self._cache_version,
            supported_modes
        )

        # 6. Recursive Check for Dynamic XY
        return self._get_capability(entity_id, kelvin)

    def _calculate_capability_from_state(self, state) -> str:
        """Calculate capability without caching (for unsafe states)."""
        supported_modes = state.attributes.get(ATTR_SUPPORTED_COLOR_MODES) or []
        
        if not supported_modes:
            return "onoff"
        
        supports_color = any(
            mode in supported_modes 
            for mode in (ColorMode.XY, ColorMode.HS, ColorMode.RGB)
        )

        if ColorMode.COLOR_TEMP in supported_modes:
            return "ct"
        elif supports_color:
            return "xy_sim"
        elif (ColorMode.BRIGHTNESS in supported_modes or 
              (supported_modes and ColorMode.ONOFF not in supported_modes)):
            return "dim"
        
        return "onoff"

    def _needs_update(self, entity_id: str, target_b: int, target_k: int) -> bool:
        """Check if an update is needed based on thresholds."""
        state = self.hass.states.get(entity_id)
        if not state:
            return True

        curr_b = state.attributes.get("brightness")
        curr_k = state.attributes.get("color_temp_kelvin")
        
        # Safety Check: Ignore Groups (Hue Groups or HA Groups)
        # Groups shouldn't be in the list, but if they sneak in (e.g. startup race),
        # we strictly ignore them here to avoid "Double Control".
        if self._is_group(entity_id):
            return False

        # Check Brightness
        if curr_b is not None:
             curr_b_pct = int(curr_b * 100 / 255)
             delta_b = abs(curr_b_pct - target_b)
             if delta_b > BRIGHTNESS_THRESHOLD:
                 return True
        else:
            delta_b = "Unknown"
            # Unknown brightness, assume update needed
            return True
            
        # Check Kelvin (if supported)
        if curr_k is not None:
             delta_k = abs(curr_k - target_k)
             if delta_k > KELVIN_THRESHOLD:
                 return True
        elif self._get_capability(entity_id, target_k) in ("ct", "xy_sim"):
             # Color supported but current is None (e.g. RGB mode?), force update
             return True
        else:
            delta_k = "N/A"

        _LOGGER.debug(
            "Skipping update for %s: Change too small (Delta B=%s%%, K=%sK)", 
            entity_id, delta_b, delta_k
        )
        return False

    def resolve_targets(self, target_config: dict[str, Any]) -> set[str]:
        """Resolve target config to a set of entity IDs."""
        # Extracted directly from old switch.py
        entity_ids = set()
        er_registry = er.async_get(self.hass)
        dr_registry = dr.async_get(self.hass)
        
        # 1. Direct Entities
        if "entity_id" in target_config:
            ents = target_config["entity_id"]
            if isinstance(ents, str): ents = [ents]
            entity_ids.update(ents)
            
        # 2. Devices
        if "device_id" in target_config:
            devices = target_config["device_id"]
            if isinstance(devices, str): devices = [devices]
            for device_id in devices:
                for entry in er.async_entries_for_device(er_registry, device_id):
                     if entry.domain == "light":
                        entity_ids.add(entry.entity_id)

        # 3. Areas
        if "area_id" in target_config:
            areas = target_config["area_id"]
            if isinstance(areas, str): areas = [areas]
            for area_id in areas:
                for entry in er.async_entries_for_area(er_registry, area_id):
                    if entry.domain == "light":
                        entity_ids.add(entry.entity_id)
                for device in dr.async_entries_for_area(dr_registry, area_id):
                    for entry in er.async_entries_for_device(er_registry, device.id):
                        if entry.domain == "light":
                            entity_ids.add(entry.entity_id)
        
        # Expand Groups
        final_entities = set()
        to_process = list(entity_ids)
        processed = set()

        while to_process:
            eid = to_process.pop(0)
            if eid in processed: continue
            processed.add(eid)

            state = self.hass.states.get(eid)
            if not state:
                final_entities.add(eid)
                continue

            group_members = state.attributes.get(ATTR_ENTITY_ID)
            if group_members and isinstance(group_members, (list, tuple, set)):
                 to_process.extend(group_members)
            elif (state.attributes.get("is_hue_group") or state.attributes.get("lights") or state.attributes.get("hue_type")):
                continue # Skip raw Hue groups
            else:
                final_entities.add(eid)
                
        return final_entities

    async def _apply_smart_xy_single(self, entity_id, x, y, brightness, transition):
        try:
            state = self.hass.states.get(entity_id)
            if not state: return
            curr_bri = state.attributes.get("brightness") or 0
            curr_xy = state.attributes.get("xy_color") or (x, y)
            target_bri_byte = int(brightness * 255 / 100)
            delta_b = abs(curr_bri - target_bri_byte) / 255.0
            curr_x, curr_y = curr_xy
            delta_c = ((curr_x - x)**2 + (curr_y - y)**2)**0.5 * XY_COLOR_SENSITIVITY
            
            if delta_c > delta_b:
                await self.hass.services.async_call("light", "turn_on", {"entity_id": entity_id, "brightness_pct": brightness, "transition": 0}, blocking=True)
                await self.hass.services.async_call("light", "turn_on", {"entity_id": entity_id, "xy_color": (x, y), "transition": transition}, blocking=True)
            else:
                await self.hass.services.async_call("light", "turn_on", {"entity_id": entity_id, "xy_color": (x, y), "transition": 0}, blocking=True)
                await self.hass.services.async_call("light", "turn_on", {"entity_id": entity_id, "brightness_pct": brightness, "transition": transition}, blocking=True)
        except Exception as e:
            _LOGGER.error("Smart XY error %s: %s", entity_id, e)
            # Fallback
            try:
                await self.hass.services.async_call("light", "turn_on", {"entity_id": entity_id, "brightness_pct": brightness, "xy_color": (x, y), "transition": 0}, blocking=True)
            except Exception:
                pass

    async def _apply_smart_ct_single(self, entity_id, kelvin, brightness, transition):
        try:
            state = self.hass.states.get(entity_id)
            if not state: return
            curr_bri = state.attributes.get("brightness") or 0
            curr_kelvin = state.attributes.get("color_temp_kelvin") or 2700
            target_bri_byte = int(brightness * 255 / 100)
            delta_b = abs(curr_bri - target_bri_byte) / 255.0
            delta_k = abs(curr_kelvin - kelvin) / KELVIN_RANGE
            
            if delta_k > delta_b:
                await self.hass.services.async_call("light", "turn_on", {"entity_id": entity_id, "brightness_pct": brightness, "transition": 0}, blocking=True)
                await self.hass.services.async_call("light", "turn_on", {"entity_id": entity_id, "color_temp_kelvin": kelvin, "transition": transition}, blocking=True)
            else:
                await self.hass.services.async_call("light", "turn_on", {"entity_id": entity_id, "color_temp_kelvin": kelvin, "transition": 0}, blocking=True)
                await self.hass.services.async_call("light", "turn_on", {"entity_id": entity_id, "brightness_pct": brightness, "transition": transition}, blocking=True)
        except Exception as e:
            _LOGGER.error("Smart CT error %s: %s", entity_id, e)
            # Fallback
            try:
                await self.hass.services.async_call("light", "turn_on", {"entity_id": entity_id, "brightness_pct": brightness, "color_temp_kelvin": kelvin, "transition": 0}, blocking=True)
            except Exception:
                pass

    def _is_group(self, entity_id: str) -> bool:
        """Check if entity is a group."""
        state = self.hass.states.get(entity_id)
        if not state:
            return False
        return (state.attributes.get("is_hue_group") or 
                state.attributes.get("hue_type") or 
                isinstance(state.attributes.get(ATTR_ENTITY_ID), (list, tuple)))
