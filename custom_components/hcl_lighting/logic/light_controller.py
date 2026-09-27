"""Controller for interacting with Light entities."""
from __future__ import annotations

import logging
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import time

from homeassistant.core import Context, HomeAssistant
from homeassistant.components.light import (
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_COLOR_TEMP_KELVIN,
    ColorMode
)
from homeassistant.util.color import (
    color_temperature_to_rgb,
    color_RGB_to_xy,
    color_xy_to_temperature,
)
from homeassistant.const import ATTR_ENTITY_ID

from ..const import (
    CONF_SMART_TRANSITION,
    REENGAGE_INTERVAL_SECONDS,
    REENGAGE_STEPS,
    BRIGHTNESS_THRESHOLD,
    KELVIN_THRESHOLD,
    XY_COLOR_SENSITIVITY,
    KELVIN_RANGE,
    CAPABILITY_CACHE_VERSION,
    MODE_AUTO,
    MODE_GUEST,
    MODE_SLEEP,
    SCENARIO_DEFAULTS,
    CONF_MIN_BRIGHTNESS,
    CONF_MAX_BRIGHTNESS,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_MAX_BRIGHTNESS,
    XY_COLOR_DISTANCE_THRESHOLD,
    CONFIGURABLE_SCENARIOS,
    LIMITABLE_SCENARIOS,
    CONF_SCENARIO_LIMITS,
    DEFAULT_SCENARIO_LIMITS,
    CONF_BRIGHTNESS_SCALING,
    DEFAULT_BRIGHTNESS_SCALING,
    scenario_option_keys,
)

from ..logic.hcl_math import HCLCalculator

from .override_manager import OverrideManager

from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    STATE_OFF,
    STATE_ON,
    ATTR_ENTITY_ID
)

_LOGGER = logging.getLogger(__name__)


def extract_referenced_entities(hass: HomeAssistant, target_config: dict[str, Any]):
    """Home Assistant's own resolution of a target (entities, devices, areas,
    floors, labels) for the running version.

    2026.1+: helpers.target with TargetSelection; 2025.8–2025.12: with
    TargetSelectorData; up to 2025.7: helpers.service with a service call.
    Groups are not expanded here (HCL expands light groups itself).
    """
    config = {
        key: target_config[key]
        for key in ("entity_id", "device_id", "area_id", "floor_id", "label_id")
        if target_config.get(key)
    }
    try:
        from homeassistant.helpers import target as ha_target
    except ImportError:
        ha_target = None
    if ha_target is not None and hasattr(ha_target, "async_extract_referenced_entity_ids"):
        selection = getattr(ha_target, "TargetSelection", None) or ha_target.TargetSelectorData
        return ha_target.async_extract_referenced_entity_ids(hass, selection(config), expand_group=False)
    from homeassistant.core import ServiceCall
    from homeassistant.helpers.service import async_extract_referenced_entity_ids

    return async_extract_referenced_entity_ids(
        hass, ServiceCall("light", "turn_on", config), expand_group=False
    )


@dataclass(slots=True)
class BatchResult:
    """Result of apply_batch.

    updated: lights whose command succeeded (fast mode: whose command was sent).
    failed: lights whose command raised an error, with the error.
    Lights without a command (already at the values) are in neither.
    """

    updated: list[str] = field(default_factory=list)
    failed: dict[str, BaseException] = field(default_factory=dict)

# Colour modes HCL drives through the XY simulation (Home Assistant converts
# xy_color to the light's own mode, including RGBW and RGBWW)
_COLOR_MODES = (ColorMode.XY, ColorMode.HS, ColorMode.RGB, ColorMode.RGBW, ColorMode.RGBWW)

class HCLLightController:
    """Controller for applying HCL settings to lights."""

    def __init__(self, hass: HomeAssistant, override_manager: OverrideManager, hcl_calc: HCLCalculator, config_entry):
        self.hass = hass
        self.override_manager = override_manager
        self.hcl_calc = hcl_calc
        self.config_entry = config_entry
        self._capability_cache = {}
        self._cache_version = CAPABILITY_CACHE_VERSION
        
        # State Machine
        self.active_mode = MODE_AUTO
        # Set when the scenario changed; the next update uses the scenario transition
        self._mode_change_pending = False

        # Adaptation switches (brightness / colour temperature)
        self._adapt_brightness = True
        self._adapt_color = True

        # Contexts of the service calls HCL sends itself ({context_id: monotonic time})
        self._own_contexts: dict[str, float] = {}

    @property
    def adapt_brightness(self) -> bool:
        """Whether HCL controls the brightness."""
        return self._adapt_brightness

    @adapt_brightness.setter
    def adapt_brightness(self, value: bool) -> None:
        self._adapt_brightness = bool(value)
        self.override_manager.track_brightness = self._adapt_brightness

    @property
    def adapt_color(self) -> bool:
        """Whether HCL controls the colour temperature."""
        return self._adapt_color

    @adapt_color.setter
    def adapt_color(self, value: bool) -> None:
        self._adapt_color = bool(value)
        self.override_manager.track_color = self._adapt_color

    def is_own_context(self, context: Context | None) -> bool:
        """Return True if a context belongs to a service call sent by HCL."""
        if context is None:
            return False
        return context.id in self._own_contexts or (
            context.parent_id is not None and context.parent_id in self._own_contexts
        )

    def _new_context(self, parent: Context | None = None) -> Context:
        """New context for an HCL command.

        parent: context of the request that caused the command (service call,
        scenario change). It is linked as parent_id, like automations and
        scripts do, so logbook and traces show the origin; the command itself
        runs with HCL's permissions (no user_id).
        """
        now = time.monotonic()
        # Contexts are only needed while the resulting state changes arrive
        for ctx_id in [c for c, t in self._own_contexts.items() if now - t > 300]:
            del self._own_contexts[ctx_id]
        context = Context(parent_id=parent.id if parent is not None else None)
        self._own_contexts[context.id] = now
        return context

    _BRIGHTNESS_KEYS = ("brightness_pct",)
    _COLOR_KEYS = ("color_temp_kelvin", "xy_color")

    def _filter_service_data(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Drop the attributes HCL must not adapt; None if nothing is left to send.

        Brightness 0 (Sleep mode switches lights off) is always kept.
        """
        data = dict(data)
        if not self._adapt_brightness and data.get("brightness_pct") != 0:
            for key in self._BRIGHTNESS_KEYS:
                data.pop(key, None)
        if not self._adapt_color:
            for key in self._COLOR_KEYS:
                data.pop(key, None)
        if not any(key in data for key in self._BRIGHTNESS_KEYS + self._COLOR_KEYS):
            return None
        return data

    async def _async_call(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
        blocking: bool = False,
        parent: Context | None = None,
    ) -> bool:
        """Send a light command with an HCL context (only the adapted attributes).

        Returns True when a command was sent, False when nothing was left to
        send. Errors of the command are raised to the caller.
        """
        data = self._filter_service_data(data)
        if data is None:
            return False
        await self.hass.services.async_call(
            domain, service, data, blocking=blocking, context=self._new_context(parent)
        )
        return True
        
    def set_active_mode(self, mode: str, announce: bool = True) -> None:
        """Set the active scenario mode.

        announce=False (restore at startup/reload): the next update is not
        treated as a scenario change (normal transition).
        """
        if self.active_mode == mode:
            return
            
        self.active_mode = mode
        if announce:
            self._mode_change_pending = True
        _LOGGER.debug("HCL Mode changed to: %s", mode)
        
        # Trigger immediate update logic is handled by the caller (select entity) calling switch.update_ha_state() 
        # or sending a signal. But actually, we should probably expose a signal or callback.
        # For now, select entity calls generic update.

    def calculate_target_values(self, now) -> tuple[int | None, int | None]:
        """
        Calculate target (Brightness, Kelvin) based on Priority Stack.
        User Intent > Curve.
        """
        
        # 1. GUEST MODE (Freeze)
        if self.active_mode == MODE_GUEST:
            return None, None

        # 2. FIXED SCENARIOS
        if self.active_mode in SCENARIO_DEFAULTS:
            # Special Handling: Sleep (Off)
            if self.active_mode == MODE_SLEEP:
                return 0, 2000 # Off, but pre-heat to 2000K
                
            return self.scenario_setpoint(self.active_mode)

        # 3. AUTO MODE (Curve)
        if self.active_mode == MODE_AUTO:
            min_b, max_b = self.brightness_limits()
            scale = self.config_entry.options.get(CONF_BRIGHTNESS_SCALING, DEFAULT_BRIGHTNESS_SCALING)
            return self.hcl_calc.get_hcl_values(now, min_b, max_b, scale=bool(scale))
            
        # Fallback
        return None, None

    def consume_mode_change(self) -> bool:
        """True once after a scenario change (for the scenario transition)."""
        pending = self._mode_change_pending
        self._mode_change_pending = False
        return pending

    def scenario_setpoint(self, mode: str) -> tuple[int, int]:
        """Brightness and colour temperature of a fixed scenario (options, limits)."""
        settings = SCENARIO_DEFAULTS[mode]
        options = self.config_entry.options
        brightness, kelvin = settings["brightness"], settings["kelvin"]
        if mode in CONFIGURABLE_SCENARIOS:
            key_b, key_k = scenario_option_keys(mode)
            brightness = int(options.get(key_b, brightness))
            kelvin = int(options.get(key_k, kelvin))
        # Option: Focus/Relax/Cleaning stay within the min/max brightness
        if mode in LIMITABLE_SCENARIOS and options.get(CONF_SCENARIO_LIMITS, DEFAULT_SCENARIO_LIMITS):
            min_b, max_b = self.brightness_limits()
            brightness = max(min_b, min(max_b, brightness))
        return brightness, kelvin

    def scenario_values(self) -> dict[str, dict[str, int]]:
        """Values of all scenarios with fixed values (for the card)."""
        return {
            mode: dict(zip(("b", "k"), self.scenario_setpoint(mode)))
            for mode, settings in SCENARIO_DEFAULTS.items()
            if settings["brightness"] is not None
        }

    def brightness_limits(self) -> tuple[int, int]:
        """Configured min/max brightness of the curve."""
        options = self.config_entry.options
        return (
            options.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS),
            options.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS),
        )

    def prune_cache(self, valid_entity_ids: set[str]) -> None:
        """Prune capability cache of invalid/removed entities."""
        # Prune main cache
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
        fast_mode: bool = False,
        parent: Context | None = None,
        on_failure: Callable[[list[str]], None] | None = None,
    ) -> BatchResult:
        """Apply settings to a batch of lights (one command per light, in parallel).

        Each light gets its own command: Home Assistant runs a command for
        several lights for all of them and raises the first error afterwards,
        so the lights of a shared command could not be told apart.

        A light whose command failed (or was not sent) gets its previous
        tracking values and ignore window back, so the manual-control
        detection does not use values the light never received.

        fast_mode: the commands run in the background (the caller does not
        wait); result.updated holds the lights a command was sent to, and
        on_failure is called with the lights whose command failed later.
        """
        result = BatchResult()
        if not lights:
            return result

        transition_val = 0 if transition is None else transition
        smart_transition = self.config_entry.options.get(CONF_SMART_TRANSITION, False)
        bulk = transition_val == 0 or not smart_transition
        xy = color_RGB_to_xy(*color_temperature_to_rgb(kelvin))

        previous: dict[str, tuple[Any, Any]] = {}
        # (light, command)
        jobs: list[tuple[str, Awaitable[bool]]] = []

        for entity_id in lights:
            # Check thresholds to avoid redundant traffic
            if not self._needs_update(entity_id, brightness, kelvin):
                continue
            cap_type = self._get_capability(entity_id, kelvin)
            data: dict[str, Any] = {"entity_id": [entity_id], "brightness_pct": brightness, "transition": transition_val}
            if cap_type == "ct":
                # Native colour temperature: the value the light can reach
                tracked_kelvin = self.reachable_kelvin(entity_id, kelvin)
                data["color_temp_kelvin"] = tracked_kelvin
                job = (
                    self._async_call("light", "turn_on", data, blocking=True, parent=parent)
                    if bulk else self._apply_smart_ct_single(entity_id, tracked_kelvin, brightness, transition_val, parent)
                )
            elif cap_type == "xy_sim":
                tracked_kelvin = kelvin
                data["xy_color"] = xy
                job = (
                    self._async_call("light", "turn_on", data, blocking=True, parent=parent)
                    if bulk else self._apply_smart_xy_single(entity_id, xy[0], xy[1], brightness, transition_val, parent)
                )
            elif cap_type == "dim":
                tracked_kelvin = kelvin
                job = self._async_call("light", "turn_on", data, blocking=True, parent=parent)
            else:
                continue
            # Tracking is set before sending (state reports may arrive at once);
            # a failed command restores it.
            previous[entity_id] = self.override_manager.tracking_snapshot(entity_id)
            self.override_manager.set_last_set_values(entity_id, brightness, tracked_kelvin)
            self.override_manager.set_ignore_window(entity_id, transition_val)
            jobs.append((entity_id, job))

        if not jobs:
            return result

        if fast_mode:
            for entity_id, job in jobs:
                task = self.hass.async_create_task(job)
                task.add_done_callback(
                    lambda t, eid=entity_id: self._background_result(t, eid, previous[eid], on_failure)
                )
                result.updated.append(entity_id)
            return result

        outcomes = await asyncio.gather(*(job for _, job in jobs), return_exceptions=True)
        for (entity_id, _job), outcome in zip(jobs, outcomes):
            if outcome is True:
                result.updated.append(entity_id)
                continue
            if isinstance(outcome, BaseException):
                _LOGGER.error("Light update for %s failed: %s", entity_id, outcome, exc_info=outcome)
                result.failed[entity_id] = outcome
            self.override_manager.restore_tracking(entity_id, previous[entity_id])
        return result

    def _background_result(
        self,
        task: asyncio.Task,
        entity_id: str,
        previous: tuple[Any, Any],
        on_failure: Callable[[list[str]], None] | None,
    ) -> None:
        """Result of a command sent in fast mode."""
        if task.cancelled():
            error: BaseException | None = asyncio.CancelledError()
        else:
            error = task.exception()
        if error is None and task.result() is True:
            return
        if error is not None:
            _LOGGER.error("Light update for %s failed: %s", entity_id, error, exc_info=error)
        self.override_manager.restore_tracking(entity_id, previous)
        if on_failure is not None:
            on_failure([entity_id])

    async def apply_fast(
        self,
        entity_id: str,
        brightness: int,
        kelvin: int,
        state_obj=None,
        transition: float = 0,
        ignore_seconds: float | None = None,
    ) -> bool:
        """Ultra-fast HCL application for turn-on events (True if the command succeeded).

        The tracking values and the ignore window are set before the command
        (synchronously, before the first await, so the first state report of
        the light is not taken for manual control) and restored if the
        command is not sent or fails.
        """
        _LOGGER.debug("Applying Fast-HCL to %s (B:%s%%, K:%sK)", entity_id, brightness, kelvin)

        # Use passed state object or fallback to lookup (performance optimization)
        state = state_obj or self.hass.states.get(entity_id)
        if state is None:
            return False
        if self._is_group(entity_id, state):
            _LOGGER.debug("Ignoring Fast-HCL for Group/Hue Group: %s", entity_id)
            return False

        cap_type = self._get_capability(entity_id, kelvin, state)
        service_data = {"entity_id": entity_id, "brightness_pct": brightness, "transition": transition}
        tracked_kelvin = kelvin
        if cap_type == "ct":
            tracked_kelvin = self.reachable_kelvin(entity_id, kelvin, state)
            service_data["color_temp_kelvin"] = tracked_kelvin
        elif cap_type == "xy_sim":
            service_data["xy_color"] = color_RGB_to_xy(*color_temperature_to_rgb(kelvin))
        elif cap_type != "dim":
            return False  # onoff or unknown

        previous = self.override_manager.tracking_snapshot(entity_id)
        self.override_manager.set_last_set_values(entity_id, brightness, tracked_kelvin)
        self.override_manager.set_ignore_window(
            entity_id, transition if ignore_seconds is None else ignore_seconds
        )
        try:
            sent = await self._async_call("light", "turn_on", service_data, blocking=True)
        except Exception as err:  # the light keeps its previous tracking
            _LOGGER.error("Light update for %s after switching on failed: %s", entity_id, err, exc_info=err)
            self.override_manager.restore_tracking(entity_id, previous)
            return False
        if not sent:
            self.override_manager.restore_tracking(entity_id, previous)
        return sent

    async def reengage_light(
        self, entity_id: str, target_brightness: int, target_kelvin: int, parent: Context | None = None
    ) -> None:
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
        
        def _failed(eids: list[str]) -> None:
            # The command failed: the normal updates take the light back
            for eid in eids:
                self.override_manager.end_reengaging(eid)

        result = await self.apply_batch(
            [entity_id], 
            target_brightness, 
            target_kelvin, 
            transition=duration,
            fast_mode=True,  # Don't block main loop
            parent=parent,
            on_failure=_failed,
        )
        # Normal update cycles must not cut the smooth transition short
        if entity_id in result.updated:
            self.override_manager.set_reengaging(entity_id, duration)

    def capability_for(self, entity_id: str, kelvin: int) -> str:
        """How a light is driven for a colour temperature (ct, xy_sim, dim, onoff)."""
        return self._get_capability(entity_id, kelvin)

    def _get_capability(self, entity_id: str, kelvin: int, state_obj=None) -> str:
        """Determine how a light is driven for a target colour temperature.

        The light's capabilities are cached; the range check (native CT or XY
        simulation) is done for every target value.
        """
        return self._get_capability_internal(entity_id, kelvin, state_obj)

    def _get_capability_internal(self, entity_id: str, kelvin: int, state_obj=None) -> str:
        """Internal capability resolution logic."""
        
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
                # Valid Cache
                native_type = cached["type"]
                
                # Dynamic Check: If Native CT but out of range -> Simulate XY
                if (native_type == "ct" and 
                    cached.get("min_kelvin") is not None and 
                    cached.get("max_kelvin") is not None and
                    cached.get("supports_color")):
                    
                    if kelvin < cached["min_kelvin"] or kelvin > cached["max_kelvin"]:
                        return "xy_sim"
                        
                return native_type

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
        
        # Explicit None Check
        if supported_modes is None:
             _LOGGER.debug("Entity %s has no 'supported_color_modes'", entity_id)
             return "onoff"

        # Type safety: ensure iterable
        if not isinstance(supported_modes, (list, tuple)):
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
            for mode in _COLOR_MODES
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
        
        # Handle CT lights with missing min/max kelvin
        if cap_type == "ct":
            if min_kelvin is None: min_kelvin = 2000
            if max_kelvin is None: max_kelvin = 6500

        # Store NATIVE Capability in Cache
        cap_data = {
            "type": cap_type, # Always store native type (ct, xy_sim, dim)
            "min_kelvin": min_kelvin,
            "max_kelvin": max_kelvin,
            "supports_color": supports_color,
            "version": self._cache_version
        }
        self._capability_cache[entity_id] = cap_data

        _LOGGER.debug(
            "Capability cached for %s: %s (v%s, modes=%s)", 
            entity_id, cap_type, self._cache_version, supported_modes
        )

        # Dynamic Override (Runtime Only, do not cache simulation type)
        if (cap_type == "ct" and supports_color and 
            (kelvin < min_kelvin or kelvin > max_kelvin)):
             return "xy_sim"
        
        return cap_type

    def _calculate_capability_from_state(self, state) -> str:
        """Calculate capability without caching (for unsafe states)."""
        supported_modes = state.attributes.get(ATTR_SUPPORTED_COLOR_MODES)
        
        if supported_modes is None:
            return "onoff"
        
        # Type safety: ensure iterable
        if not isinstance(supported_modes, (list, tuple)):
            # Invalid type (e.g. string) -> onoff
            return "onoff"

        supported_modes = supported_modes or []
        
        if not supported_modes:
            return "onoff"
        
        supports_color = any(
            mode in supported_modes 
            for mode in _COLOR_MODES
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
        # Fix verified: One single source of truth for brightness percentage.
        curr_b_pct = round(curr_b * 100 / 255) if curr_b is not None else None
        curr_k = state.attributes.get(ATTR_COLOR_TEMP_KELVIN)
        
        # Safety Check: Ignore Groups (Hue Groups or HA Groups)
        # Groups shouldn't be in the list, but if they sneak in (e.g. startup race),
        # we strictly ignore them here to avoid "Double Control".
        if self._is_group(entity_id):
            return False

        # Only the adapted attributes count (brightness 0 = Sleep switches off)
        check_b = self._adapt_brightness or target_b == 0
        check_k = self._adapt_color
        if not check_b and not check_k:
            return False

        # Check Brightness
        delta_b = 0
        if not check_b:
            pass
        elif curr_b is not None:
             delta_b = abs(curr_b_pct - target_b)
        else:
            # Unknown brightness, assume update needed
            return True
            
        # Check Kelvin (if supported)
        delta_k = 0
        if not check_k:
            pass
        elif curr_k is not None:
             # Compare with what the light can reach: a CT light clamps the
             # target to its own range and reports the clamped value.
             delta_k = abs(curr_k - self.reachable_kelvin(entity_id, target_k, state))
        elif self._get_capability(entity_id, target_k) in ("ct", "xy_sim"):
             # Light is in a colour mode (e.g. XY simulation): no colour_temp is
             # reported, so compare the XY colour with the XY value HCL sends.
             curr_xy = state.attributes.get("xy_color")
             if not curr_xy:
                 return True
             target_x, target_y = color_RGB_to_xy(*color_temperature_to_rgb(target_k))
             dist_xy = ((curr_xy[0] - target_x) ** 2 + (curr_xy[1] - target_y) ** 2) ** 0.5
             if dist_xy > XY_COLOR_DISTANCE_THRESHOLD:
                 return True
             delta_k = abs(
                 color_xy_to_temperature(curr_xy[0], curr_xy[1])
                 - color_xy_to_temperature(target_x, target_y)
             )
        
        if delta_b <= BRIGHTNESS_THRESHOLD and (delta_k <= KELVIN_THRESHOLD if target_k else True):
             # Logs demoted to TRACE (level 5) to avoid spam
             _LOGGER.log(5, "Skipping update for %s: Change too small (Delta B=%s%%, K=%sK)", entity_id, delta_b, delta_k if target_k else "N/A")
             return False
        
        return True

    def reachable_kelvin(self, entity_id: str, kelvin: int, state_obj=None) -> int:
        """Return the colour temperature a CT light actually shows for a target.

        Lights controlled via native colour temperature clamp the target to
        their min/max range. Lights simulated via XY get the target unchanged.
        """
        state = state_obj or self.hass.states.get(entity_id)
        if state is None or self._get_capability(entity_id, kelvin) != "ct":
            return kelvin
        min_k = state.attributes.get("min_color_temp_kelvin")
        max_k = state.attributes.get("max_color_temp_kelvin")
        if min_k is not None and kelvin < min_k:
            return min_k
        if max_k is not None and kelvin > max_k:
            return max_k
        return kelvin

    def resolve_targets(self, target_config: dict[str, Any], groups: set[str] | None = None) -> set[str]:
        """Resolve target config to a set of light entity IDs.

        Entities, devices, areas, floors and labels are resolved by Home
        Assistant's own target resolution of the running version (the same
        one light actions use): hidden and configuration/diagnostic lights
        reached indirectly are skipped, a light with its own area belongs to
        that area, disabled lights are not included, and on versions with
        child/composite devices a device includes them. Lights given
        directly are always used. Light groups are expanded afterwards.

        groups (optional) collects the light groups that were expanded, so the
        caller can watch their member lists.
        """
        selected = extract_referenced_entities(self.hass, target_config)
        entity_ids = {
            eid for eid in selected.referenced | selected.indirectly_referenced
            if eid.startswith("light.")
        }

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
                 if groups is not None:
                     groups.add(eid)
            elif (state.attributes.get("is_hue_group") or state.attributes.get("lights") or state.attributes.get("hue_type")):
                continue # Skip raw Hue groups
            else:
                if eid.startswith("light."):
                    final_entities.add(eid)
                
        return final_entities

    async def _apply_smart_xy_single(
        self, entity_id, x, y, brightness, transition, parent: Context | None = None
    ) -> bool:
        """Colour and brightness in two steps; the larger change gets the transition.

        If the two-step command fails, the values are sent once without
        transition. If that fails too, the error is raised to apply_batch.
        """
        state = self.hass.states.get(entity_id)
        if not state:
            return False
        try:
            curr_bri = state.attributes.get("brightness") or 0
            curr_xy = state.attributes.get("xy_color") or (x, y)
            target_bri_byte = int(round(float(brightness) * 255 / 100))
            delta_b = abs(curr_bri - target_bri_byte) / 255.0
            curr_x, curr_y = curr_xy
            delta_c = ((curr_x - x)**2 + (curr_y - y)**2)**0.5 * XY_COLOR_SENSITIVITY

            if delta_c > delta_b:
                first = await self._async_call("light", "turn_on", {"entity_id": entity_id, "brightness_pct": brightness, "transition": 0}, blocking=True, parent=parent)
                second = await self._async_call("light", "turn_on", {"entity_id": entity_id, "xy_color": (x, y), "transition": transition}, blocking=True, parent=parent)
            else:
                first = await self._async_call("light", "turn_on", {"entity_id": entity_id, "xy_color": (x, y), "transition": 0}, blocking=True, parent=parent)
                second = await self._async_call("light", "turn_on", {"entity_id": entity_id, "brightness_pct": brightness, "transition": transition}, blocking=True, parent=parent)
            return first or second
        except Exception as err:  # the fallback below reports a final failure
            _LOGGER.warning(
                "Smart transition for %s failed (%s); sending the values without transition", entity_id, err
            )
        return await self._async_call(
            "light", "turn_on",
            {"entity_id": entity_id, "brightness_pct": brightness, "xy_color": (x, y), "transition": 0},
            blocking=True, parent=parent,
        )

    async def _apply_smart_ct_single(
        self, entity_id, kelvin, brightness, transition, parent: Context | None = None
    ) -> bool:
        """Colour temperature without transition, brightness with it (IKEA-safe).

        kelvin is already limited to the light's range. If the command fails,
        the values are sent once without transition; if that fails too, the
        error is raised to apply_batch.
        """
        state = self.hass.states.get(entity_id)
        if not state:
            return False
        try:
            curr_bri = state.attributes.get("brightness") or 0
            curr_kelvin = state.attributes.get("color_temp_kelvin") or 2700
            target_bri_byte = int(round(float(brightness) * 255 / 100))
            delta_b = abs(curr_bri - target_bri_byte) / 255.0
            delta_k = abs(curr_kelvin - kelvin) / KELVIN_RANGE
            sent = False

            if delta_k > delta_b:
                # Check if brightness change is significant enough to warrant a snap
                if abs(curr_bri - target_bri_byte) > (BRIGHTNESS_THRESHOLD / 100.0 * 255):
                    sent |= await self._async_call("light", "turn_on", {"entity_id": entity_id, "brightness_pct": brightness, "transition": 0}, blocking=True, parent=parent)
                # Send color without transition to avoid glitches on IKEA bulbs
                sent |= await self._async_call("light", "turn_on", {"entity_id": entity_id, "color_temp_kelvin": kelvin}, blocking=True, parent=parent)
            else:
                # Only snap color if delta is significant. NEVER send transition with color_temp.
                if abs(curr_kelvin - kelvin) > KELVIN_THRESHOLD:
                    sent |= await self._async_call("light", "turn_on", {"entity_id": entity_id, "color_temp_kelvin": kelvin}, blocking=True, parent=parent)
                sent |= await self._async_call("light", "turn_on", {"entity_id": entity_id, "brightness_pct": brightness, "transition": transition}, blocking=True, parent=parent)
            return sent
        except Exception as err:  # the fallback below reports a final failure
            _LOGGER.warning(
                "Smart transition for %s failed (%s); sending the values without transition", entity_id, err
            )
        # Fallback: send everything, no transition (safest)
        return await self._async_call(
            "light", "turn_on",
            {"entity_id": entity_id, "brightness_pct": brightness, "color_temp_kelvin": kelvin},
            blocking=True, parent=parent,
        )

    def _is_group(self, entity_id: str, state_obj=None) -> bool:
        """Check if entity is a group."""
        state = state_obj or self.hass.states.get(entity_id)
        if not state:
            return False
        return (state.attributes.get("is_hue_group") or 
                state.attributes.get("hue_type") or 
                isinstance(state.attributes.get(ATTR_ENTITY_ID), (list, tuple)))
