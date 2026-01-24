"""Switch platform for HCL Lighting."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util
from datetime import timedelta
from homeassistant.core import callback, Event
from homeassistant.helpers.event import async_track_time_interval, async_track_state_change_event
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.const import STATE_ON, ATTR_ENTITY_ID

from .const import (
    DOMAIN, 
    CONF_TARGET, 
    HCL_TRANSITION_SECONDS, 
    UPDATE_INTERVAL_MINUTES,
    BRIGHTNESS_THRESHOLD,
    KELVIN_THRESHOLD,
    MINUTES_PER_DAY,
    CONF_SMART_TRANSITION,
    CONF_MIN_BRIGHTNESS,
    CONF_MAX_BRIGHTNESS,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_MAX_BRIGHTNESS,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the HCL Lighting switch."""
    async_add_entities([HCLSwitch(entry)], True)


class HCLSwitch(SwitchEntity, RestoreEntity):
    """Representation of a HCL Lighting Switch."""

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the switch."""
        self._entry = entry
        self._attr_has_entity_name = True
        self._attr_translation_key = "hcl_switch"
        self._attr_unique_id = f"{entry.entry_id}_switch"
        self._is_on = False
        self._calculated_brightness = 100
        self._calculated_color_temp = 2700
        self._last_applied_values = None
        self._watched_entities = set()
        self._listeners_remove = None

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        
        if last_state and last_state.state not in ("unknown", "unavailable"):
            _LOGGER.debug("Restoring state: %s", last_state.state)
            self._is_on = last_state.state == STATE_ON
        else:
            _LOGGER.debug("Found previous state: %s. Defaulting to OFF.", 
                        last_state.state if last_state else "None")
            self._is_on = False
        
        # Ensure state is written to HA
        self.async_write_ha_state()

        # Setup periodic update
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_update_callback, timedelta(minutes=UPDATE_INTERVAL_MINUTES)
            )
        )
        
        # Trigger immediate update to initialize listeners and calculated values
        await self.async_update()

    async def _async_update_callback(self, now) -> None:
        """Callback for periodic update."""
        await self.async_update()

    @property
    def device_info(self) -> DeviceInfo:
        """Return information about the device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="HCL Lighting Controller",
            manufacturer="Custom",
            model="HCL Controller",
            sw_version="0.1.0",
        )

    @property
    def should_poll(self) -> bool:
        """Disable default polling, as we use a custom timer."""
        return False

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return {
            "calculated_brightness": self._calculated_brightness,
            "calculated_color_temp": self._calculated_color_temp,
            "target_entities": self._entry.options.get(CONF_TARGET, self._entry.data.get(CONF_TARGET)),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        self._is_on = True
        self.async_write_ha_state()
        await self.async_update()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        self._is_on = False
        
        # Clean up listeners
        if self._listeners_remove:
            self._listeners_remove()
            self._listeners_remove = None
        self._watched_entities = set()
        
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update the switch state and calculated values."""
        now = dt_util.now()
        
        # 1. Calculate HCL values first (always needed)
        old_brightness = self._calculated_brightness
        old_color_temp = self._calculated_color_temp
        
        self._calculated_brightness, self._calculated_color_temp = self._calculate_hcl_values(now)
        
        # 2. State update if values changed
        if (old_brightness != self._calculated_brightness or 
            old_color_temp != self._calculated_color_temp):
            if self.entity_id:
                self.async_write_ha_state()

        if not self._is_on:
            return

        target_config = self._entry.options.get(CONF_TARGET, self._entry.data.get(CONF_TARGET))
        if not target_config:
            _LOGGER.warning("No target config found")
            return

        # 3. Expand targets
        try:
            entity_ids = self._resolve_targets(target_config)
        except Exception as err:
            _LOGGER.error("Failed to resolve targets: %s", err)
            return

        # 4. Update State Listeners (ALWAYS, even if lights are off)
        # If the set of potential targets changed, update the listener
        if entity_ids != self._watched_entities:
            self._watched_entities = entity_ids
            if self._listeners_remove:
                self._listeners_remove()
                self._listeners_remove = None
            
            if entity_ids:
                # Filter to track only lights to reduce noise
                track_ids = [eid for eid in entity_ids if eid.startswith("light.")]
                if track_ids:
                    self._listeners_remove = async_track_state_change_event(
                        self.hass, track_ids, self._handle_light_state_change
                    )

        # 5. Filter for active lights
        target_lights = [
            eid for eid in entity_ids
            if eid.startswith("light.")
            and (state := self.hass.states.get(eid))
            and state.state == STATE_ON
        ]

        if not target_lights:
            _LOGGER.debug("No active lights to update")
            return

        # 6. Check Deltas
        if self._last_applied_values is not None:
            last_b, last_k = self._last_applied_values
            delta_b = abs(self._calculated_brightness - last_b)
            delta_k = abs(self._calculated_color_temp - last_k)
            
            if delta_b < BRIGHTNESS_THRESHOLD and delta_k < KELVIN_THRESHOLD:
                _LOGGER.debug(
                    "Skipping update, delta below threshold (B: %d%%, K: %d)", 
                    delta_b, delta_k
                )
                return

        # 7. Apply to lights
        await self._apply_hcl_to_lights(target_lights, self._calculated_brightness, self._calculated_color_temp)

    async def _apply_hcl_to_lights(self, lights: list[str], brightness: int, kelvin: int, transition: float | None = None):
        """Apply HCL settings to a list of lights, respecting capabilities."""
        if not lights or not self._is_on:
            return
            
        # Local import to avoid blocking I/O warning at module level
        from homeassistant.components.light import ATTR_SUPPORTED_COLOR_MODES, ColorMode
        from homeassistant.util.color import (
            color_temperature_to_rgb,
            color_RGB_to_xy
        )

        # Default transition if not specified (Standard periodic update = slow fade)
        if transition is None:
            transition = HCL_TRANSITION_SECONDS

        lights_ct = []
        lights_dim = []
        lights_xy_sim = [] # For lights that need color simulation for low kelvin

        for entity_id in lights:
            state = self.hass.states.get(entity_id)
            if not state:
                continue
            
            supported_modes = state.attributes.get(ATTR_SUPPORTED_COLOR_MODES) or []
            min_kelvin = state.attributes.get("min_color_temp_kelvin")
            
            # Check for Warm White Simulation requirement
            # If we want a warmer temp than the light physically supports, and it supports generic color
            supports_color = any(mode in supported_modes for mode in (ColorMode.XY, ColorMode.HS, ColorMode.RGB))
            
            if (min_kelvin is not None and kelvin < min_kelvin and supports_color):
                 lights_xy_sim.append(entity_id)
            
            # Standard HCL Logic
            elif ColorMode.COLOR_TEMP in supported_modes:
                 lights_ct.append(entity_id)
            elif ColorMode.BRIGHTNESS in supported_modes:
                 lights_dim.append(entity_id)
            elif supported_modes and ColorMode.ONOFF not in supported_modes: 
                 lights_dim.append(entity_id)
            else:
                 pass

        # 1. Apply Extended Warm White (XY Simulation)
        if lights_xy_sim:
            smart_transition = self._entry.options.get(CONF_SMART_TRANSITION, False)
            
            try:
                # Convert target Kelvin to RGB to XY using HA util
                rgb = color_temperature_to_rgb(kelvin)
                x, y = color_RGB_to_xy(*rgb)
                
                # If explicit instant transition is requested (manually turned on), override smart transition
                if transition == 0:
                     await self.hass.services.async_call(
                        "light", "turn_on",
                        {
                            "entity_id": lights_xy_sim, 
                            "brightness_pct": brightness, 
                            "xy_color": (x, y),
                            "transition": 0
                        },
                        blocking=True,
                    )
                     _LOGGER.debug("Applied Instant HCL (XY Sim) to: %s", lights_xy_sim)
                
                elif not smart_transition:
                    # Standard Fast Bulk Update
                    await self.hass.services.async_call(
                        "light",
                        "turn_on",
                        {
                            "entity_id": lights_xy_sim,
                            "brightness_pct": brightness,
                            "xy_color": (x, y),
                            "transition": transition
                        },
                        blocking=True,
                    )
                    _LOGGER.debug("Applied HCL (XY Sim for %dK) to: %s", kelvin, lights_xy_sim)
                else:
                    # Smart Compatibility Mode (Split Calls) for XY
                    # Use provided transition for the "Slow" part
                    _LOGGER.debug("Smart Transition (XY) active for: %s", lights_xy_sim)
                    
                    for entity_id in lights_xy_sim:
                        try:
                            state = self.hass.states.get(entity_id)
                            curr_bri = state.attributes.get("brightness", 0)
                            curr_xy = state.attributes.get("xy_color", (x, y)) # Default to no change if missing
                            
                            target_bri_byte = int(brightness * 255 / 100)
                            
                            # Deltas
                            delta_b = abs(curr_bri - target_bri_byte) / 255.0
                            
                            # XY Distance (Euclidean)
                            curr_x, curr_y = curr_xy
                            delta_xy = ((curr_x - x)**2 + (curr_y - y)**2)**0.5
                            # Normalize XY delta: Max plausible distance in HCL range is ~0.2.
                            # So we scale it up to be comparable with brightness (0-1).
                            delta_c = delta_xy * 5.0 
                            
                            if delta_c > delta_b:
                                # Color Dominant -> Brightness Instant, Color Fade
                                await self.hass.services.async_call(
                                    "light", "turn_on",
                                    {"entity_id": entity_id, "brightness_pct": brightness, "transition": 0},
                                    blocking=True
                                )
                                await self.hass.services.async_call(
                                    "light", "turn_on",
                                    {"entity_id": entity_id, "xy_color": (x, y), "transition": transition},
                                    blocking=True
                                )
                            else:
                                # Brightness Dominant -> Color Instant, Brightness Fade
                                await self.hass.services.async_call(
                                    "light", "turn_on",
                                    {"entity_id": entity_id, "xy_color": (x, y), "transition": 0},
                                    blocking=True
                                )
                                await self.hass.services.async_call(
                                    "light", "turn_on",
                                    {"entity_id": entity_id, "brightness_pct": brightness, "transition": transition},
                                    blocking=True
                                )
                                
                        except Exception as err:
                             _LOGGER.error("Failed smart transition (XY) for %s: %s", entity_id, err)

            except Exception as err:
                 _LOGGER.error("Failed to apply XY Sim to %s: %s", lights_xy_sim, err)

        # 2. Apply Standard Color Temp + Brightness
        if lights_ct:
            smart_transition = self._entry.options.get(CONF_SMART_TRANSITION, False)
            
            # Explicit instant transition overrides smart logic
            if transition == 0:
                 try:
                    await self.hass.services.async_call(
                        "light", "turn_on",
                        {
                            "entity_id": lights_ct,
                            "brightness_pct": brightness, 
                            "color_temp_kelvin": kelvin,
                            "transition": 0
                        },
                        blocking=True,
                    )
                    _LOGGER.debug("Applied Instant HCL (CT) to: %s", lights_ct)
                 except Exception as err:
                     _LOGGER.error("Failed instant CT update: %s", err)

            elif not smart_transition:
                # Standard Fast Bulk Update
                try:
                    await self.hass.services.async_call(
                        "light",
                        "turn_on",
                        {
                            "entity_id": lights_ct,
                            "brightness_pct": brightness,
                            "color_temp_kelvin": kelvin,
                            "transition": transition
                        },
                        blocking=True,
                    )
                    _LOGGER.debug("Applied HCL (CT+Bright) to: %s", lights_ct)
                except Exception as err:
                    _LOGGER.error("Failed to apply CT to %s: %s", lights_ct, err)
            else:
                # Smart Compatibility Mode (Split Calls)
                # Iterates individual lights to calculate deltas
                _LOGGER.debug("Smart Transition Mode active for: %s", lights_ct)
                
                for entity_id in lights_ct:
                    try:
                        state = self.hass.states.get(entity_id)
                        curr_bri = state.attributes.get("brightness", 0) # 0-255
                        curr_kelvin = state.attributes.get("color_temp_kelvin", 2700)
                        
                        target_bri_byte = int(brightness * 255 / 100)
                        
                        delta_b = abs(curr_bri - target_bri_byte) / 255.0
                        delta_k = abs(curr_kelvin - kelvin) / 4500.0
                        
                        # Group A: Color Change is dominant
                        if delta_k > delta_b:
                            # 1. Set Brightness (Instant)
                            await self.hass.services.async_call(
                                "light", "turn_on",
                                {"entity_id": entity_id, "brightness_pct": brightness, "transition": 0},
                                blocking=True
                            )
                            # 2. Set Kelvin (Transition)
                            await self.hass.services.async_call(
                                "light", "turn_on",
                                {"entity_id": entity_id, "color_temp_kelvin": kelvin, "transition": transition},
                                blocking=True
                            )
                        # Group B: Brightness Change is dominant (or equal)
                        else:
                             # 1. Set Kelvin (Instant)
                            await self.hass.services.async_call(
                                "light", "turn_on",
                                {"entity_id": entity_id, "color_temp_kelvin": kelvin, "transition": 0},
                                blocking=True
                            )
                            # 2. Set Brightness (Transition)
                            await self.hass.services.async_call(
                                "light", "turn_on",
                                {"entity_id": entity_id, "brightness_pct": brightness, "transition": transition},
                                blocking=True
                            )
                    except Exception as err:
                         _LOGGER.error("Failed smart transition for %s: %s", entity_id, err)

        # 3. Apply Brightness Only
        if lights_dim:
            try:
                await self.hass.services.async_call(
                    "light",
                    "turn_on",
                    {
                        "entity_id": lights_dim,
                        "brightness_pct": brightness,
                        "transition": transition
                    },
                    blocking=True,
                )
                _LOGGER.debug("Applied HCL (Bright Only) to: %s", lights_dim)
            except Exception as err:
                 _LOGGER.error("Failed to apply Brightness to %s: %s", lights_dim, err)
        
        # Update last applied values (we assume success if we tried)
        self._last_applied_values = (brightness, kelvin)

    @callback
    def _handle_light_state_change(self, event: Event):
        """Handle state changes of monitored lights."""
        entity_id = event.data.get("entity_id")
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        
        if not self._is_on:
            return

        if not new_state or new_state.state != STATE_ON:
            return
            
        # Only trigger if it turned ON (from off/unavailable/unknown)
        if old_state and old_state.state == STATE_ON:
            return

        _LOGGER.debug("Monitored light %s turned ON. Applying HCL immediately.", entity_id)
        
        # Apply current calculated values immediately WITH ZERO TRANSITION
        self.hass.async_create_task(
            self._apply_hcl_to_lights(
                [entity_id], 
                self._calculated_brightness, 
                self._calculated_color_temp,
                transition=0 # Instant update to prevent color flash
            )
        )


    def _resolve_targets(self, target_config: dict[str, Any]) -> set[str]:
        """Resolve target config to a set of entity IDs manually."""
        entity_ids = set()
        er_registry = er.async_get(self.hass)
        dr_registry = dr.async_get(self.hass)
        
        # 1. Direct Entities
        if "entity_id" in target_config:
            ents = target_config["entity_id"]
            if isinstance(ents, str):
                ents = [ents]
            entity_ids.update(ents)
            
        # 2. Devices
        if "device_id" in target_config:
            devices = target_config["device_id"]
            if isinstance(devices, str):
                devices = [devices]
            for device_id in devices:
                for entry in er.async_entries_for_device(er_registry, device_id):
                     if entry.domain == "light":
                        entity_ids.add(entry.entity_id)

        # 3. Areas
        if "area_id" in target_config:
            areas = target_config["area_id"]
            if isinstance(areas, str):
                areas = [areas]
            for area_id in areas:
                # a) Entities directly in area
                for entry in er.async_entries_for_area(er_registry, area_id):
                    if entry.domain == "light":
                        entity_ids.add(entry.entity_id)
                
                # b) Devices in area (and their entities)
                for device in dr.async_entries_for_area(dr_registry, area_id):
                    for entry in er.async_entries_for_device(er_registry, device.id):
                        if entry.domain == "light":
                            entity_ids.add(entry.entity_id)
        
        # Flatten groups to ensures we check capabilities of individual lights
        # instead of the group wrapper.
        final_entities = set()
        to_process = list(entity_ids)
        processed = set()

        while to_process:
            eid = to_process.pop(0)
            if eid in processed:
                continue
            processed.add(eid)

            state = self.hass.states.get(eid)
            if not state:
                # If state is missing, we can't check for group-ness, 
                # but we shouldn't discard it if it was explicitly requested?
                # Best effort: add it, maybe it comes alive later.
                final_entities.add(eid)
                continue

            # Check if it looks like a group.
            # Check if it looks like a group (Standard HA or Hue).
            # We explicitly check attributes for member lists.
            group_members = state.attributes.get(ATTR_ENTITY_ID)

            if group_members:
                 # Ensure it is a list/tuple/set to avoid iteration errors
                 if not isinstance(group_members, (list, tuple, set)):
                      _LOGGER.warning("Entity %s has entity_id attribute but unexpected type: %s", eid, type(group_members))
                 else:
                     # It is a group, add members to process queue
                     # _LOGGER.debug("Expanding group %s into members: %s", eid, group_members)
                     to_process.extend(group_members)
                     continue # Don't add the group itself
            
            # Special Handling: Hue Groups sometimes initialize without 'entity_id' at startup
            # If we treat them as normal lights, we accidentally control the whole group.
            # We check multiple indicators for a "Group" that isn't ready yet.
            elif (
                state.attributes.get("is_hue_group") 
                or state.attributes.get("lights") 
                or state.attributes.get("hue_type")
            ):
                _LOGGER.warning(
                    "Entity %s appears to be a Group (Hue/Zigbee) but has no 'entity_id' members yet. "
                    "Skipping to avoid accidental group control (Startup race conditions). Attributes: %s", 
                    eid, list(state.attributes.keys())
                )
                continue

            # Standard Path
            else:
                 # Not a group (or a customized ZHA group without members exposed), keep it
                 final_entities.add(eid)
        
        return final_entities

    def _calculate_hcl_values(self, now) -> tuple[int, int]:
        """Calculate Brightness and Color Temp using Cubic Hermite Spline."""
        # Time -> (Kelvin, Brightness %)
        # Using DIN SPEC 67600 inspired points
        # NOTE: List contains NO duplicate 24:00 point. Wrap-around is handled logically.
        points = [
            (0, 2200, 10),           # 00:00
            (7 * 60, 2700, 30),      # 07:00
            (9 * 60, 4500, 50),      # 09:00
            (9 * 60 + 30, 5500, 75), # 09:30
            (10 * 60, 6500, 100),    # 10:00
            (12 * 60, 6500, 100),    # 12:00
            (12 * 60 + 30, 4000, 50),# 12:30 (Regeneration)
            (13 * 60, 4000, 50),     # 13:00
            (13 * 60 + 30, 6000, 75),# 13:30 (Re-Activation)
            (14 * 60, 6000, 75),     # 14:00
            (16 * 60, 4000, 50),     # 16:00
            (18 * 60, 2700, 30),     # 18:00
            (22 * 60, 2200, 10),     # 22:00
        ]

        current_minutes = now.hour * 60 + now.minute
        
        # 1. Find segment
        # Default to last segment (wrapping to start)
        idx = len(points) - 1
        
        # Check normal segments
        for i in range(len(points) - 1):
            if points[i][0] <= current_minutes < points[i+1][0]:
                idx = i
                break
        
        # 2. Extract Data for Segment [idx, idx+1]
        p0 = points[idx]
        p1 = points[(idx + 1) % len(points)]
        
        t0, k0, b0 = p0
        t1, k1, b1 = p1
        
        # Handle time wrapping for integration interval
        dt_interval = t1 - t0
        if dt_interval < 0:
            dt_interval += MINUTES_PER_DAY
            
        # 3. Calculate Normalized Time t (0..1)
        # Handle current_minutes crossing midnight relative to t0
        time_diff = current_minutes - t0
        if time_diff < 0:
            time_diff += MINUTES_PER_DAY
            
        t = time_diff / dt_interval

        # 4. Tangent Calculation (Slope Averaging)
        def get_slope(i1, i2):
            """Calculate slope with wraparound handling."""
            p1_idx = i1 % len(points)
            p2_idx = i2 % len(points)
            
            p_start = points[p1_idx]
            p_end = points[p2_idx]
            
            ts, ks, bs = p_start
            te, ke, be = p_end
            
            d_time = te - ts
            
            # If we wrapped around (went backwards in time), add 24h
            if p2_idx <= p1_idx and i2 != i1:
                 d_time += MINUTES_PER_DAY
            
            if d_time <= 0:
                return 0.0, 0.0
                
            mk = (ke - ks) / d_time
            mb = (be - bs) / d_time
            return mk, mb

        # Tangents for start (idx) and end (idx+1)
        s_in_k, s_in_b = get_slope(idx - 1, idx)
        s_out_k, s_out_b = get_slope(idx, idx + 1)
        
        # Tangent at p0 (m0)
        m0_k = (s_in_k + s_out_k) / 2
        m0_b = (s_in_b + s_out_b) / 2
        
        # Tangent at p1 (m1) -> need slope for (idx+1) -> (idx+2)
        s_next_k, s_next_b = get_slope(idx + 1, idx + 2)
        m1_k = (s_out_k + s_next_k) / 2
        m1_b = (s_out_b + s_next_b) / 2

        # 5. Hermite Interpolation
        t2 = t * t
        t3 = t2 * t

        h00 = 2*t3 - 3*t2 + 1
        h10 = t3 - 2*t2 + t
        h01 = -2*t3 + 3*t2
        h11 = t3 - t2
        
        kelvin = h00*k0 + h10*dt_interval*m0_k + h01*k1 + h11*dt_interval*m1_k
        brightness = h00*b0 + h10*dt_interval*m0_b + h01*b1 + h11*dt_interval*m1_b
        
        # Scale Brightness to User Limits
        min_b = self._entry.options.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS)
        max_b = self._entry.options.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS)
        
        # User Feedback: "User Min" should correspond to the "Lowest HCL Value" (Night = 10%),
        # not the theoretical 0%. Mapping [10, 100] -> [UserMin, UserMax].
        INTERNAL_MIN_HCL = 10.0
        INTERNAL_RANGE = 100.0 - INTERNAL_MIN_HCL
        
        # Normalize input (brightness from spline 10-100) to 0-1 range relative to effective curve
        normalized_b = (brightness - INTERNAL_MIN_HCL) / INTERNAL_RANGE
        
        # Clamp normalized to 0-1 (in case spline dipped slightly below 10)
        normalized_b = max(0.0, min(1.0, normalized_b))
        
        # Scale to user range
        scaled_b = min_b + normalized_b * (max_b - min_b)
        
        brightness = scaled_b

        # Clamp values to valid ranges
        brightness = max(1, min(100, int(brightness)))
        kelvin = max(2000, min(6500, int(kelvin))) # Safe Human Centric Limits (2000K-6500K)
        
        return brightness, kelvin

