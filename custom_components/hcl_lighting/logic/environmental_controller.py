"""Environmental Controller (RM-E01, spec EC v1.5).

The only layer that derives the effective setpoint from the base setpoint
(curve or scenario). State providers describe the environment (e.g. an indoor
lux sensor); modifiers change exactly their own setpoint dimension (e.g. the
daylight compensation lowers the brightness).

Life cycle (EC-PRD-03/04/05): stateful providers and modifiers are advanced
only by step(), once per regular update cycle under the update lock. All other
readers (target sensors, diagnostics, apply, Fast-HCL when a light is switched
on) use peek(): the current base with the state of the last step - nothing is
advanced (pure evaluate(), the next state is discarded).

Time (EC-PRD-06/07, EC-PRD-27): rates are per time; changes of a cap or an
integrator use dt_control = min(dt_real, 60 s), filters the real dt. While HCL
is off there is no step(); the first step afterwards is limited the same way.
"""
from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, Protocol, TypeVar

_LOGGER = logging.getLogger(__name__)

MAX_CONTROL_DT = 60.0  # s, product rule (EC-PRD-07)

# Status of the controller and of its parts (EC-PRD-23)
STATUS_DISABLED = "disabled"
STATUS_ACTIVE = "active"
STATUS_BYPASSED = "bypassed"
STATUS_HOLD = "hold"
STATUS_DEGRADED = "degraded"
STATUS_FALLBACK = "fallback"
# Priority of the global status by effect (EC §20): the first that applies
_STATUS_PRIORITY = (STATUS_FALLBACK, STATUS_DEGRADED, STATUS_ACTIVE, STATUS_HOLD, STATUS_BYPASSED)

T = TypeVar("T")
S = TypeVar("S")


@dataclass(frozen=True, slots=True)
class HCLSetpoint:
    """Brightness (%) and colour temperature (K); None: not set (Guest)."""

    brightness: float | None
    kelvin: float | None


@dataclass(frozen=True, slots=True)
class StepTime:
    """Time of an evaluation. peek(): dt_real = dt_control = 0."""

    now: datetime
    monotonic: float
    dt_real: float
    dt_control: float
    committing: bool  # step() (True) or peek() (False)


@dataclass(frozen=True, slots=True)
class EnvironmentalContext:
    """What the modifiers may know about the instance (EC §17).

    The light counts and the seed are only known in a regular cycle (step());
    peek() leaves them None.
    """

    mode: str
    hcl_active: bool
    adapt_brightness: bool
    adapt_color: bool
    update_interval: float
    min_brightness: int
    max_brightness: int
    lights_on: int | None = None
    lights_controlled: int | None = None  # on and following HCL
    lights_manual: int | None = None  # on and manually controlled or returning
    # mean brightness (%) of the lights that are on, follow HCL and were set
    # last by the Auto path (start seed of the daylight cap, DL §11)
    seed_brightness: float | None = None


@dataclass(frozen=True, slots=True)
class EnvironmentalStateSnapshot(Generic[T]):
    """What a state provider reports (immutable)."""

    key: str
    status: str
    quality: str
    confidence: float | None
    payload: T | None
    reason: str


@dataclass(frozen=True, slots=True)
class ModifierSnapshot:
    """What a modifier did in an evaluation (EC §9, E01-16)."""

    key: str
    status: str
    reason: str
    before: HCLSetpoint
    after: HCLSetpoint
    details: Mapping[str, Any] = field(default_factory=dict)  # feature-specific diagnosis


@dataclass(frozen=True, slots=True)
class EnvironmentalResult:
    """One consistent snapshot: base, providers, modifiers, effective setpoint."""

    base: HCLSetpoint
    effective: HCLSetpoint
    status: str
    reason: str  # primary reason (UI)
    reason_codes: tuple[str, ...]  # all reasons in pipeline order
    hold: bool
    providers: tuple[EnvironmentalStateSnapshot, ...]
    modifiers: tuple[ModifierSnapshot, ...]
    evaluated_at: datetime

    def modifier(self, key: str) -> ModifierSnapshot | None:
        return next((m for m in self.modifiers if m.key == key), None)


class EnvironmentalStateProvider(Protocol[S, T]):
    """Pure provider: evaluate() returns the snapshot and the next state;
    step() commits the state, peek() discards it (EC-PRD-29)."""

    key: str

    def initial_state(self) -> S: ...

    def evaluate(
        self, state: S, ctx: EnvironmentalContext, time: StepTime
    ) -> tuple[EnvironmentalStateSnapshot[T], S]: ...


class EnvironmentalModifier(Protocol[S]):
    """Pure modifier of one setpoint dimension (EC-PRD-19); the return order
    is the same as for providers: result first, next state second (E01-20)."""

    key: str

    def initial_state(self) -> S: ...

    def evaluate(
        self,
        state: S,
        ctx: EnvironmentalContext,
        current: HCLSetpoint,
        providers: Mapping[str, EnvironmentalStateSnapshot],
        time: StepTime,
    ) -> tuple[HCLSetpoint, ModifierSnapshot, S]: ...


def _valid(value: float | None, low: float, high: float) -> bool:
    return value is None or (isinstance(value, (int, float)) and math.isfinite(value) and low <= value <= high)


def _published(base: HCLSetpoint, effective: HCLSetpoint) -> HCLSetpoint:
    """Round once for publication (EC-PRD-26): whole percent, 10-K steps. A
    dimension no modifier changed keeps the base value (disabled parity)."""
    brightness = effective.brightness
    if brightness is not None and brightness != base.brightness:
        brightness = int(round(brightness))
    kelvin = effective.kelvin
    if kelvin is not None and kelvin != base.kelvin:
        kelvin = int(round(kelvin / 10.0) * 10)
    return HCLSetpoint(brightness, kelvin)


class EnvironmentalController:
    """Pipeline base -> providers -> modifiers -> effective of one entry (EC-PRD-24)."""

    def __init__(
        self,
        providers: Sequence[EnvironmentalStateProvider] = (),
        modifiers: Sequence[EnvironmentalModifier] = (),
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._providers = tuple(providers)
        self._modifiers = tuple(modifiers)
        # looked up at call time (a test may replace time.monotonic)
        self._clock = clock or (lambda: time.monotonic())
        self._states: dict[str, Any] = {p.key: p.initial_state() for p in self._providers}
        self._states.update({m.key: m.initial_state() for m in self._modifiers})
        self._last_step: float | None = None
        self.last_result: EnvironmentalResult | None = None
        # debounced status changes for the log (EC-PRD-25)
        self._reported_status: str | None = None
        self._pending_status: str | None = None
        self._failing: set[str] = set()

    @property
    def enabled(self) -> bool:
        """Whether any environmental feature is configured."""
        return bool(self._modifiers)

    def state(self, key: str) -> Any:
        """Committed state of a provider or modifier (diagnosis, persistence, tests)."""
        return self._states.get(key)

    def step(self, now: datetime, base: HCLSetpoint, ctx: EnvironmentalContext) -> EnvironmentalResult:
        """Advance the providers and modifiers once (regular cycle, under the lock)."""
        mono = self._clock()
        dt_real = 0.0 if self._last_step is None else max(0.0, mono - self._last_step)
        self._last_step = mono
        result, states = self._evaluate(
            base, ctx, StepTime(now, mono, dt_real, min(dt_real, MAX_CONTROL_DT), True)
        )
        self._states = states
        self.last_result = result
        self._log_status(result)
        return result

    def peek(self, now: datetime, base: HCLSetpoint, ctx: EnvironmentalContext) -> EnvironmentalResult:
        """Effective setpoint for the current base and the last committed state;
        changes nothing (EC-PRD-04)."""
        result, _states = self._evaluate(base, ctx, StepTime(now, self._clock(), 0.0, 0.0, False))
        return result

    def _evaluate(
        self, base: HCLSetpoint, ctx: EnvironmentalContext, step_time: StepTime
    ) -> tuple[EnvironmentalResult, dict[str, Any]]:
        if not self._modifiers:
            return EnvironmentalResult(
                base, base, STATUS_DISABLED, "environment_disabled", (), False, (), (), step_time.now
            ), self._states
        states = dict(self._states)
        snapshots: list[EnvironmentalStateSnapshot] = []
        for provider in self._providers:
            try:
                snapshot, states[provider.key] = provider.evaluate(states[provider.key], ctx, step_time)
            except Exception:  # noqa: BLE001 - a broken provider must not stop the lights (EC-T11)
                self._report_error(provider.key)
                snapshot = EnvironmentalStateSnapshot(provider.key, STATUS_FALLBACK, "none", None, None, f"{provider.key}_error")
            snapshots.append(snapshot)
        by_key = {s.key: s for s in snapshots}
        current = base
        modifier_snapshots: list[ModifierSnapshot] = []
        for modifier in self._modifiers:
            before = current
            try:
                after, snapshot, next_state = modifier.evaluate(states[modifier.key], ctx, current, by_key, step_time)
                if not (_valid(after.brightness, 0, 100) and _valid(after.kelvin, 1000, 10000)):
                    raise ValueError(f"invalid setpoint {after}")  # EC-PRD-22: no silent clamping
                states[modifier.key] = next_state
                self._failing.discard(modifier.key)
            except Exception:  # noqa: BLE001 - fall back to the setpoint before this modifier (EC-T11)
                self._report_error(modifier.key)
                after = before
                snapshot = ModifierSnapshot(modifier.key, STATUS_FALLBACK, f"{modifier.key}_error", before, before)
            # the next modifier sees this intermediate setpoint (EC-PRD-30)
            current = after
            modifier_snapshots.append(snapshot)
        effective = _published(base, current)
        status, reason, codes = self._aggregate(snapshots, modifier_snapshots)
        return EnvironmentalResult(
            base=base,
            effective=effective,
            status=status,
            reason=reason,
            reason_codes=codes,
            hold=status == STATUS_HOLD,
            providers=tuple(snapshots),
            modifiers=tuple(modifier_snapshots),
            evaluated_at=step_time.now,
        ), states

    @staticmethod
    def _aggregate(
        providers: Sequence[EnvironmentalStateSnapshot], modifiers: Sequence[ModifierSnapshot]
    ) -> tuple[str, str, tuple[str, ...]]:
        """Global status by effect, primary reason and all reasons (EC-PRD-28)."""
        codes = tuple(dict.fromkeys([*(p.reason for p in providers), *(m.reason for m in modifiers)]))
        for status in _STATUS_PRIORITY:
            hit = next((m for m in modifiers if m.status == status), None)
            if hit is not None:
                return status, hit.reason, codes
        return STATUS_DISABLED, "environment_disabled", codes

    def _report_error(self, key: str) -> None:
        if key in self._failing:
            _LOGGER.debug("Environmental %s failed again", key, exc_info=True)
        else:
            self._failing.add(key)
            _LOGGER.warning("Environmental %s failed; using the setpoint without it", key, exc_info=True)

    def _log_status(self, result: EnvironmentalResult) -> None:
        """Log a status change once it holds for two cycles (no entry per cycle)."""
        if result.status == self._reported_status:
            self._pending_status = None
            return
        if self._pending_status != result.status:
            self._pending_status = result.status
            return
        _LOGGER.info(
            "Environment status %s -> %s (%s)", self._reported_status or "-", result.status, ", ".join(result.reason_codes)
        )
        self._reported_status = result.status
        self._pending_status = None

