"""State management for manual overrides."""
from __future__ import annotations

import logging
from datetime import timedelta
from homeassistant.util import dt as dt_util
from homeassistant.core import State
from homeassistant.util.color import color_temperature_to_rgb, color_RGB_to_xy

from ..const import (
    OVERRIDE_TIMEOUT_HOURS,
    OVERRIDE_BRIGHTNESS_DELTA,
    OVERRIDE_KELVIN_DELTA,
    XY_COLOR_DISTANCE_THRESHOLD,
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
        # Behaviour (set from the entry options / adapt switches)
        self.timeout: timedelta | None = timedelta(hours=OVERRIDE_TIMEOUT_HOURS)
        self.reset_on_off = True
        self.track_brightness = True
        self.track_color = True
        # Called whenever the set of manually controlled lights changes
        self.on_change = None

    def _notify(self) -> None:
        if self.on_change:
            self.on_change()

    def overridden_entities(self) -> list[str]:
        """Return the lights that are currently under manual control."""
        return sorted(
            eid for eid, data in self._override_state.items()
            if data.get("manual_override_time") is not None
        )

    def export_overrides(self) -> dict[str, str]:
        """Serializable manual-control state ({entity_id: ISO timestamp})."""
        return {
            eid: data["manual_override_time"].isoformat()
            for eid, data in self._override_state.items()
            if data.get("manual_override_time") is not None
        }

    def import_overrides(self, stored: dict[str, str]) -> None:
        """Restore manual-control state exported by export_overrides."""
        for eid, iso in (stored or {}).items():
            when = dt_util.parse_datetime(iso) if isinstance(iso, str) else None
            if when is not None:
                self._override_state.setdefault(eid, {})["manual_override_time"] = when

    def is_overridden(self, entity_id: str) -> bool:
        """Check if a light is currently in manual override."""
        state = self._override_state.get(entity_id)
        if not state:
            return False
        return state.get("manual_override_time") is not None

    def set_ignore_window(self, entity_id: str, seconds: float) -> None:
        """Set a window where state changes are ignored (to prevent self-detection)."""
        if entity_id not in self._override_state:
            self._override_state[entity_id] = {}
        
        now = dt_util.now()
        # Explicit type cast to prevent timedelta type confusion
        safe_seconds = float(seconds)
        ignore_until = now + timedelta(seconds=safe_seconds + 2) # 2s buffer
        self._override_state[entity_id]["ignore_events_until"] = ignore_until

    def prune_stale_entities(self, valid_entity_ids: set[str]) -> None:
        """Remove override tracking for entities no longer in target list."""
        to_remove = [eid for eid in self._override_state if eid not in valid_entity_ids]
        
        was_overridden = any(self.is_overridden(eid) for eid in to_remove)
        for eid in to_remove:
            del self._override_state[eid]
            
        if to_remove:
            _LOGGER.debug("Pruned %d stale entities from OverrideManager", len(to_remove))
        if was_overridden:
            self._notify()

    def set_last_set_values(self, entity_id: str, brightness: int, kelvin: int):
        """Update the last known HCL values applied to the light."""
        if entity_id not in self._override_state:
            self._override_state[entity_id] = {}
        self._override_state[entity_id]["last_set"] = (brightness, kelvin)

    def check_override(self, entity_id: str, state: State | None, last_set_values: tuple[int, int] | None, old_state: State | None = None) -> bool:
        """Check if state change is a manual override."""
        if not state:
            return False

        if entity_id not in self._override_state:
            self._override_state[entity_id] = {}

        light_data = self._override_state[entity_id]
        now = dt_util.now()

        # Priority: internal last_set > global last_applied
        recorded_last_set = light_data.get("last_set")
        reference_values = recorded_last_set or last_set_values
        last_b = reference_values[0] if reference_values else None
        last_k = reference_values[1] if reference_values and len(reference_values) > 1 else None

        # 1. Check Ignore Window with Divergence Detection
        ignore_until = light_data.get("ignore_events_until")
        if ignore_until and now < ignore_until:
            # Trajectory Analysis: Did we move AWAY from target significantly?
            divergence_detected = False
            if old_state and old_state.state == "on" and last_b is not None:
                try:
                    if self.track_brightness:
                        curr_b_raw = state.attributes.get("brightness") or 0
                        old_b_raw = old_state.attributes.get("brightness") or 0

                        curr_pct = round(curr_b_raw * 100 / 255)
                        old_pct = round(old_b_raw * 100 / 255)

                        dist_new = abs(curr_pct - last_b)
                        dist_old = abs(old_pct - last_b)

                        # If new distance is significantly larger (>5%) than old distance,
                        # the user moved the light away from the target -> Override!
                        if dist_new > dist_old + 5:
                            _LOGGER.debug(
                                "Override detected inside Ignore Window! Divergence: OldDist=%s%%, NewDist=%s%%",
                                dist_old, dist_new
                            )
                            divergence_detected = True

                    # Same trajectory check for colour: an HCL transition only moves
                    # towards the target, a user change moves away from it.
                    curr_k = state.attributes.get("color_temp_kelvin")
                    old_k = old_state.attributes.get("color_temp_kelvin")
                    if self.track_color and last_k and curr_k and old_k:
                        dist_new_k = abs(curr_k - last_k)
                        dist_old_k = abs(old_k - last_k)
                        if dist_new_k > dist_old_k + OVERRIDE_KELVIN_DELTA:
                            _LOGGER.debug(
                                "Override detected inside Ignore Window! Kelvin divergence: OldDist=%sK, NewDist=%sK",
                                dist_old_k, dist_new_k
                            )
                            divergence_detected = True

                    curr_xy = state.attributes.get("xy_color")
                    old_xy = old_state.attributes.get("xy_color")
                    if self.track_color and last_k and curr_xy and old_xy:
                        exp_x, exp_y = color_RGB_to_xy(*color_temperature_to_rgb(last_k))
                        dist_new_xy = ((curr_xy[0] - exp_x) ** 2 + (curr_xy[1] - exp_y) ** 2) ** 0.5
                        dist_old_xy = ((old_xy[0] - exp_x) ** 2 + (old_xy[1] - exp_y) ** 2) ** 0.5
                        if dist_new_xy > dist_old_xy + XY_COLOR_DISTANCE_THRESHOLD:
                            _LOGGER.debug(
                                "Override detected inside Ignore Window! XY divergence: OldDist=%.3f, NewDist=%.3f",
                                dist_old_xy, dist_new_xy
                            )
                            divergence_detected = True
                except Exception:
                    pass # Fallback to standard ignore
            
            if not divergence_detected:
                _LOGGER.debug("Ignoring event for %s (Window active until %s)", entity_id, ignore_until)
                return False

        # 2. Check if light is ON
        if state.state != "on":
            # Switching a light off ends its manual control (configurable)
            if self.reset_on_off and light_data.get("manual_override_time"):
                _LOGGER.debug("Override reset for %s (turned off)", entity_id)
                light_data["manual_override_time"] = None
                self._notify()
            return False

        # 3. Compare with Expected Values
        # Priority: internal last_set > global last_applied
        # recorded_last_set = light_data.get("last_set") # Already got above
        # reference_values = recorded_last_set or last_set_values

        if reference_values and len(reference_values) == 2:
            last_b, last_k = reference_values
        else:
             # If no reference values (startup/race), assume valid to prevent crash
             return False

        if last_b is None or last_k is None:
             return False

        curr_b = state.attributes.get("brightness")
        curr_k = state.attributes.get("color_temp_kelvin")

        if curr_b is None:
            _LOGGER.debug("Ignoring event for %s (Brightness is None/Unknown)", entity_id)
            return False

        # Percentage with Bounds Check
        curr_b = min(255, max(0, curr_b))
        curr_b_pct = round(curr_b * 100 / 255) # Fixed: Use round() for consistency
        
        # Calculate Deltas
        delta_b = abs(curr_b_pct - last_b)
        delta_k = 0
        if curr_k and last_k:
            delta_k = abs(curr_k - last_k)

        # Threshold Check
        is_override = False
        reasons = []

        if self.track_brightness and delta_b > OVERRIDE_BRIGHTNESS_DELTA:
            is_override = True
            reasons.append(f"Brightness (L:{last_b}%->C:{curr_b_pct}%, d:{delta_b}%)")

        if self.track_color and delta_k > OVERRIDE_KELVIN_DELTA:
             is_override = True
             reasons.append(f"Kelvin (L:{last_k}K->C:{curr_k}K, d:{delta_k}K)")

        # XY Color Check (Fallback if Kelvin is missing or for Color changes)
        # Threshold 0.05 covers significant color changes while ignoring minor gamut drifts
        if not is_override and self.track_color and last_k:
            curr_xy = state.attributes.get("xy_color")
            if curr_xy:
                try:
                    # Calculate expected XY from last known Kelvin
                    rgb = color_temperature_to_rgb(last_k)
                    exp_x, exp_y = color_RGB_to_xy(*rgb)
                    curr_x, curr_y = curr_xy
                    
                    # Euclidean distance
                    dist_xy = ((curr_x - exp_x)**2 + (curr_y - exp_y)**2)**0.5
                    
                    if dist_xy > XY_COLOR_DISTANCE_THRESHOLD:
                        is_override = True
                        reasons.append(f"XY Color (d:{dist_xy:.3f})")
                except Exception:
                    pass # Math errors shouldn't crash logic
        
        if is_override:
            _LOGGER.debug("Manual Override detected for %s: %s", entity_id, ", ".join(reasons))

        if is_override:
            light_data["manual_override_time"] = now
            self._notify()
            return True
            
        return False

    def get_pending_reengagements(self) -> list[str]:
        """Get list of entities where override has expired and need re-engagement."""
        now = dt_util.now()
        ready = []
        if self.timeout is None:
            return ready

        for eid, data in self._override_state.items():
            override_time = data.get("manual_override_time")
            if override_time:
                diff = now - override_time
                if diff > self.timeout:
                    _LOGGER.debug("Override timeout expired for %s", eid)
                    data["manual_override_time"] = None # Clear override
                    ready.append(eid)

        if ready:
            self._notify()
        return ready

    def set_override(self, entity_id: str) -> None:
        """Mark a light as manually controlled.

        HCL leaves the light alone until it is turned off (if configured) or
        the override timeout expires.
        """
        if entity_id not in self._override_state:
            self._override_state[entity_id] = {}
        self._override_state[entity_id]["manual_override_time"] = dt_util.now()
        self._notify()

    def reset_override(self, entity_id: str):
        """Manually reset override state."""
        if entity_id in self._override_state and self._override_state[entity_id].get("manual_override_time"):
             self._override_state[entity_id]["manual_override_time"] = None
             self._notify()
