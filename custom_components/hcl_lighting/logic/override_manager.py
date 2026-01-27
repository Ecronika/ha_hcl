"""State management for manual overrides."""
from __future__ import annotations

import logging
from datetime import timedelta
from homeassistant.util import dt as dt_util
from homeassistant.core import State

from ..const import (
    OVERRIDE_TIMEOUT_HOURS,
    OVERRIDE_BRIGHTNESS_DELTA,
    OVERRIDE_KELVIN_DELTA,
)

_LOGGER = logging.getLogger(__name__)

class OverrideManager:
    """Manages manual override states for HCL lights."""

    def __init__(self):
        """Initialize the manager."""
        # Dict structure:
        # {
        #   entity_id: {
        #       "last_set": (brightness, kelvin),
        #       "manual_override_time": datetime | None,
        #       "ignore_events_until": datetime | None
        #   }
        # }
        self._override_state = {}

    def is_overridden(self, entity_id: str) -> bool:
        """Check if a light is currently in manual override."""
        state = self._override_state.get(entity_id)
        if not state:
            return False
        return state is not None

    def set_ignore_window(self, entity_id: str, seconds: float) -> None:
        """Set a time window where state changes are ignored (treated as HCL updates)."""
        now = dt_util.now()
        # Explicit type cast to prevent timedelta type confusion
        safe_seconds = float(seconds)
        ignore_until = now + timedelta(seconds=safe_seconds + 2) # Buffer
        self._ignore_windows[entity_id] = ignore_until
        _LOGGER.debug("Ignoring event for %s (Window active until %s)", entity_id, ignore_until)

    def prune_stale_entities(self, valid_entity_ids: set[str]) -> None:
        """Remove override state for entities that are no longer tracked."""
        # Create list to avoid size mutation during iteration
        stale_ids = [eid for eid in self._override_state if eid not in valid_entity_ids]
        
        for eid in stale_ids:
            self._override_state.pop(eid, None)
            self._ignore_windows.pop(eid, None)
            self._last_set_values.pop(eid, None)
            
        if stale_ids:
            _LOGGER.debug("Pruned %d stale entities from OverrideManager", len(stale_ids))

    def set_last_set_values(self, entity_id: str, brightness: int, kelvin: int):
        """Update the last known HCL values applied to the light."""
        self._last_set_values[entity_id] = (brightness, kelvin)


    def check_override(self, entity_id: str, state: State | None, last_set_values: tuple[int, int] | None) -> bool:
        """Check if state change is a manual override.
        
        Returns:
            bool: True if override was detected, False otherwise.
        """
        if not state:
            return False

        now = dt_util.now()

        # 1. Check Ignore Window
        ignore_until = self._ignore_windows.get(entity_id)
        if ignore_until and now < ignore_until:
             _LOGGER.debug("Ignoring event for %s (Window active until %s)", entity_id, ignore_until)
             return False

        # 2. Check if light is ON
        if state.state != "on":
            # Reset override if light is turned off
            if self._override_state.get(entity_id):
                _LOGGER.debug("Override reset for %s (turned off)", entity_id)
                self._override_state[entity_id] = None
            return False

        # 3. Compare with Expected Values
        # Priority: internal last_set > global last_applied
        recorded_last_set = self._last_set_values.get(entity_id)
        reference_values = recorded_last_set or last_set_values

        ref_b, ref_k = reference_values or (None, None)

        curr_b = state.attributes.get("brightness")
        curr_k = state.attributes.get("color_temp_kelvin")

        if curr_b is None:
            _LOGGER.debug("Ignoring event for %s (Brightness is None/Unknown)", entity_id)
            return False
        # Percentage with Bounds Check
        curr_b = min(255, max(0, curr_b))
        curr_b_pct = int(curr_b * 100 / 255)
        
        # Calculate Deltas
        delta_b = abs(curr_b_pct - last_b)
        delta_k = 0
        if curr_k and last_k:
            delta_k = abs(curr_k - last_k)

        # Threshold Check
        is_override = False
        reasons = []

        if delta_b > OVERRIDE_BRIGHTNESS_DELTA:
            is_override = True
            reasons.append(f"Brightness (L:{last_b}%->C:{curr_b_pct}%, d:{delta_b}%)")

        if delta_k > OVERRIDE_KELVIN_DELTA:
             is_override = True
             reasons.append(f"Kelvin (L:{last_k}K->C:{curr_k}K, d:{delta_k}K)")
        
        if is_override:
            _LOGGER.debug("Manual Override detected for %s: %s", entity_id, ", ".join(reasons))

        if is_override:
            light_data["manual_override_time"] = now
            return True
            
        return False

    def get_pending_reengagements(self) -> list[str]:
        """Get list of entities where override has expired and need re-engagement."""
        now = dt_util.now()
        ready = []
        
        for eid, data in self._override_state.items():
            override_time = data.get("manual_override_time")
            if override_time:
                diff = now - override_time
                if diff > timedelta(hours=OVERRIDE_TIMEOUT_HOURS):
                    _LOGGER.debug("Override timeout expired for %s", eid)
                    data["manual_override_time"] = None # Clear override
                    ready.append(eid)
        
        return ready

    def reset_override(self, entity_id: str):
        """Manually reset override state."""
        if entity_id in self._override_state:
             self._override_state[entity_id]["manual_override_time"] = None
