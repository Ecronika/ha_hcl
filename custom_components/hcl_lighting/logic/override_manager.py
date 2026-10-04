"""State management for manual overrides."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
from homeassistant.util import dt as dt_util
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State
from homeassistant.util.color import color_temperature_to_rgb, color_RGB_to_xy

from ..const import (
    OVERRIDE_TIMEOUT_HOURS,
    OVERRIDE_BRIGHTNESS_DELTA,
    OVERRIDE_KELVIN_DELTA,
    TRAJECTORY_BRIGHTNESS_DELTA,
    UNREACHABLE_GRACE_SECONDS,
    XY_COLOR_DISTANCE_THRESHOLD,
)

UNREACHABLE_STATES = (STATE_UNAVAILABLE, STATE_UNKNOWN)
_TRACKING_KEYS = ("last_set", "ignore_events_until", "command_start")


def _pct(brightness) -> int | None:
    """Brightness 0-255 as percent (None if unknown)."""
    if brightness is None:
        return None
    return round(min(255, max(0, brightness)) * 100 / 255)


def _xy_distance(xy, target) -> float | None:
    if not xy or not target:
        return None
    return ((xy[0] - target[0]) ** 2 + (xy[1] - target[1]) ** 2) ** 0.5


# Verdicts on a value reported with HCL's context (RM-B33)
_OWN, _OPEN, _AWAY = 0, 1, 2


def _verdict(curr, target, old, start, tolerance) -> int:
    """Whether a value reported with HCL's context belongs to HCL's command (RM-B33).

    _OWN: at the target, or moving towards it (also a slow ramp of the device).
    _OPEN: back towards the light's value when the command was sent (start).
    A device can report the target at once and then its own values of the
    transition, but a user can dim back as well: it is decided when the
    command's transition has ended (see own_report_pending).
    _AWAY: beyond the range between start and target - a manual change.
    """
    if curr is None or target is None:
        return _OWN
    if abs(curr - target) <= tolerance:
        return _OWN
    if old is not None and abs(curr - target) <= abs(old - target) + tolerance:
        return _OWN
    if start is not None and min(start, target) - tolerance <= curr <= max(start, target) + tolerance:
        return _OPEN
    return _AWAY if old is not None or start is not None else _OWN


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
        #       "ignore_events_until": datetime | None,
        #       "command_start": (brightness %, kelvin, xy) of the light when
        #                        HCL sent its last command (None if it was off),
        #       "unreachable_since": datetime  (while unavailable/unknown)
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

    def set_last_set_values(
        self, entity_id: str, brightness: int, kelvin: int, start: State | None = None
    ) -> None:
        """Update the last known HCL values applied to the light.

        start: state of the light when the command is sent; its values are the
        other end of the command's transition (RM-B33).
        """
        if entity_id not in self._override_state:
            self._override_state[entity_id] = {}
        data = self._override_state[entity_id]
        data["last_set"] = (brightness, kelvin)
        data.pop("own_report_open", None)
        if start is not None and start.state == "on":
            attrs = start.attributes
            data["command_start"] = (
                _pct(attrs.get("brightness")), attrs.get("color_temp_kelvin"), attrs.get("xy_color")
            )
        else:
            data.pop("command_start", None)

    def tracking_snapshot(self, entity_id: str) -> tuple[Any, ...]:
        """Tracking values a command changes (last values, ignore window, start values)."""
        data = self._override_state.get(entity_id) or {}
        return tuple(data.get(key) for key in _TRACKING_KEYS)

    def restore_tracking(self, entity_id: str, snapshot: tuple[Any, ...]) -> None:
        """Undo the tracking of a command that was not sent or failed.

        The light never got the values: neither the values nor the ignore
        window of that command may be used by the manual-control detection.
        """
        data = self._override_state.get(entity_id)
        if data is None:
            return
        for key, value in zip(_TRACKING_KEYS, snapshot):
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value

    def check_override(self, entity_id: str, state: State | None, last_set_values: tuple[int, int] | None, old_state: State | None = None) -> bool:
        """Check if state change is a manual override."""
        if not state:
            return False

        if entity_id not in self._override_state:
            self._override_state[entity_id] = {}

        light_data = self._override_state[entity_id]
        now = dt_util.now()

        # 0. Unavailable/unknown says nothing about the light: it is not
        # switched off and keeps its manual control (RM-B24). When it reports
        # again, light_returned() decides by the length of the gap.
        if state.state in UNREACHABLE_STATES:
            light_data.setdefault("unreachable_since", now)
            return False

        # Priority: internal last_set > global last_applied
        recorded_last_set = light_data.get("last_set")
        reference_values = recorded_last_set or last_set_values
        last_b = reference_values[0] if reference_values else None
        last_k = reference_values[1] if reference_values and len(reference_values) > 1 else None

        # 1. Check Ignore Window with Divergence Detection (lights that are
        # on; switching off is never an HCL value and goes to step 2, RM-D03)
        ignore_until = light_data.get("ignore_events_until")
        if ignore_until and now < ignore_until and state.state == "on":
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
                        if dist_new > dist_old + TRAJECTORY_BRIGHTNESS_DELTA:
                            _LOGGER.debug(
                                "Change away from the HCL value inside the ignore window for %s "
                                "(brightness distance %s%% -> %s%%): checking for manual control",
                                entity_id, dist_old, dist_new
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
                                "Change away from the HCL value inside the ignore window for %s "
                                "(colour temperature distance %sK -> %sK): checking for manual control",
                                entity_id, dist_old_k, dist_new_k
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
                                "Change away from the HCL value inside the ignore window for %s "
                                "(colour distance %.3f -> %.3f): checking for manual control",
                                entity_id, dist_old_xy, dist_new_xy
                            )
                            divergence_detected = True
                except Exception:
                    pass # Fallback to standard ignore
            
            if not divergence_detected:
                _LOGGER.debug("Ignoring event for %s (Window active until %s)", entity_id, ignore_until)
                return False

        # 2. Check if light is ON
        light_data.pop("unreachable_since", None)
        if state.state != "on":
            light_data.pop("own_report_open", None)
            # Switching a light off ends its manual control (configurable)
            if self.reset_on_off and light_data.get("manual_override_time"):
                _LOGGER.debug("Override reset for %s (turned off)", entity_id)
                light_data["manual_override_time"] = None
                self._notify()
            return False

        # 3. Compare with the values HCL sent last (reference_values from above)

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
            light_data.pop("reengage_until", None)
            light_data.pop("own_report_open", None)
            self._notify()
            return True
            
        return False

    def _own_report_values(self, data: dict, state: State, old_state: State | None) -> list[tuple[str, int]]:
        """(description, verdict) of the adapted attributes of a report (RM-B33)."""
        last_b, last_k = data["last_set"]
        start_b, start_k, start_xy = data.get("command_start") or (None, None, None)
        old = old_state.attributes if old_state is not None and old_state.state == "on" else {}
        attrs = state.attributes
        out = []
        if self.track_brightness and last_b is not None:
            curr_b = _pct(attrs.get("brightness"))
            out.append((
                f"Brightness (L:{last_b}%->C:{curr_b}%)",
                _verdict(curr_b, last_b, _pct(old.get("brightness")), start_b, TRAJECTORY_BRIGHTNESS_DELTA),
            ))
        if self.track_color and last_k:
            curr_k = attrs.get("color_temp_kelvin")
            if curr_k is not None:
                out.append((
                    f"Kelvin (L:{last_k}K->C:{curr_k}K)",
                    _verdict(curr_k, last_k, old.get("color_temp_kelvin"), start_k, OVERRIDE_KELVIN_DELTA),
                ))
            else:
                # Colour lights (XY simulation): distance to the HCL colour
                try:
                    expected = color_RGB_to_xy(*color_temperature_to_rgb(last_k))
                except Exception:
                    expected = None
                dist = _xy_distance(attrs.get("xy_color"), expected)
                if dist is not None:
                    out.append((
                        f"XY Color (d:{dist:.3f})",
                        _verdict(
                            dist, 0.0, _xy_distance(old.get("xy_color"), expected),
                            _xy_distance(start_xy, expected), XY_COLOR_DISTANCE_THRESHOLD,
                        ),
                    ))
        return out

    def _set_manual(self, entity_id: str, data: dict, reasons: list[str], why: str) -> None:
        _LOGGER.debug("Manual Override detected for %s (%s): %s", entity_id, why, ", ".join(reasons))
        data["manual_override_time"] = dt_util.now()
        data.pop("reengage_until", None)
        data.pop("own_report_open", None)
        self._notify()

    def check_own_report(self, entity_id: str, state: State | None, old_state: State | None = None) -> bool:
        """Check a state report that carries the context of an HCL command (RM-B33).

        Home Assistant gives the state changes of a light the context of the
        last command for 5 seconds, also a change made on the device (e.g. a
        KNX wall dimmer right after switching on). Reports of HCL's command
        reach its values: they are at the target or move towards it. A report
        beyond the range between the light's value at the command and the
        target is a manual change. A report back towards the light's value at
        the command can be either; it is decided when the transition has
        ended (own_report_pending). Returns True if the light is now manually
        controlled.
        """
        data = self._override_state.get(entity_id)
        if not data or data.get("manual_override_time") is not None or not data.get("last_set"):
            return False
        if state is None or state.state != "on":
            data.pop("own_report_open", None)
            return False
        verdicts = self._own_report_values(data, state, old_state)
        reasons = [text for text, verdict in verdicts if verdict == _AWAY]
        if reasons:
            self._set_manual(entity_id, data, reasons, "change on the device within 5 s after an HCL command")
            return True
        if any(verdict == _OPEN for _text, verdict in verdicts):
            _LOGGER.debug(
                "Report of %s with HCL's context moved back towards the value before the command; "
                "decided when the transition has ended", entity_id,
            )
            data["own_report_open"] = True
        elif all(ok for _text, ok in self._at_target(data, state)):
            data.pop("own_report_open", None)
        return False

    def _at_target(self, data: dict, state: State) -> list[tuple[str, bool]]:
        """Per adapted attribute: (description, whether the light is at the HCL value)."""
        last_b, last_k = data["last_set"]
        attrs = state.attributes
        out = []
        if self.track_brightness and last_b is not None and attrs.get("brightness") is not None:
            curr_b = _pct(attrs["brightness"])
            out.append((f"Brightness (L:{last_b}%->C:{curr_b}%)", abs(curr_b - last_b) <= TRAJECTORY_BRIGHTNESS_DELTA))
        if self.track_color and last_k:
            curr_k = attrs.get("color_temp_kelvin")
            if curr_k is not None:
                out.append((f"Kelvin (L:{last_k}K->C:{curr_k}K)", abs(curr_k - last_k) <= OVERRIDE_KELVIN_DELTA))
            else:
                try:
                    expected = color_RGB_to_xy(*color_temperature_to_rgb(last_k))
                except Exception:
                    expected = None
                dist = _xy_distance(attrs.get("xy_color"), expected)
                if dist is not None:
                    out.append((f"XY Color (d:{dist:.3f})", dist <= XY_COLOR_DISTANCE_THRESHOLD))
        return out

    def own_report_pending(self, entity_id: str, state: State | None) -> bool:
        """Decide an open report with HCL's context (RM-B33); True: leave the light alone.

        While the transition of the command runs the light is left alone (its
        values are still on the way). Afterwards a light that stayed away
        from the HCL value was changed on the device: manual control.
        """
        data = self._override_state.get(entity_id)
        if not data or not data.get("own_report_open"):
            return False
        if state is None or state.state != "on" or not data.get("last_set"):
            data.pop("own_report_open", None)
            return False
        ignore_until = data.get("ignore_events_until")
        if ignore_until is not None and dt_util.now() < ignore_until:
            return True
        reasons = [text for text, ok in self._at_target(data, state) if not ok]
        if not reasons:
            data.pop("own_report_open", None)
            return False
        self._set_manual(
            entity_id, data, reasons, "stayed away from the HCL value after a report with HCL's context"
        )
        return True

    def light_returned(self, entity_id: str, old_state: State | None) -> None:
        """A light reports again after being unavailable/unknown (RM-B24).

        A short gap (HA restart, bridge or broker restart, radio dropout)
        keeps its manual control. A longer gap counts like switching off
        (e.g. a lamp without power at the wall switch comes back with its
        power-on values), if manual control ends when a light is switched off.
        """
        data = self._override_state.get(entity_id)
        if data is None:
            return
        since = data.pop("unreachable_since", None)
        if since is None and old_state is not None and old_state.state in UNREACHABLE_STATES:
            since = old_state.last_changed  # gap started before HCL listened
        if since is None or not data.get("manual_override_time"):
            return
        gap = dt_util.now() - since
        if self.reset_on_off and gap > timedelta(seconds=UNREACHABLE_GRACE_SECONDS):
            _LOGGER.debug("Override reset for %s (not reachable for %s)", entity_id, gap)
            data["manual_override_time"] = None
            self._notify()
        else:
            _LOGGER.debug("Manual control of %s kept (not reachable for %s)", entity_id, gap)

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

    def set_reengaging(self, entity_id: str, seconds: float) -> None:
        """Protect a light that is returning to HCL with a smooth transition.

        Normal update cycles leave it alone until the transition has ended.
        """
        self._override_state.setdefault(entity_id, {})["reengage_until"] = (
            dt_util.now() + timedelta(seconds=float(seconds))
        )

    def is_reengaging(self, entity_id: str) -> bool:
        """Whether a light is still in its smooth return to HCL."""
        data = self._override_state.get(entity_id)
        until = data.get("reengage_until") if data else None
        if until is None:
            return False
        if dt_util.now() < until:
            return True
        data.pop("reengage_until", None)
        return False

    def end_reengaging(self, entity_id: str | None = None) -> None:
        """End the smooth return of one light (or of all lights)."""
        targets = [entity_id] if entity_id else list(self._override_state)
        for eid in targets:
            if eid in self._override_state:
                self._override_state[eid].pop("reengage_until", None)

    def set_override(self, entity_id: str) -> None:
        """Mark a light as manually controlled.

        HCL leaves the light alone until it is turned off (if configured) or
        the override timeout expires.
        """
        if entity_id not in self._override_state:
            self._override_state[entity_id] = {}
        self._override_state[entity_id]["manual_override_time"] = dt_util.now()
        self._override_state[entity_id].pop("reengage_until", None)
        self._override_state[entity_id].pop("own_report_open", None)
        self._notify()

    def reset_override(self, entity_id: str):
        """Manually reset override state."""
        if entity_id in self._override_state and self._override_state[entity_id].get("manual_override_time"):
             self._override_state[entity_id]["manual_override_time"] = None
             self._notify()
