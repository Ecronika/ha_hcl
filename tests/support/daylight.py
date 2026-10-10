"""Helpers for tests of the environmental controller and the daylight compensation."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from custom_components.hcl_lighting.const import MODE_AUTO
from custom_components.hcl_lighting.logic.daylight_compensation import (
    LUX_KEY,
    DaylightConfig,
    DaylightModifier,
    LuxReading,
)
from custom_components.hcl_lighting.logic.environmental_controller import (
    STATUS_ACTIVE,
    STATUS_DEGRADED,
    EnvironmentalContext,
    EnvironmentalController,
    EnvironmentalStateSnapshot,
    HCLSetpoint,
)

START = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)

LUX_SENSOR = "sensor.lux"
LUX_ATTRS = {"device_class": "illuminance", "unit_of_measurement": "lx", "state_class": "measurement"}


def config(**changes) -> DaylightConfig:
    values = dict(
        sensor=LUX_SENSOR, target_lux=500.0, deadband_lux=25.0, smoothing_s=60.0, response_band_lux=300.0,
        max_rate_pct_per_min=11.0, stale_after_s=3600.0, grace_s=300.0,
    )
    values.update(changes)
    return DaylightConfig(**values)


def daylight_options(**changes) -> dict:
    """Options of an entry with the daylight compensation on."""
    options = {"daylight_enabled": True, "daylight_sensor": LUX_SENSOR, "daylight_target_lux": 500}
    options.update(changes)
    return options


def context(**changes) -> EnvironmentalContext:
    values = dict(
        mode=MODE_AUTO, hcl_active=True, adapt_brightness=True, adapt_color=True, update_interval=27.0,
        min_brightness=3, max_brightness=100, lights_on=1, lights_controlled=1, lights_manual=0,
        seed_brightness=None,
    )
    values.update(changes)
    return EnvironmentalContext(**values)


class FakeLux:
    """Lux provider for unit tests: the reading comes from a function."""

    key = LUX_KEY

    def __init__(self, read: Callable[[], LuxReading]) -> None:
        self.read = read

    def initial_state(self):
        return None

    def evaluate(self, state, ctx, time):
        reading = self.read()
        status = STATUS_ACTIVE if reading.problem is None else STATUS_DEGRADED
        reason = "lux_measured" if reading.problem is None else f"lux_sensor_{reading.problem}"
        return EnvironmentalStateSnapshot(self.key, status, "measured", 1.0, reading, reason), None


@dataclass
class Loop:
    """Environmental controller with the daylight modifier, a fake clock and a
    fake lux sensor (unit tests and room model)."""

    cfg: DaylightConfig = field(default_factory=config)
    lux: float | None = 500.0
    problem: str | None = None
    age: float = 0.0
    seconds: float = 0.0
    persisted: tuple[float | None, datetime | None] = (None, None)

    def __post_init__(self) -> None:
        self.modifier = DaylightModifier(self.cfg, *self.persisted)
        self.env = EnvironmentalController(
            providers=[FakeLux(lambda: LuxReading(self.lux, self.problem, self.age))],
            modifiers=[self.modifier],
            clock=lambda: self.seconds,
        )

    @property
    def now(self) -> datetime:
        return START + timedelta(seconds=self.seconds)

    def step(self, base: float = 80, dt: float = 27, **ctx):
        self.seconds += dt
        return self.env.step(self.now, HCLSetpoint(base, 4000), context(**ctx))

    def peek(self, base: float = 80, **ctx):
        return self.env.peek(self.now, HCLSetpoint(base, 4000), context(**ctx))

    @property
    def state(self):
        return self.env.state("daylight")

    @property
    def cap(self) -> float | None:
        return self.state.cap_pct
