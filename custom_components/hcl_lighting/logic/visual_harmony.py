"""Visual Harmony (RM-E04, spec VH v1.4): colour temperature modifier.

When the daylight compensation has lowered the brightness far below the base
(curve), the cool colour temperature of the curve is softly limited towards a
warmer value, so that the little electric light left fits the room. Only the
own correction (delta in mired) is smoothed and rate limited; the base follows
at once (VH-PRD-04) and the result is never cooler than the base (VH-PRD-03).
A comfort heuristic, not a standard or health function. The outdoor light
state of the Daylight Estimator (RM-E03) refines the influence.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from ..const import (
    CONF_HARMONY_PROFILE,
    CONF_HARMONY_WEATHER,
    HARMONY_PROFILES,
    MODE_AUTO,
)
from .daylight_compensation import DaylightConfig
from .daylight_estimator import (
    BRIGHT_OVERCAST,
    CLEAR_DIRECT,
    DARK_OVERCAST,
    FOG_LOW_CONTRAST,
    LOW_SUN_DIRECT,
    MIXED_VARIABLE,
    NIGHT,
    OUTDOOR_KEY,
    PRECIPITATION_DARK,
    TWILIGHT,
    OutdoorLightState,
)
from .environmental_controller import (
    STATUS_ACTIVE,
    STATUS_BYPASSED,
    STATUS_HOLD,
    EnvironmentalContext,
    EnvironmentalStateSnapshot,
    HCLSetpoint,
    ModifierSnapshot,
    StepTime,
)

HARMONY_KEY = "harmony"

# Strength per profile (VH §9); beta values until the field test (VH-PRD-10)
_STRENGTH = {"balanced": 0.8, "strong": 1.0}
NEUTRAL_WEIGHT = 0.75  # without estimator, and for UNKNOWN_DAYLIGHT (VH §9/§16)
# Relative envelope (VH §8): relative output -> colour temperature cap (K);
# at 0.90 and above no cap (the base). Interpolated in mired.
_ENVELOPE = ((0.15, 4000.0), (0.30, 4500.0), (0.50, 5000.0), (0.75, 5500.0))
_ENVELOPE_END = 0.90
# Character weight and envelope offset in mired (VH §10)
_CHARACTER = {
    CLEAR_DIRECT: (1.00, 0.0),
    MIXED_VARIABLE: (0.90, 0.0),
    BRIGHT_OVERCAST: (0.90, -8.0),
    DARK_OVERCAST: (0.75, 0.0),
    LOW_SUN_DIRECT: (0.70, 15.0),
    TWILIGHT: (0.45, 15.0),
    FOG_LOW_CONTRAST: (0.65, 5.0),
    PRECIPITATION_DARK: (0.60, 5.0),
    NIGHT: (0.0, 0.0),
}
SMOOTHING_S = 180.0  # time constant of the correction (VH §11)
TIGHTEN_RATE = 5.0  # mired/min towards a warmer correction (VH-PRD-13)
RELEASE_RATE = 10.0  # mired/min back towards the base
_MIRED_MIN = 1_000_000 / 7000.0  # colour temperature range of the options (2000-7000 K)
_MIRED_MAX = 1_000_000 / 2000.0
DISABLED = "disabled"  # handover marker: the feature was off before a reload


@dataclass(frozen=True, slots=True)
class HarmonyConfig:
    """Options of Visual Harmony (only together with the daylight compensation, VH-PRD-01)."""

    profile: str
    weather_entity: str | None

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> HarmonyConfig | None:
        profile = options.get(CONF_HARMONY_PROFILE)
        if profile not in HARMONY_PROFILES or profile == "off" or DaylightConfig.from_options(options) is None:
            return None
        return cls(profile=profile, weather_entity=options.get(CONF_HARMONY_WEATHER) or None)


@dataclass(frozen=True, slots=True)
class HarmonyState:
    """delta_mired: the correction in effect; None: seed with the raw value at
    the next evaluation (start). from_scenario: the last evaluation was a
    scenario (the return to Auto starts with the raw value, VH §12)."""

    delta_mired: float | None = None
    from_scenario: bool = False


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def smoothstep(edge0: float, edge1: float, x: float) -> float:
    t = _clamp((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def envelope_mired(relative_output: float, base_mired: float) -> float:
    """Cap of the relative envelope in mired (VH §8), continuous; the base at
    0.90 and above."""
    points = [(r, 1_000_000 / k) for r, k in _ENVELOPE] + [(_ENVELOPE_END, base_mired)]
    if relative_output <= points[0][0]:
        return points[0][1]
    for (r0, m0), (r1, m1) in zip(points, points[1:]):
        if relative_output <= r1:
            return _lerp(m0, m1, (relative_output - r0) / (r1 - r0))
    return base_mired


def daylight_weight(outdoor: OutdoorLightState | None) -> tuple[float, float]:
    """Weight of the influence and the envelope offset (mired), blended with the
    confidence of the estimator (VH-PRD-09, E04-14 variant A)."""
    if outdoor is None:
        return NEUTRAL_WEIGHT, 0.0
    weight, offset = _CHARACTER.get(outdoor.daylight_character, (NEUTRAL_WEIGHT, 0.0))
    c = _clamp(outdoor.confidence, 0.0, 1.0)
    return _lerp(NEUTRAL_WEIGHT, weight, c), offset * c


def raw_delta(
    base_brightness: float, effective_brightness: float, base_kelvin: float, profile: str,
    outdoor: OutdoorLightState | None,
) -> tuple[float, dict[str, Any]]:
    """Target correction in mired (VH §7-§11) and its diagnosis."""
    reduction = 0.0 if base_brightness <= 0 else _clamp(1.0 - effective_brightness / base_brightness, 0.0, 1.0)
    weight, offset = daylight_weight(outdoor)
    influence = _clamp(_STRENGTH[profile] * smoothstep(0.15, 0.70, reduction) * weight, 0.0, 1.0)
    base_mired = 1_000_000 / base_kelvin
    cap = _clamp(envelope_mired(1.0 - reduction, base_mired) + offset, _MIRED_MIN, _MIRED_MAX)
    target = max(base_mired, _lerp(base_mired, cap, influence))
    return max(0.0, target - base_mired), {
        "reduction_ratio": round(reduction, 3),
        "influence": round(influence, 3),
    }


class VisualHarmonyModifier:
    """Colour temperature modifier after the daylight compensation (VH §11-§12)."""

    key = HARMONY_KEY

    def __init__(self, config: HarmonyConfig, handover: float | str | None = None) -> None:
        """handover: the correction of the setup before a reload (O17 = C, E04-17):
        a value continues it (also with changed parameters, rate limited to the
        new target), DISABLED (the feature was off) starts at 0, None (start of
        Home Assistant) seeds the raw value (VH-PRD-11/-15)."""
        self.config = config
        self._initial = 0.0 if handover == DISABLED else handover

    def initial_state(self) -> HarmonyState:
        return HarmonyState(delta_mired=self._initial)

    def evaluate(
        self,
        state: HarmonyState,
        ctx: EnvironmentalContext,
        current: HCLSetpoint,
        providers: Mapping[str, EnvironmentalStateSnapshot],
        time: StepTime,
    ) -> tuple[HCLSetpoint, ModifierSnapshot, HarmonyState]:
        snapshot = providers.get(OUTDOOR_KEY)
        outdoor: OutdoorLightState | None = snapshot.payload if snapshot is not None else None
        details: dict[str, Any] = {
            "daylight_character": None if outdoor is None else outdoor.daylight_character,
            "outdoor_quality": None if outdoor is None else outdoor.quality_level,
            "outdoor_confidence": None if outdoor is None else outdoor.confidence,
        }

        def done(status: str, reason: str, delta: float | None, final: HarmonyState):
            after = current
            if delta and current.kelvin:
                after = replace(current, kelvin=1_000_000 / (1_000_000 / current.kelvin + delta))
            details["delta_mired"] = None if delta is None else round(delta, 1)
            return after, ModifierSnapshot(self.key, status, reason, current, after, details), final

        base = ctx.base
        if base is None or base.brightness is None or current.brightness is None or not current.kelvin:
            return done(STATUS_BYPASSED, "harmony_no_setpoint", None, state)
        # Only in Auto (VH-PRD-02): the correction is not advanced in a scenario
        if ctx.mode != MODE_AUTO:
            return done(STATUS_BYPASSED, "harmony_scenario_bypass", None, replace(state, from_scenario=True))
        if not ctx.hcl_active:
            # no step while HCL is off; peek shows the correction in effect
            return done(STATUS_HOLD, "harmony_controller_paused", state.delta_mired, state)
        if not ctx.adapt_brightness:
            # the actual brightness is unknown (VH-PRD-05): the base, and the
            # correction builds up again from 0 when it is back (no windup)
            return done(STATUS_BYPASSED, "harmony_bypass_adapt_brightness_off", None, HarmonyState(0.0))
        if not ctx.adapt_color:
            # no colour temperature is sent; the correction is held (VH-PRD-06)
            return done(STATUS_HOLD, "harmony_hold_adapt_color_off", state.delta_mired, state)

        raw, info = raw_delta(base.brightness, current.brightness, current.kelvin, self.config.profile, outdoor)
        night = outdoor is not None and outdoor.daylight_character == NIGHT
        if night:
            raw = 0.0  # no harmony at night (VH §10); an earlier correction is released
        details.update(info)
        details["raw_delta_mired"] = round(raw, 1)
        if state.delta_mired is None or state.from_scenario:
            previous = raw  # start or return to Auto: no cold start, no lag (VH §12)
        else:
            previous = state.delta_mired
        alpha = 0.0 if time.dt_real <= 0 else 1.0 - math.exp(-time.dt_real / SMOOTHING_S)
        filtered = previous + alpha * (raw - previous)
        limit = (RELEASE_RATE if raw < previous else TIGHTEN_RATE) * time.dt_control / 60.0
        delta = max(0.0, previous + _clamp(filtered - previous, -limit, limit))
        if abs(raw - delta) < 0.05:
            delta = raw  # the filter approaches the target only asymptotically
        if night:
            reason = "harmony_night"
        elif delta > 0:
            reason = "harmony_warming"
        else:
            reason = "harmony_no_reduction"
        return done(STATUS_ACTIVE, reason, delta, HarmonyState(delta_mired=delta))
