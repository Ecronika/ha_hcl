"""Daylight compensation (RM-E02, spec DL v1.5): measured closed loop.

An indoor lux sensor lowers the brightness in Auto below the curve value when
there is enough daylight: the cap follows the measured (smoothed) illuminance
with a rate in percent points per minute. The effective brightness is never
above the base (curve) and never below the minimum brightness; the colour
temperature is not changed. Only measured mode in 0.8.0 (no feed-forward, no
estimated mode).
"""
from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_DAYLIGHT_DEADBAND_LUX,
    CONF_DAYLIGHT_ENABLED,
    CONF_DAYLIGHT_MAX_RATE,
    CONF_DAYLIGHT_RESPONSE_BAND_LUX,
    CONF_DAYLIGHT_SENSOR,
    CONF_DAYLIGHT_SMOOTHING,
    CONF_DAYLIGHT_STALE_AFTER,
    CONF_DAYLIGHT_TARGET_LUX,
    CONF_DAYLIGHT_UNAVAILABLE_GRACE,
    DEFAULT_DAYLIGHT_MAX_RATE,
    DEFAULT_DAYLIGHT_RESPONSE_BAND_LUX,
    DEFAULT_DAYLIGHT_SMOOTHING,
    DEFAULT_DAYLIGHT_STALE_AFTER,
    DEFAULT_DAYLIGHT_UNAVAILABLE_GRACE,
    DOMAIN,
    MODE_AUTO,
)
from .environmental_controller import (
    STATUS_ACTIVE,
    STATUS_BYPASSED,
    STATUS_DEGRADED,
    STATUS_FALLBACK,
    STATUS_HOLD,
    EnvironmentalContext,
    EnvironmentalStateSnapshot,
    HCLSetpoint,
    ModifierSnapshot,
    StepTime,
)

_LOGGER = logging.getLogger(__name__)

DAYLIGHT_KEY = "daylight"
LUX_KEY = "indoor_lux"
# A persisted cap (or one frozen in a hold or scenario) is used for at most 2 h
# (product value, DL §6); after that the loop starts like after a restart
PERSISTED_CAP_MAX_AGE = 7200.0
PERSIST_DELAY = 300.0  # s, coalesced store writes (DL-PRD-21/22)
STORE_VERSION = 1


@dataclass(frozen=True, slots=True)
class DaylightConfig:
    """Options of the daylight compensation (DL §8)."""

    sensor: str
    target_lux: float
    deadband_lux: float
    smoothing_s: float
    response_band_lux: float
    max_rate_pct_per_min: float
    stale_after_s: float  # 0: no stale check (sensors that report only on change)
    grace_s: float

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> DaylightConfig | None:
        """The configuration, or None if the feature is off or incomplete."""
        if not options.get(CONF_DAYLIGHT_ENABLED):
            return None
        sensor = options.get(CONF_DAYLIGHT_SENSOR)
        target = options.get(CONF_DAYLIGHT_TARGET_LUX)
        if not sensor or not target:
            return None
        target = float(target)
        deadband = options.get(CONF_DAYLIGHT_DEADBAND_LUX)
        return cls(
            sensor=sensor,
            target_lux=target,
            deadband_lux=float(deadband) if deadband else max(20.0, 0.05 * target),
            smoothing_s=float(options.get(CONF_DAYLIGHT_SMOOTHING, DEFAULT_DAYLIGHT_SMOOTHING)),
            response_band_lux=float(options.get(CONF_DAYLIGHT_RESPONSE_BAND_LUX, DEFAULT_DAYLIGHT_RESPONSE_BAND_LUX)),
            max_rate_pct_per_min=float(options.get(CONF_DAYLIGHT_MAX_RATE, DEFAULT_DAYLIGHT_MAX_RATE)),
            stale_after_s=float(options.get(CONF_DAYLIGHT_STALE_AFTER, DEFAULT_DAYLIGHT_STALE_AFTER)),
            grace_s=float(options.get(CONF_DAYLIGHT_UNAVAILABLE_GRACE, DEFAULT_DAYLIGHT_UNAVAILABLE_GRACE)),
        )


# ------------------------------------------------------------------ lux sensor
@dataclass(frozen=True, slots=True)
class LuxReading:
    """A sample of the lux sensor; problem is None for a valid value."""

    lux: float | None
    problem: str | None  # missing | unavailable | unknown | invalid | stale
    age_s: float | None  # since the sensor last reported (State.last_reported)


def read_lux(hass: HomeAssistant, config: DaylightConfig, now: datetime) -> LuxReading:
    """The sensor value: a finite number >= 0 (no conversions, DL §9)."""
    state = hass.states.get(config.sensor)
    if state is None:
        return LuxReading(None, "missing", None)
    reported = getattr(state, "last_reported", None) or state.last_updated
    age = max(0.0, (now - reported).total_seconds())
    if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return LuxReading(None, state.state, age)
    try:
        lux = float(state.state)
    except (TypeError, ValueError):
        return LuxReading(None, "invalid", age)
    if not math.isfinite(lux) or lux < 0:
        return LuxReading(None, "invalid", age)
    if config.stale_after_s > 0 and age > config.stale_after_s:
        return LuxReading(lux, "stale", age)
    return LuxReading(lux, None, age)


class LuxSensorProvider:
    """State provider of the indoor lux sensor (stateless; reading a state is
    no I/O, EC-PRD-16)."""

    key = LUX_KEY

    def __init__(self, hass: HomeAssistant, config: DaylightConfig) -> None:
        self._hass = hass
        self._config = config

    def initial_state(self) -> None:
        return None

    def evaluate(
        self, state: None, ctx: EnvironmentalContext, time: StepTime
    ) -> tuple[EnvironmentalStateSnapshot[LuxReading], None]:
        reading = read_lux(self._hass, self._config, time.now)
        if reading.problem is None:
            snapshot = EnvironmentalStateSnapshot(self.key, STATUS_ACTIVE, "measured", 1.0, reading, "lux_measured")
        else:
            snapshot = EnvironmentalStateSnapshot(
                self.key, STATUS_DEGRADED, "none", None, reading, f"lux_sensor_{reading.problem}"
            )
        return snapshot, None


# ------------------------------------------------------------------ modifier
@dataclass(frozen=True, slots=True)
class DaylightState:
    """State of the daylight loop (DL §10); immutable, replaced by step()."""

    filtered_lux: float | None = None
    last_valid: float | None = None  # monotonic time of the last valid sample
    cap_pct: float | None = None
    invalid_since: float | None = None  # monotonic; also counted during a hold (DL-PRD-24)
    last_auto: float | None = None  # monotonic time of the last regular step without hold/bypass
    persisted_cap: float | None = None  # from the store, used once at the start
    persisted_at: datetime | None = None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class DaylightModifier:
    """Brightness modifier of the measured closed loop (DL §13)."""

    key = DAYLIGHT_KEY

    def __init__(
        self, config: DaylightConfig, persisted_cap: float | None = None, persisted_at: datetime | None = None
    ) -> None:
        self.config = config
        self._persisted = (persisted_cap, persisted_at)

    def initial_state(self) -> DaylightState:
        cap, at = self._persisted
        return DaylightState(persisted_cap=cap, persisted_at=at)

    def evaluate(
        self,
        state: DaylightState,
        ctx: EnvironmentalContext,
        current: HCLSetpoint,
        providers: Mapping[str, EnvironmentalStateSnapshot],
        time: StepTime,
    ) -> tuple[HCLSetpoint, ModifierSnapshot, DaylightState]:
        cfg = self.config
        snapshot = providers.get(LUX_KEY)
        reading: LuxReading = (
            snapshot.payload if snapshot is not None and snapshot.payload is not None
            else LuxReading(None, "missing", None)
        )
        valid = reading.problem is None
        new = self._observe(state, reading, time)
        base = current.brightness
        details: dict[str, Any] = {
            "measured_lux": reading.lux,
            "filtered_lux": None if new.filtered_lux is None else round(new.filtered_lux, 1),
            "target_lux": cfg.target_lux,
            "deadband_lux": cfg.deadband_lux,
            "sensor_age": None if reading.age_s is None else round(reading.age_s),
            "sensor_problem": reading.problem,
        }

        def done(status: str, reason: str, after: HCLSetpoint, final: DaylightState):
            details["cap_pct"] = None if final.cap_pct is None else round(final.cap_pct, 1)
            return after, ModifierSnapshot(self.key, status, reason, current, after, details), final

        # Only in Auto and for a brightness (Guest: none); the cap is frozen (DL §14)
        if base is None or ctx.mode != MODE_AUTO:
            return done(STATUS_BYPASSED, "daylight_scenario_bypass", current, new)
        min_b = ctx.min_brightness
        cap = new.cap_pct
        # A cap frozen for longer than 2 h (long manual control, scenario,
        # HCL off) counts like a start (DL §14, E02-29)
        if cap is not None and new.last_auto is not None and time.monotonic - new.last_auto > PERSISTED_CAP_MAX_AGE:
            cap = None
        start_reason = None
        if cap is None:
            cap, start_reason, new = self._start_cap(new, ctx, base, min_b, time)
        cur = min(cap, base)
        if not ctx.hcl_active:
            # no step while HCL is off (EC-PRD-27); peek shows the frozen value
            return done(STATUS_HOLD, "daylight_controller_paused", replace(current, brightness=cur), new)

        hold = None
        if not ctx.adapt_brightness:
            hold = "daylight_hold_adapt_off"
        elif ctx.lights_on and not ctx.lights_controlled:
            hold = "daylight_hold_manual_control"
        rate = cfg.max_rate_pct_per_min * time.dt_control / 60.0
        invalid_age = None if valid else time.monotonic - (new.invalid_since if new.invalid_since is not None else time.monotonic)
        # 1. Anti-windup first (DL-PRD-09/18): the cap does not move
        if hold:
            status, reason, cap = STATUS_HOLD, hold, cur
        # 2. Temporarily invalid source: grace with the cap held, then softly to the base
        elif not valid and invalid_age <= cfg.grace_s:
            status, reason, cap = STATUS_DEGRADED, f"daylight_sensor_{reading.problem}", cur
        elif not valid:
            status, reason, cap = STATUS_FALLBACK, "daylight_sensor_fallback", min(base, cur + rate)
        else:
            lux = new.filtered_lux
            band = max(1.0, cfg.response_band_lux)
            if lux > cfg.target_lux + cfg.deadband_lux:
                excess = lux - (cfg.target_lux + cfg.deadband_lux)
                cap = max(min_b, cur - rate * min(1.0, excess / band))
                reason = "daylight_reducing"
            elif lux < cfg.target_lux - cfg.deadband_lux and cur < base:
                deficit = (cfg.target_lux - cfg.deadband_lux) - lux
                cap = min(base, cur + rate * min(1.0, deficit / band))
                reason = "daylight_raising"
            else:
                cap = cur
                reason = "daylight_within_deadband" if cur < base else "daylight_at_base"
            if ctx.lights_on == 0:
                reason = "daylight_lights_off_observe"
            status = STATUS_ACTIVE
        if start_reason and status in (STATUS_ACTIVE, STATUS_HOLD):
            details["start"] = start_reason
        effective = min(base, cap)
        new = replace(new, cap_pct=cap, last_auto=new.last_auto if hold else time.monotonic)
        return done(status, reason, replace(current, brightness=effective), new)

    def _observe(self, state: DaylightState, reading: LuxReading, time: StepTime) -> DaylightState:
        """Filter and source health: also during a hold (DL §12, §21)."""
        if reading.problem is not None:
            if state.invalid_since is not None:
                return state
            return replace(state, invalid_since=time.monotonic)
        tau = self.config.smoothing_s
        if (
            state.filtered_lux is None
            or state.last_valid is None
            or time.monotonic - state.last_valid > 3 * tau  # long without a valid sample (E02-30)
        ):
            filtered = reading.lux
        else:
            alpha = 1.0 if tau <= 0 else 1.0 - math.exp(-time.dt_real / tau)
            filtered = state.filtered_lux + alpha * (reading.lux - state.filtered_lux)
        return replace(state, filtered_lux=filtered, last_valid=time.monotonic, invalid_since=None)

    @staticmethod
    def _start_cap(
        state: DaylightState, ctx: EnvironmentalContext, base: float, min_b: float, time: StepTime
    ) -> tuple[float, str, DaylightState]:
        """Cap at the start, after a reload or a long pause (DL §11): a fresh
        persisted cap, else the brightness the Auto path set last (never a
        scenario value, DL-PRD-17), else the base."""
        persisted, persisted_at = state.persisted_cap, state.persisted_at
        state = replace(state, persisted_cap=None, persisted_at=None)  # used once
        if persisted is not None and persisted_at is not None:
            age = (time.now - persisted_at).total_seconds()
            if 0 <= age <= PERSISTED_CAP_MAX_AGE:
                return _clamp(persisted, min_b, base), "daylight_resume", state
        if ctx.seed_brightness is not None:
            return _clamp(ctx.seed_brightness, min_b, base), "daylight_seed", state
        return base, "daylight_seed_fallback", state


# ------------------------------------------------------------------ persistence
class DaylightCapStore:
    """Persisted cap with a timestamp (DL §20): for a jump-free resume after a
    restart or reload, at most 2 h old. Writes are coalesced (DL-PRD-21/22):
    marked on a change of >= 1 percent point or of the status, refreshed at
    least every 300 s in Auto, written with a delay of 300 s and finally when
    Home Assistant stops (Store) or the entry is unloaded."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORE_VERSION, f"{DOMAIN}.daylight.{entry_id}")
        self._payload: dict[str, Any] | None = None
        self._pending = False
        self._cap: float | None = None
        self._status: str | None = None
        self._stamped: datetime | None = None
        self.writes = 0  # scheduled writes (diagnosis, tests)

    async def async_load(self) -> tuple[float | None, datetime | None]:
        data = await self._store.async_load() or {}
        cap, stamp = data.get("cap_pct"), data.get("timestamp")
        at = dt_util.parse_datetime(stamp) if isinstance(stamp, str) else None
        if not isinstance(cap, (int, float)) or at is None:
            return None, None
        self._payload = dict(data)
        self._cap, self._stamped = float(cap), at
        return float(cap), at

    def note(self, state: DaylightState | None, status: str, now: datetime) -> None:
        """After a regular step: mark the cap for writing if it is relevant."""
        if state is None or state.cap_pct is None:
            return
        running = status not in (STATUS_HOLD, STATUS_BYPASSED)
        cap = state.cap_pct
        stamp_due = running and (self._stamped is None or (now - self._stamped).total_seconds() >= PERSIST_DELAY)
        if self._cap is not None and abs(cap - self._cap) < 1.0 and status == self._status and not stamp_due:
            return
        if running:
            self._stamped = now  # the timestamp says when the Auto loop last ran
        self._cap, self._status = cap, status
        self._payload = {
            "cap_pct": round(cap, 2),
            "timestamp": (self._stamped or now).isoformat(),
            "status": status,
        }
        if not self._pending:
            self._pending = True
            self.writes += 1
            self._store.async_delay_save(self._data, PERSIST_DELAY)

    def _data(self) -> dict[str, Any]:
        self._pending = False
        return dict(self._payload or {})

    async def async_flush(self) -> None:
        """Write now (entry unloaded, e.g. before a reload)."""
        if self._payload is not None:
            self._pending = False
            await self._store.async_save(self._data())

    async def async_remove(self) -> None:
        self._payload = None
        await self._store.async_remove()
