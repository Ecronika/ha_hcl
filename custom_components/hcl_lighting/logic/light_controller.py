"""Controller for interacting with Light entities."""
from __future__ import annotations

import logging
import asyncio
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.components.light import (
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_COLOR_TEMP_KELVIN,
    ColorMode
)
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

    def prune_cache(self, valid_entity_ids: set[str]) -> None:
        """Prune capability cache of invalid/removed entities."""
        to_remove = [eid for eid in self._capability_cache if eid not in valid_entity_ids]
        
        for eid in to_remove:
            del self._capability_cache[eid]
            
        if to_remove:
            _LOGGER.debug("Pruned %d stale entities from capability cache", len(to_remove))

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

        # 2. Filter & Grouping
        lights_ct = []
        lights_dim = []
        lights_xy_sim = []

        # -- Capability Resolution & Threshold Check --
        for entity_id in lights:
            # Check Thresholds to avoid redundant traffic
            if not self._needs_update(entity_id, brightness, kelvin):
                 continue
            
            # NOTE: Override Tracking has been moved inside the capability check blocks
            # below to ensure we only ignore-window lights that ACTUALLY get an update command.

            cap_type = self._get_capability(entity_id, kelvin)
            if cap_type == "ct":
                lights_ct.append(entity_id)
                self.override_manager.set_last_set_values(entity_id, brightness, kelvin)
                self.override_manager.set_ignore_window(entity_id, transition_val)
            elif cap_type == "xy_sim":
                lights_xy_sim.append(entity_id)
                self.override_manager.set_last_set_values(entity_id, brightness, kelvin)
                self.override_manager.set_ignore_window(entity_id, transition_val)
            elif cap_type == "dim":
                lights_dim.append(entity_id)
                self.override_manager.set_last_set_values(entity_id, brightness, kelvin)
                self.override_manager.set_ignore_window(entity_id, transition_val)

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
                for i, res in enumerate(results):
                    if isinstance(res, BaseException):
                        _LOGGER.error(
                            "Batch light update task %d/%d failed: %s", 
                            i + 1, len(results), res, 
                            exc_info=res
                        )

    async def apply_fast(self, entity_id: str, brightness: int, kelvin: int, state_obj=None):
        """Ultra-fast HCL application for turn-on events."""
        _LOGGER.debug("Applying Fast-HCL to %s (B:%s%%, K:%sK)", entity_id, brightness, kelvin)
        
        # Use passed state object or fallback to lookup (performance optimization)
        state = state_obj or self.hass.states.get(entity_id)
        
        if state is None:
            return

        if self._is_group(entity_id, state):
             _LOGGER.debug("Ignoring Fast-HCL for Group/Hue Group: %s", entity_id)
             return

        # Redundant tracking removed (handled in switch.py synchronously)
        
        cap_type = self._get_capability(entity_id, kelvin, state)
        
        service_data = {
            "entity_id": entity_id,
            "brightness_pct": brightness,
            "transition": 0
        }
        
        if cap_type == "ct":
             service_data["color_temp_kelvin"] = kelvin
        elif cap_type == "xy_sim":
            rgb = color_temperature_to_rgb(kelvin)
            x, y = color_RGB_to_xy(*rgb)
            service_data["xy_color"] = (x, y)
        elif cap_type == "dim":
            pass
        else:
            return # onoff or unknown

        # Execute immediately in current task context (no double-scheduling)
        await self.hass.services.async_call(
            "light", 
            "turn_on",
            service_data,
            blocking=True
        )

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

    def _get_capability(self, entity_id: str, kelvin: int, state_obj=None) -> str:
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
                    cached.get("max_kelvin") and
                    (kelvin < cached["min_kelvin"] or kelvin > cached["max_kelvin"]) and 
                    cached.get("supports_color")):
                    return "xy_sim"
                return cached["type"]

        # 2. Get Current State
        state = state_obj or self.hass.states.get(entity_id)
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
        # Type safety check
        if supported_modes and not isinstance(supported_modes, (list, tuple)):
             _LOGGER.warning("Entity %s has invalid supported_color_modes type: %s", entity_id, type(supported_modes))
             return "onoff"
        
        # None or Empty List = Invalid
        if not supported_modes:
             _LOGGER.debug(
                 "Entity %s is %s but has no 'supported_color_modes' - treating as onoff", 
                 entity_id, state.state
             )
             return "onoff"

        # 5. Safe to Cache (State=ON + Valid Attributes)
        min_kelvin = state.attributes.get("min_color_temp_kelvin")
        max_kelvin = state.attributes.get("max_color_temp_kelvin")
        supports_color = any(
            mode in supported_modes 
            for mode in (ColorMode.XY, ColorMode.HS, ColorMode.RGB)
        )

        # Calculate Capability
        cap_type = "onoff" # Default
        if ColorMode.COLOR_TEMP in supported_modes:
            cap_type = "ct"
        elif supports_color:
            cap_type = "xy_sim"
        elif (ColorMode.BRIGHTNESS in supported_modes or 
              (supported_modes and ColorMode.ONOFF not in supported_modes)):
            cap_type = "dim"
        
        # Handle CT lights with missing min/max kelvin or target kelvin out of range
        if cap_type == "ct":
            # If we have color_temp mode but no limits, assume standard range to avoid crash
            # This happens with some MQTT/Template lights
            if min_kelvin is None:
                min_kelvin = 2000
            if max_kelvin is None:
                max_kelvin = 6500
            
            # If target kelvin is outside the light's reported range, simulate with XY if possible
            if (kelvin < min_kelvin or kelvin > max_kelvin) and supports_color:
                cap_type = "xy_sim" # Simulate CT using XY if target is out of range

        # Store in Cache with Version
        cap_data = {
            "type": cap_type,
            "min_kelvin": min_kelvin,
            "max_kelvin": max_kelvin,
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

        # 6. Recursive Check for Dynamic XY (if it was originally CT but switched to XY_SIM)
        # This ensures the logic for out-of-range kelvin is applied immediately after caching
        if cap_type == "xy_sim" and cap_data["type"] == "ct": # If it was originally CT but we decided to simulate
            return self._get_capability(entity_id, kelvin) # Recalculate with the new kelvin range logic
        
        return cap_type

    def _calculate_capability_from_state(self, state) -> str:
        """Calculate capability without caching (for unsafe states)."""
        supported_modes = state.attributes.get(ATTR_SUPPORTED_COLOR_MODES)
        
        # Type safety: ensure iterable
        if supported_modes and not isinstance(supported_modes, (list, tuple)):
            # Invalid type (e.g. string) -> onoff
            return "onoff"

        supported_modes = supported_modes or []
        
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

        # Current State
        curr_b = state.attributes.get("brightness")
        # Use ROUND instead of INT truncation to prevent off-by-one ping-pong loops
        # e.g. 50% = 127.5 -> round(128) vs int(127).
        curr_b_pct = round(curr_b * 100 / 255) if curr_b is not None else None
        curr_k = state.attributes.get(ATTR_COLOR_TEMP_KELVIN)
        
        # Safety Check: Ignore Groups (Hue Groups or HA Groups)
        # Groups shouldn't be in the list, but if they sneak in (e.g. startup race),
        # we strictly ignore them here to avoid "Double Control".
        if self._is_group(entity_id):
            return False

        # Check Brightness
        delta_b = 0
        if curr_b is not None:
             curr_b_pct = int(curr_b * 100 / 255)
             delta_b = abs(curr_b_pct - target_b)
        else:
            # Unknown brightness, assume update needed
            return True
            
        # Check Kelvin (if supported)
        delta_k = 0
        if curr_k is not None:
             delta_k = abs(curr_k - target_k)
        elif self._get_capability(entity_id, target_k) in ("ct", "xy_sim"):
             # Color supported but current is None (e.g. RGB mode?), force update
             return True
        
        if delta_b <= BRIGHTNESS_THRESHOLD and (delta_k <= KELVIN_THRESHOLD if target_k else True):
             # Logs demoted to TRACE (level 5) to avoid spam
             _LOGGER.log(5, "Skipping update for %s: Change too small (Delta B=%s%%, K=%sK)", entity_id, delta_b, delta_k if target_k else "N/A")
             return False
        
        return True

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
            eid = to_process.pop() # Stack behavior (O(1)) instead of Queue (O(n))
            
            if eid in processed: continue
            processed.add(eid)

            state = self.hass.states.get(eid)
            if not state:
                if eid.startswith("light."):
                    final_entities.add(eid)
                continue

            group_members = state.attributes.get(ATTR_ENTITY_ID)
            if group_members and isinstance(group_members, (list, tuple, set)):
                 to_process.extend(group_members)
            elif (state.attributes.get("is_hue_group") or state.attributes.get("lights") or state.attributes.get("hue_type")):
                continue # Skip raw Hue groups
            else:
                if eid.startswith("light."):
                    final_entities.add(eid)
                
        return final_entities

    async def _apply_smart_xy_single(self, entity_id, x, y, brightness, transition):
        try:
            state = self.hass.states.get(entity_id)
            if not state: return
            curr_bri = state.attributes.get("brightness") or 0
            curr_xy = state.attributes.get("xy_color") or (x, y)
            target_bri_byte = int(round(float(brightness) * 255 / 100))
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
            target_bri_byte = int(round(float(brightness) * 255 / 100))
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

    def _is_group(self, entity_id: str, state_obj=None) -> bool:
        """Check if entity is a group."""
        state = state_obj or self.hass.states.get(entity_id)
        if not state:
            return False
        return (state.attributes.get("is_hue_group") or 
                state.attributes.get("hue_type") or 
                isinstance(state.attributes.get(ATTR_ENTITY_ID), (list, tuple)))
