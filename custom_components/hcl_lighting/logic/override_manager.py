"""State management for manual overrides."""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import NamedTuple

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State
from homeassistant.util import dt as dt_util

from ..const import (
    OVERRIDE_BRIGHTNESS_DELTA,
    OVERRIDE_KELVIN_DELTA,
    OVERRIDE_TIMEOUT_HOURS,
    TRAJECTORY_BRIGHTNESS_DELTA,
    UNREACHABLE_GRACE_SECONDS,
    XY_COLOR_DISTANCE_THRESHOLD,
)
from .units import brightness_pct, kelvin_to_xy, on_brightness, xy_distance

_LOGGER = logging.getLogger(__name__)

UNREACHABLE_STATES = (STATE_UNAVAILABLE, STATE_UNKNOWN)


class CommandStart(NamedTuple):
    """Values of a light when HCL sent its last command (RM-B33)."""

    brightness: int | None  # percent
    kelvin: int | None
    xy: tuple[float, float] | None


class Tracking(NamedTuple):
    """What an HCL command changes in the tracking of a light; restored when the
    command was not sent or failed (RM-B14, RM-B45)."""

    last_set: tuple[int, int] | None  # (brightness %, kelvin) of the last command
    ignore_until: datetime | None
    command_start: CommandStart | None
    own_report_open: bool


@dataclass(slots=True)
class LightState:
    """Manual-control state of one light (RM-T03)."""

    # values of the last HCL command and the light's values at that moment
    last_set: tuple[int, int] | None = None
    command_start: CommandStart | None = None
    # state reports are not checked until then (the command's transition)
    ignore_until: datetime | None = None
    # a report with HCL's context moved back towards the start values: decided
    # when the transition has ended (RM-B33)
    own_report_open: bool = False
    # manual control since then (None: HCL controls the light)
    manual_since: datetime | None = None
    # while unavailable/unknown (RM-B24)
    unreachable_since: datetime | None = None
    # smooth return to HCL: update cycles leave the light alone until then
    reengage_until: datetime | None = None

    def tracking(self) -> Tracking:
        return Tracking(self.last_set, self.ignore_until, self.command_start, self.own_report_open)

    def restore(self, tracking: Tracking) -> None:
        self.last_set, self.ignore_until, self.command_start, self.own_report_open = tracking


_NO_TRACKING = Tracking(None, None, None, False)


# Verdicts on a reported value compared with an HCL command (RM-B33)
_OWN, _OPEN, _AWAY = 0, 1, 2


def _verdict(curr, target, old, start, tolerance) -> int:
    """Whether a reported value belongs to HCL's command (RM-B33).

    _OWN: at the target, or moving towards it (also a slow ramp of the device).
    _OPEN: back towards the light's value when the command was sent (start).
    A device can report the target at once and then its own values of the
    transition, but a user can dim back as well: it is decided when the
    command's transition has ended (see settle_open_report).
    _AWAY: away from the target, beyond the range between start and target -
    a manual change.
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


class OverrideManager:
    """Manages manual override states for HCL lights."""

    def __init__(self) -> None:
        """Initialize the manager."""
        self._lights: dict[str, LightState] = {}
        # Behaviour (set from the entry options / adapt switches)
        self.timeout: timedelta | None = timedelta(hours=OVERRIDE_TIMEOUT_HOURS)
        self.reset_on_off = True
        self.track_brightness = True
        self.track_color = True
        # Called whenever the set of manually controlled lights changes
        self.on_change: Callable[[], None] | None = None

    def _notify(self) -> None:
        if self.on_change:
            self.on_change()

    def _light(self, entity_id: str) -> LightState:
        return self._lights.setdefault(entity_id, LightState())

    # ------------------------------------------------------------ manual control
    def _start_manual(
        self, entity_id: str, light: LightState, why: str, reasons: Iterable[str] = (),
        since: datetime | None = None,
    ) -> None:
        """The light is manually controlled from now (or since) on."""
        details = ", ".join(reasons)
        _LOGGER.debug("Manual Override detected for %s (%s)%s", entity_id, why, f": {details}" if details else "")
        light.manual_since = since or dt_util.now()
        light.reengage_until = None
        light.own_report_open = False
        self._notify()

    def _end_manual(self, entity_id: str, light: LightState, why: str, notify: bool = True) -> None:
        """The light follows HCL again."""
        _LOGGER.debug("Override reset for %s (%s)", entity_id, why)
        light.manual_since = None
        if notify:
            self._notify()

    def set_override(self, entity_id: str, since: datetime | None = None) -> None:
        """Mark a light as manually controlled (action, command of a user, Sleep).

        HCL leaves the light alone until it is turned off (if configured) or
        the override timeout expires.
        """
        self._start_manual(entity_id, self._light(entity_id), "set", since=since)

    def reset_override(self, entity_id: str) -> None:
        """Hand a manually controlled light back to HCL."""
        light = self._lights.get(entity_id)
        if light is not None and light.manual_since is not None:
            self._end_manual(entity_id, light, "released")

    def overridden_entities(self) -> list[str]:
        """Return the lights that are currently under manual control."""
        return sorted(eid for eid, light in self._lights.items() if light.manual_since is not None)

    def is_overridden(self, entity_id: str) -> bool:
        """Check if a light is currently in manual override."""
        light = self._lights.get(entity_id)
        return light is not None and light.manual_since is not None

    def export_overrides(self) -> dict[str, str]:
        """Serializable manual-control state ({entity_id: ISO timestamp})."""
        return {
            eid: light.manual_since.isoformat()
            for eid, light in self._lights.items()
            if light.manual_since is not None
        }

    def import_overrides(self, stored: dict[str, str]) -> None:
        """Restore manual-control state exported by export_overrides."""
        for eid, iso in (stored or {}).items():
            when = dt_util.parse_datetime(iso) if isinstance(iso, str) else None
            if when is not None:
                self._light(eid).manual_since = when

    def pop_expired_overrides(self) -> list[str]:
        """End the manual control whose timeout has expired; returns these lights
        (they return to HCL with a smooth transition)."""
        if self.timeout is None:
            return []
        now = dt_util.now()
        expired = [
            eid for eid, light in self._lights.items()
            if light.manual_since is not None and now - light.manual_since > self.timeout
        ]
        for eid in expired:
            self._end_manual(eid, self._lights[eid], "timeout expired", notify=False)
        if expired:
            self._notify()
        return expired

    # ------------------------------------------------------------ tracking of HCL commands
    def set_ignore_window(self, entity_id: str, seconds: float) -> None:
        """Set a window where state changes are ignored (to prevent self-detection)."""
        self._light(entity_id).ignore_until = dt_util.now() + timedelta(seconds=float(seconds) + 2)  # 2 s buffer

    def set_last_set_values(
        self, entity_id: str, brightness: int, kelvin: int, start: State | None = None
    ) -> None:
        """Update the last known HCL values applied to the light.

        start: state of the light when the command is sent; its values are the
        other end of the command's transition (RM-B33).
        """
        light = self._light(entity_id)
        light.last_set = (brightness, kelvin)
        light.own_report_open = False
        if start is not None and start.state == "on":
            attrs = start.attributes
            light.command_start = CommandStart(
                brightness_pct(on_brightness(attrs)), attrs.get("color_temp_kelvin"), attrs.get("xy_color")
            )
        else:
            light.command_start = None

    def last_set(self, entity_id: str) -> tuple[int, int] | None:
        """Values of the last HCL command to the light (brightness, kelvin)."""
        light = self._lights.get(entity_id)
        return light.last_set if light else None

    def tracking_snapshot(self, entity_id: str) -> Tracking:
        """Tracking values a command changes (last values, ignore window, start values, open report)."""
        light = self._lights.get(entity_id)
        return light.tracking() if light else _NO_TRACKING

    def restore_tracking(self, entity_id: str, snapshot: Tracking) -> None:
        """Undo the tracking of a command that was not sent or failed.

        The light never got the values: neither the values nor the ignore
        window of that command may be used by the manual-control detection.
        """
        light = self._lights.get(entity_id)
        if light is not None:
            light.restore(snapshot)

    def prune_stale_entities(self, valid_entity_ids: set[str]) -> None:
        """Remove override tracking for entities no longer in target list."""
        stale = [eid for eid in self._lights if eid not in valid_entity_ids]
        was_overridden = any(self.is_overridden(eid) for eid in stale)
        for eid in stale:
            del self._lights[eid]
        if stale:
            _LOGGER.debug("Pruned %d stale entities from OverrideManager", len(stale))
        if was_overridden:
            self._notify()

    # ------------------------------------------------------------ detection
    def _verdicts(
        self, last: tuple[int, int], start: CommandStart | None, state: State, old_state: State | None
    ) -> list[tuple[str, int]]:
        """(description, verdict) of the adapted attributes of a report."""
        last_b, last_k = last
        start = start or CommandStart(None, None, None)
        old = old_state.attributes if old_state is not None and old_state.state == "on" else {}
        attrs = state.attributes
        out = []
        if self.track_brightness and last_b is not None:
            # "on" with brightness 0 carries no brightness information (RM-B41)
            curr_b = brightness_pct(on_brightness(attrs))
            out.append((
                f"Brightness (L:{last_b}%->C:{curr_b}%)",
                _verdict(curr_b, last_b, brightness_pct(on_brightness(old)), start.brightness, TRAJECTORY_BRIGHTNESS_DELTA),
            ))
        if self.track_color and last_k:
            curr_k = attrs.get("color_temp_kelvin")
            if curr_k is not None:
                out.append((
                    f"Kelvin (L:{last_k}K->C:{curr_k}K)",
                    _verdict(curr_k, last_k, old.get("color_temp_kelvin"), start.kelvin, OVERRIDE_KELVIN_DELTA),
                ))
            else:
                # Colour lights (XY simulation): distance to the HCL colour
                expected = kelvin_to_xy(last_k)
                dist = xy_distance(attrs.get("xy_color"), expected)
                if dist is not None:
                    out.append((
                        f"XY Color (d:{dist:.3f})",
                        _verdict(
                            dist, 0.0, xy_distance(old.get("xy_color"), expected),
                            xy_distance(start.xy, expected), XY_COLOR_DISTANCE_THRESHOLD,
                        ),
                    ))
        return out

    def _deviations(self, last: tuple[int, int], state: State) -> list[str]:
        """Reasons why a report (without HCL's context) is manual control: its
        values differ from the HCL values by more than the thresholds."""
        last_b, last_k = last
        attrs = state.attributes
        curr_b = brightness_pct(on_brightness(attrs))
        curr_k = attrs.get("color_temp_kelvin")
        reasons = []
        delta_b = abs(curr_b - last_b)
        if self.track_brightness and delta_b > OVERRIDE_BRIGHTNESS_DELTA:
            reasons.append(f"Brightness (L:{last_b}%->C:{curr_b}%, d:{delta_b}%)")
        delta_k = abs(curr_k - last_k) if curr_k and last_k else 0
        if self.track_color and delta_k > OVERRIDE_KELVIN_DELTA:
            reasons.append(f"Kelvin (L:{last_k}K->C:{curr_k}K, d:{delta_k}K)")
        # XY colour (lights without colour temperature, or a colour change);
        # 0.05 covers significant changes while ignoring minor gamut drifts
        if not reasons and self.track_color and last_k:
            dist = xy_distance(attrs.get("xy_color"), kelvin_to_xy(last_k))
            if dist is not None and dist > XY_COLOR_DISTANCE_THRESHOLD:
                reasons.append(f"XY Color (d:{dist:.3f})")
        return reasons

    def check_override(
        self, entity_id: str, state: State | None, last_set_values: tuple[int, int] | None,
        old_state: State | None = None,
    ) -> bool:
        """Check a state report without HCL's context; True if the light is now
        manually controlled.

        last_set_values: the current HCL values, used if HCL has not sent a
        command to the light yet.
        """
        if not state:
            return False
        light = self._light(entity_id)
        now = dt_util.now()

        # 0. Unavailable/unknown says nothing about the light: it is not
        # switched off and keeps its manual control (RM-B24). When it reports
        # again, light_returned() decides by the length of the gap.
        if state.state in UNREACHABLE_STATES:
            if light.unreachable_since is None:
                light.unreachable_since = now
            return False

        reference = light.last_set or last_set_values

        # 1. Ignore window of the last command (lights that are on; switching
        # off is never an HCL value and goes to step 2, RM-D03): only a change
        # away from the HCL value is checked (same rule as RM-B33)
        if light.ignore_until and now < light.ignore_until and state.state == "on":
            if not self._moved_away(entity_id, reference, state, old_state):
                _LOGGER.debug("Ignoring event for %s (Window active until %s)", entity_id, light.ignore_until)
                return False

        # 2. Switched off
        light.unreachable_since = None
        if state.state != "on":
            light.own_report_open = False
            # Switching a light off ends its manual control (configurable)
            if self.reset_on_off and light.manual_since is not None:
                self._end_manual(entity_id, light, "turned off")
            return False

        # 3. Compare with the values HCL sent last
        if not reference or len(reference) != 2 or None in reference:
            return False  # no reference values yet (startup)
        if on_brightness(state.attributes) is None:
            # also "on" with brightness 0 (RM-B41)
            _LOGGER.debug("Ignoring event for %s (no brightness reported)", entity_id)
            return False
        reasons = self._deviations(reference, state)
        if reasons:
            self._start_manual(entity_id, light, "differs from the HCL value", reasons)
            return True
        return False

    def _moved_away(
        self, entity_id: str, reference: tuple[int, int] | None, state: State, old_state: State | None
    ) -> bool:
        """A report inside the ignore window that moved away from the HCL value."""
        if old_state is None or old_state.state != "on" or not reference or reference[0] is None:
            return False
        away = [text for text, verdict in self._verdicts(reference, None, state, old_state) if verdict == _AWAY]
        if away:
            _LOGGER.debug(
                "Change away from the HCL value inside the ignore window for %s (%s): "
                "checking for manual control", entity_id, ", ".join(away),
            )
        return bool(away)

    def check_own_report(self, entity_id: str, state: State | None, old_state: State | None = None) -> bool:
        """Check a state report that carries the context of an HCL command (RM-B33).

        Home Assistant gives the state changes of a light the context of the
        last command for 5 seconds, also a change made on the device (e.g. a
        KNX wall dimmer right after switching on). Reports of HCL's command
        reach its values: they are at the target or move towards it. A report
        beyond the range between the light's value at the command and the
        target is a manual change. A report back towards the light's value at
        the command can be either; it is decided when the transition has
        ended (settle_open_report). Returns True if the light is now manually
        controlled.
        """
        light = self._lights.get(entity_id)
        if light is None or light.manual_since is not None or not light.last_set:
            return False
        if state is None or state.state != "on":
            light.own_report_open = False
            return False
        verdicts = self._verdicts(light.last_set, light.command_start, state, old_state)
        reasons = [text for text, verdict in verdicts if verdict == _AWAY]
        if reasons:
            self._start_manual(entity_id, light, "change on the device within 5 s after an HCL command", reasons)
            return True
        if any(verdict == _OPEN for _text, verdict in verdicts):
            _LOGGER.debug(
                "Report of %s with HCL's context moved back towards the value before the command; "
                "decided when the transition has ended", entity_id,
            )
            light.own_report_open = True
        elif all(ok for _text, ok in self._at_target(light.last_set, state)):
            light.own_report_open = False
        return False

    def _at_target(self, last: tuple[int, int], state: State) -> list[tuple[str, bool]]:
        """Per adapted attribute: (description, whether the light is at the HCL value)."""
        last_b, last_k = last
        attrs = state.attributes
        out = []
        curr_b = brightness_pct(on_brightness(attrs))
        if self.track_brightness and last_b is not None and curr_b is not None:
            out.append((f"Brightness (L:{last_b}%->C:{curr_b}%)", abs(curr_b - last_b) <= TRAJECTORY_BRIGHTNESS_DELTA))
        if self.track_color and last_k:
            curr_k = attrs.get("color_temp_kelvin")
            if curr_k is not None:
                out.append((f"Kelvin (L:{last_k}K->C:{curr_k}K)", abs(curr_k - last_k) <= OVERRIDE_KELVIN_DELTA))
            else:
                dist = xy_distance(attrs.get("xy_color"), kelvin_to_xy(last_k))
                if dist is not None:
                    out.append((f"XY Color (d:{dist:.3f})", dist <= XY_COLOR_DISTANCE_THRESHOLD))
        return out

    def settle_open_report(self, entity_id: str, state: State | None) -> bool:
        """Decide an open report with HCL's context (RM-B33); True: leave the light alone.

        While the transition of the command runs the light is left alone (its
        values are still on the way). Afterwards a light that stayed away
        from the HCL value was changed on the device: manual control.
        """
        light = self._lights.get(entity_id)
        if light is None or not light.own_report_open:
            return False
        if state is None or state.state != "on" or not light.last_set:
            light.own_report_open = False
            return False
        if light.ignore_until is not None and dt_util.now() < light.ignore_until:
            return True
        reasons = [text for text, ok in self._at_target(light.last_set, state) if not ok]
        if not reasons:
            light.own_report_open = False
            return False
        self._start_manual(
            entity_id, light, "stayed away from the HCL value after a report with HCL's context", reasons
        )
        return True

    def light_returned(self, entity_id: str, old_state: State | None) -> None:
        """A light reports again after being unavailable/unknown (RM-B24).

        A short gap (HA restart, bridge or broker restart, radio dropout)
        keeps its manual control. A longer gap counts like switching off
        (e.g. a lamp without power at the wall switch comes back with its
        power-on values), if manual control ends when a light is switched off.
        """
        light = self._lights.get(entity_id)
        if light is None:
            return
        since, light.unreachable_since = light.unreachable_since, None
        if since is None and old_state is not None and old_state.state in UNREACHABLE_STATES:
            since = old_state.last_changed  # gap started before HCL listened
        if since is None or light.manual_since is None:
            return
        gap = dt_util.now() - since
        if self.reset_on_off and gap > timedelta(seconds=UNREACHABLE_GRACE_SECONDS):
            self._end_manual(entity_id, light, f"not reachable for {gap}")
        else:
            _LOGGER.debug("Manual control of %s kept (not reachable for %s)", entity_id, gap)

    # ------------------------------------------------------------ smooth return
    def set_reengaging(self, entity_id: str, seconds: float) -> None:
        """Protect a light that is returning to HCL with a smooth transition.

        Normal update cycles leave it alone until the transition has ended.
        """
        self._light(entity_id).reengage_until = dt_util.now() + timedelta(seconds=float(seconds))

    def is_reengaging(self, entity_id: str) -> bool:
        """Whether a light is still in its smooth return to HCL."""
        light = self._lights.get(entity_id)
        if light is None or light.reengage_until is None:
            return False
        if dt_util.now() < light.reengage_until:
            return True
        light.reengage_until = None
        return False

    def end_reengaging(self, entity_id: str | None = None) -> None:
        """End the smooth return of one light (or of all lights)."""
        lights = [self._lights.get(entity_id)] if entity_id else list(self._lights.values())
        for light in lights:
            if light is not None:
                light.reengage_until = None
