"""Environmental controller (RM-E01) and daylight compensation loop (RM-E02):
unit tests with a fake clock, a fake lux sensor and a room model."""
from __future__ import annotations

import logging
import math

import pytest

from custom_components.hcl_lighting.logic.environmental_controller import (
    MAX_CONTROL_DT,
    STATUS_ACTIVE,
    STATUS_BYPASSED,
    STATUS_DEGRADED,
    STATUS_FALLBACK,
    STATUS_HOLD,
    EnvironmentalController,
    HCLSetpoint,
    ModifierSnapshot,
)

from .support.daylight import START, Loop, config, context


# ---------------------------------------------------------------- RM-E01 controller
def test_rm_e01_without_features_the_effective_setpoint_is_the_base():
    """EC-T01: disabled parity."""
    env = EnvironmentalController()
    result = env.step(START, HCLSetpoint(57, 4321), context())
    assert not env.enabled
    assert result.effective == result.base == HCLSetpoint(57, 4321)
    assert result.status == "disabled"


def test_rm_e01_peek_does_not_advance_the_state():
    """EC-T02/T13/T18: 100 peek calls between two steps change no state."""
    loop = Loop(lux=900)
    loop.step()
    loop.step()
    before = loop.state
    for _ in range(100):
        loop.seconds += 1
        loop.peek()
    assert loop.state is before
    assert loop.step().effective.brightness < 80  # the next step goes on


class _Recorder:
    """Second modifier: records what it receives (EC-T19) or fails (EC-T11)."""

    key = "recorder"

    def __init__(self, fail=False, status=STATUS_ACTIVE):
        self.seen = []
        self.fail = fail
        self.status = status

    def initial_state(self):
        return 0

    def evaluate(self, state, ctx, current, providers, time):
        if self.fail:
            raise RuntimeError("broken")
        self.seen.append(current)
        return current, ModifierSnapshot(self.key, self.status, f"recorder_{self.status}", current, current), state + 1


def test_rm_e01_a_later_modifier_sees_the_value_of_the_same_step():
    """EC-T19/EC-PRD-30: no one-cycle lag in the pipeline."""
    loop = Loop(lux=2000)
    recorder = _Recorder()
    loop.env = EnvironmentalController(loop.env._providers, [loop.modifier, recorder], clock=lambda: loop.seconds)
    for _ in range(5):
        result = loop.step()
        assert recorder.seen[-1].brightness == result.modifier("daylight").after.brightness


def test_rm_e01_a_failing_modifier_falls_back_to_the_base(caplog):
    """EC-T11: an exception gives a valid setpoint in the same cycle (and is
    logged once as a warning)."""
    env = EnvironmentalController(modifiers=[_Recorder(fail=True)])
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            result = env.step(START, HCLSetpoint(60, 3000), context())
    assert result.effective == HCLSetpoint(60, 3000)
    assert result.status == STATUS_FALLBACK and result.reason == "recorder_error"
    assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 1


class _Invalid(_Recorder):
    def evaluate(self, state, ctx, current, providers, time):
        after = HCLSetpoint(math.nan, current.kelvin)
        return after, ModifierSnapshot(self.key, STATUS_ACTIVE, "x", current, after), state


def test_rm_e01_an_invalid_result_is_no_value():
    """EC-PRD-22: NaN is an error (fallback), not clamped to a plausible value."""
    env = EnvironmentalController(modifiers=[_Invalid()])
    result = env.step(START, HCLSetpoint(60, 3000), context())
    assert result.effective == HCLSetpoint(60, 3000) and result.status == STATUS_FALLBACK


@pytest.mark.parametrize(
    "statuses,expected",
    [
        ((STATUS_ACTIVE, STATUS_HOLD), STATUS_ACTIVE),
        ((STATUS_HOLD, STATUS_HOLD), STATUS_HOLD),
        ((STATUS_ACTIVE, STATUS_DEGRADED), STATUS_DEGRADED),
        ((STATUS_DEGRADED, STATUS_FALLBACK), STATUS_FALLBACK),
        ((STATUS_BYPASSED, STATUS_HOLD), STATUS_HOLD),
        ((STATUS_BYPASSED, STATUS_BYPASSED), STATUS_BYPASSED),
    ],
)
def test_rm_e01_status_is_aggregated_by_effect_and_keeps_all_reasons(statuses, expected):
    """EC-T17: global status by effect, all reasons in reason_codes."""
    first, second = _Recorder(status=statuses[0]), _Recorder(status=statuses[1])
    second.key = "recorder2"
    env = EnvironmentalController(modifiers=[first, second])
    result = env.step(START, HCLSetpoint(60, 3000), context())
    assert result.status == expected
    assert result.reason_codes == tuple(dict.fromkeys(f"recorder_{s}" for s in statuses))


def test_rm_e01_status_changes_are_logged_once_and_debounced(caplog):
    """EC-T15: no log entry per cycle; a flapping status is not logged."""
    env = EnvironmentalController(modifiers=[_Recorder()])
    rec = env._modifiers[0]
    with caplog.at_level(logging.INFO, logger="custom_components.hcl_lighting.logic.environmental_controller"):
        for _ in range(10):
            env.step(START, HCLSetpoint(60, 3000), context())
        for status in (STATUS_HOLD, STATUS_ACTIVE, STATUS_HOLD, STATUS_ACTIVE):
            rec.status = status
            env.step(START, HCLSetpoint(60, 3000), context())
    lines = [r for r in caplog.records if "Environment status" in r.getMessage()]
    assert len(lines) == 1


def test_rm_e01_published_values_are_rounded_once():
    """EC-T14/EC-PRD-26: a changed brightness is a whole percent."""
    loop = Loop(lux=900)
    for _ in range(3):
        result = loop.step(base=80)
    assert isinstance(result.effective.brightness, int)
    assert result.effective.kelvin == 4000  # not changed: the base value


# ---------------------------------------------------------------- RM-E02 time base
@pytest.mark.parametrize("interval", [10, 27, 60, 120, 300])
def test_rm_e02_rate_is_per_minute_and_dt_is_limited(interval):
    """EC-T04/EC-T05/DL-T03: up to 60 s the same dynamics per minute; above,
    slower but never more than one minute of rate in one step."""
    loop = Loop(lux=3000)
    loop.step(dt=interval)  # start: cap = base
    caps = [loop.cap]
    for _ in range(int(600 / interval)):
        loop.step(dt=interval)
        caps.append(loop.cap)
    steps = [a - b for a, b in zip(caps, caps[1:])]
    assert max(steps) <= 11.0 * min(interval, MAX_CONTROL_DT) / 60 + 1e-9
    drop = caps[0] - caps[-1]
    if interval <= 60:
        assert drop == pytest.approx(min(77.0, 11.0 * 10 * 600 / 600), abs=0.5)
    else:
        assert 0 < drop < 77.0


def test_rm_e02_long_pause_gives_no_jump():
    """EC-T16/EC-PRD-27: after HCL was off for an hour, one step moves the cap
    by at most one minute of rate; the filter uses the real time."""
    loop = Loop(lux=3000)
    loop.step()
    loop.step()
    cap = loop.cap
    loop.lux = 4000
    loop.step(dt=3600)
    assert cap - loop.cap <= 11.0 + 1e-9
    assert loop.state.filtered_lux == pytest.approx(4000, abs=1)


# ---------------------------------------------------------------- RM-E02 control
def test_rm_e02_effective_never_above_base_nor_below_minimum():
    """DL-PRD-03/04."""
    loop = Loop(lux=100000)
    for _ in range(200):
        result = loop.step(base=60, min_brightness=7)
        assert 7 <= result.effective.brightness <= 60
    assert result.effective.brightness == 7
    loop.lux = 0
    for _ in range(200):
        result = loop.step(base=60)
        assert result.effective.brightness <= 60
    assert result.effective.brightness == 60


def test_rm_e02_base_below_the_cap_takes_effect_at_once():
    """DL-T12/E02-8: cur = min(cap, base), no cycles without effect."""
    loop = Loop(lux=500)  # in the dead band
    loop.step(base=80)
    assert loop.cap == 80
    result = loop.step(base=40)
    assert result.effective.brightness == 40 and loop.cap == 40


def test_rm_e02_start_seeds_from_the_auto_brightness():
    """DL-T06/DL-PRD-08: before 25 %, base 80 % -> no jump to 80 %."""
    loop = Loop(lux=500)
    result = loop.step(base=80, seed_brightness=25)
    assert result.effective.brightness == 25
    assert result.modifier("daylight").details["start"] == "daylight_seed"


def test_rm_e02_start_without_seed_uses_the_base():
    loop = Loop(lux=500)
    result = loop.step(base=80)
    assert result.effective.brightness == 80


def test_rm_e02_fresh_persisted_cap_is_used_before_the_first_step():
    """DL-T21/DL-PRD-19: peek before the first step uses a fresh persisted cap."""
    loop = Loop(lux=900, persisted=(30.0, START))
    loop.seconds = 600
    assert loop.peek(base=80).effective.brightness == 30
    assert loop.step(base=80).modifier("daylight").details["start"] == "daylight_resume"


def test_rm_e02_old_persisted_cap_is_discarded():
    """DL-T22: older than 2 h -> seed or base, never a stale cap."""
    loop = Loop(lux=500, persisted=(30.0, START))
    loop.seconds = 7201
    assert loop.peek(base=80).effective.brightness == 80
    result = loop.step(base=80, dt=0)
    assert result.effective.brightness == 80


def test_rm_e02_hold_freezes_the_cap_but_not_the_filter():
    """EC-T06/DL-T07: 60 min manual control: cap frozen; return without a jump."""
    loop = Loop(lux=2000)
    for _ in range(10):
        loop.step()
    cap = loop.cap
    loop.lux = 200
    for _ in range(int(3600 / 27)):
        result = loop.step(lights_on=1, lights_controlled=0, lights_manual=1)
        assert result.status == STATUS_HOLD and loop.cap == cap
    assert loop.state.filtered_lux == pytest.approx(200, abs=1)
    result = loop.step()
    assert abs(result.effective.brightness - cap) <= 11 * 27 / 60 + 1


def test_rm_e02_adapt_off_freezes_the_cap():
    """EC-T07/DL-T08."""
    loop = Loop(lux=2000)
    for _ in range(5):
        loop.step()
    cap = loop.cap
    for _ in range(50):
        result = loop.step(adapt_brightness=False)
    assert loop.cap == cap and result.status == STATUS_HOLD
    assert result.reason == "daylight_hold_adapt_off"
    assert result.effective.brightness == round(cap)


def test_rm_e02_scenario_bypass_keeps_the_cap():
    """EC-T08/DL-T13: scenario <= 2 h: the cap is frozen and used again."""
    loop = Loop(lux=2000)
    for _ in range(10):
        loop.step()
    cap = loop.cap
    for _ in range(int(3600 / 27)):
        result = loop.step(base=100, mode="focus")
        assert result.effective.brightness == 100 and result.status == STATUS_BYPASSED
    assert loop.cap == cap
    result = loop.step(base=80)
    assert abs(result.effective.brightness - cap) <= 11 * 27 / 60 + 1


def test_rm_e02_long_scenario_does_not_seed_its_brightness():
    """DL-T14/DL-T24: after > 2 h the cap starts anew; the scenario brightness
    is never a seed (the switch passes only Auto values as seed)."""
    loop = Loop(lux=500)
    for _ in range(10):
        loop.step(base=80, seed_brightness=30)
    assert loop.cap == 30
    loop.step(base=100, mode="focus", dt=7300)
    result = loop.step(base=80, seed_brightness=None)
    assert result.effective.brightness == 80
    assert result.modifier("daylight").details["start"] == "daylight_seed_fallback"


def test_rm_e02_lights_off_keep_observing():
    """EC-PRD-10: lights off are no hold; the cap follows the daylight."""
    loop = Loop(lux=2000)
    loop.step()
    for _ in range(5):
        result = loop.step(lights_on=0, lights_controlled=0)
    assert result.reason == "daylight_lights_off_observe" and loop.cap < 80


# ---------------------------------------------------------------- RM-E02 sensor outage
@pytest.mark.parametrize("problem", ["unavailable", "unknown", "invalid", "stale"])
def test_rm_e02_short_outage_holds_the_cap(problem):
    """DL-T09/DL-T19/DL-T25: < 5 min the cap is held (same path for all)."""
    loop = Loop(lux=2000)
    for _ in range(10):
        loop.step()
    cap = loop.cap
    loop.problem = problem
    for _ in range(int(290 / 27)):
        result = loop.step()
        assert result.status == STATUS_DEGRADED and loop.cap == cap


def test_rm_e02_long_outage_returns_slowly_to_the_base():
    """DL-T10: > 5 min: with the normal rate towards the base, no jump."""
    loop = Loop(lux=2000)
    for _ in range(20):
        loop.step()
    cap = loop.cap
    loop.problem = "unavailable"
    previous = cap
    for _ in range(60):
        result = loop.step()
        assert result.effective.brightness - previous <= 11 * 27 / 60 + 1
        previous = result.effective.brightness
    assert result.status == STATUS_FALLBACK and result.effective.brightness == 80


def test_rm_e02_recovery_within_the_grace_continues_without_a_jump():
    """DL-T26/DL-PRD-26."""
    loop = Loop(lux=2000)
    for _ in range(10):
        loop.step()
    cap = loop.cap
    loop.problem = "unavailable"
    loop.step()
    loop.problem = None
    result = loop.step()
    assert loop.state.invalid_since is None and result.status == STATUS_ACTIVE
    assert abs(loop.cap - cap) <= 11 * 27 / 60 + 1e-9


def test_rm_e02_hold_and_outage_then_resume_goes_straight_to_fallback():
    """DL-T20/DL-T27/E02-26: manual hold 30 min, sensor missing from minute 1:
    the cap stays in the hold; the first step afterwards falls back at once."""
    loop = Loop(lux=2000)
    for _ in range(10):
        loop.step()
    cap = loop.cap
    manual = dict(lights_on=1, lights_controlled=0, lights_manual=1)
    loop.step(dt=60, **manual)
    loop.problem = "unavailable"
    for _ in range(int(1740 / 27)):
        result = loop.step(**manual)
        assert result.status == STATUS_HOLD and loop.cap == cap
        assert "lux_sensor_unavailable" in result.reason_codes  # diagnosis shows both
    result = loop.step()
    assert result.status == STATUS_FALLBACK
    assert loop.cap > cap


# ---------------------------------------------------------------- RM-E02 room model
def _room(k: float, sensor_period: float, interval: float = 27, hours: float = 4, daylight=None, lumen=None):
    """lux = daylight + k * brightness * lumen factor; the light follows its
    command with the update transition (20 s), the sensor reports every
    sensor_period seconds. Returns (time, lux, effective) per cycle."""
    loop = Loop(cfg=config(), lux=None)
    daylight = daylight or (lambda t: 400.0)
    lumen = lumen or (lambda t: 1.0)
    actual = 80.0
    command = 80.0
    reported = None
    last_report = -1e9
    out = []
    dt = 1.0
    next_cycle = interval
    t = 0.0
    while t < hours * 3600:
        t += dt
        actual += (command - actual) * min(1.0, dt / 20.0)
        lux = daylight(t) + k * actual * lumen(t)
        if t - last_report >= sensor_period:
            reported, last_report = lux, t
        if t >= next_cycle:
            next_cycle += interval
            loop.lux = reported
            loop.seconds = t
            loop.seconds -= interval
            result = loop.step(base=80, dt=interval)
            command = result.effective.brightness
            out.append((t, lux, command))
    return out


def _direction_changes(values):
    diffs = [b - a for a, b in zip(values, values[1:]) if b != a]
    return sum(1 for a, b in zip(diffs, diffs[1:]) if (a > 0) != (b > 0))


@pytest.mark.parametrize("k", [1, 5, 20])
@pytest.mark.parametrize("sensor_period", [5, 60])
def test_rm_e02_room_model_settles_without_limit_cycle(k, sensor_period):
    """DL-T04/E02-1: settles in the dead band, no pumping in the last hour
    (daylight chosen so that about 20 % of light reach the target)."""
    daylight = max(0.0, 500.0 - 20 * k)
    run = _room(k, sensor_period, daylight=lambda t: daylight)
    last_hour = [r for r in run if r[0] > run[-1][0] - 3600]
    commands = [c for _t, _lux, c in last_hour]
    assert max(commands) - min(commands) <= 2, (k, sensor_period, min(commands), max(commands))
    assert _direction_changes(commands) <= 4
    lux = [x for _t, x, _c in last_hour]
    assert abs(sum(lux) / len(lux) - 500) <= 25 + k  # dead band (+ one step of light)


@pytest.mark.parametrize("k", [60, 100])
def test_rm_e02_room_model_sensor_in_the_light_cone_stays_bounded(k):
    """DL-T05/DL-T16: sensor in the light cone: documented warning case (with
    a 60-s sensor k = 100 oscillates between a few percent, see README); the
    output always stays within the minimum and the base."""
    run = _room(k, 60, daylight=lambda t: 0.0)
    assert all(3 <= c <= 80 for _t, _lux, c in run)


def test_rm_e02_room_model_cct_lumen_change_is_compensated():
    """DL-T15/E02-13: +/-15 % lumen over the colour temperature: no pumping."""
    run = _room(5, 60, daylight=lambda t: 400.0, lumen=lambda t: 1.0 + 0.15 * math.sin(2 * math.pi * t / 7200))
    last_hour = [c for t, _lux, c in run if t > run[-1][0] - 3600]
    assert _direction_changes(last_hour) <= 6


def test_rm_e02_error_halves_in_reasonable_time():
    """DL-T18/E02-12: acceptance by error halving instead of an exact end value."""
    run = _room(2, 5, daylight=lambda t: 600.0 if t < 1800 else 300.0)
    after = [(t, lux) for t, lux, _c in run if t >= 1800]
    first_error = abs(after[0][1] - 500)
    halved = next(t for t, lux in after if abs(lux - 500) <= first_error / 2)
    assert halved - 1800 <= 30 * 60
