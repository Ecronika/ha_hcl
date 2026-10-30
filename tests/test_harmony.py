"""Visual Harmony (RM-E04, spec VH v1.4): unit tests of the modifier with a
fake brightness reduction and a fake outdoor light state."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.hcl_lighting.logic.daylight_estimator import (
    BRIGHT_OVERCAST,
    CLEAR_DIRECT,
    LOW_SUN_DIRECT,
    NIGHT,
    OUTDOOR_KEY,
    TWILIGHT,
    UNKNOWN_DAYLIGHT,
    OutdoorLightState,
)
from custom_components.hcl_lighting.logic.environmental_controller import (
    STATUS_ACTIVE,
    STATUS_BYPASSED,
    STATUS_HOLD,
    EnvironmentalController,
    EnvironmentalStateSnapshot,
    HCLSetpoint,
    ModifierSnapshot,
)
from custom_components.hcl_lighting.logic.visual_harmony import (
    DISABLED,
    HARMONY_KEY,
    RELEASE_RATE,
    TIGHTEN_RATE,
    WARMEST_MIRED,
    HarmonyConfig,
    VisualHarmonyModifier,
    envelope_mired,
    raw_delta,
)

from .support.daylight import context

START = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)


def mired(kelvin: float) -> float:
    return 1_000_000 / kelvin


class Dim:
    """Brightness modifier before Visual Harmony: sets the effective brightness."""

    key = "daylight"

    def __init__(self, rig):
        self.rig = rig

    def initial_state(self):
        return None

    def evaluate(self, state, ctx, current, providers, time):
        after = replace(current, brightness=self.rig.effective)
        return after, ModifierSnapshot(self.key, STATUS_ACTIVE, "daylight_reducing", current, after), None


class Outdoor:
    key = OUTDOOR_KEY

    def __init__(self, rig):
        self.rig = rig

    def initial_state(self):
        return None

    def evaluate(self, state, ctx, time):
        o = self.rig.outdoor
        return EnvironmentalStateSnapshot(self.key, STATUS_ACTIVE, "D1", None if o is None else o.confidence, o, "outdoor"), None


@dataclass
class Rig:
    profile: str = "balanced"
    handover: float | str | None = None
    effective: float = 20.0
    outdoor: OutdoorLightState | None = None
    seconds: float = 0.0
    env: EnvironmentalController = field(init=False)

    def __post_init__(self):
        self.modifier = VisualHarmonyModifier(HarmonyConfig(self.profile, None), self.handover)
        self.env = EnvironmentalController(
            providers=[Outdoor(self)], modifiers=[Dim(self), self.modifier], clock=lambda: self.seconds
        )

    def step(self, base_b=100.0, base_k=6500.0, dt=27.0, **ctx):
        self.seconds += dt
        return self.env.step(START + timedelta(seconds=self.seconds), HCLSetpoint(base_b, base_k), context(**ctx))

    def peek(self, base_b=100.0, base_k=6500.0, **ctx):
        return self.env.peek(START + timedelta(seconds=self.seconds), HCLSetpoint(base_b, base_k), context(**ctx))

    @property
    def delta(self):
        return self.env.state(HARMONY_KEY).delta_mired


def outdoor(character, confidence):
    return OutdoorLightState(START, "D1", confidence, character, "test")


def settle(rig, minutes=60, **kw):
    for _ in range(int(minutes * 60 / 27)):
        result = rig.step(**kw)
    return result


# ---------------------------------------------------------------- core (VH §7-§11)
def test_vh_t01_no_reduction_no_change():
    rig = Rig(effective=30.0)
    result = settle(rig, base_b=30.0)
    assert result.effective.kelvin == 6500
    assert rig.delta == 0
    assert result.modifier(HARMONY_KEY).reason == "harmony_no_reduction"


def test_vh_t02_strong_reduction_reference_value():
    """Balanced, no estimator, base 100 % -> 20 %, 6500 K: 4855 K (review 29.09.2026)."""
    rig = Rig(effective=20.0)
    result = settle(rig, minutes=120)
    assert result.effective.kelvin == pytest.approx(4855, abs=10)
    assert result.modifier(HARMONY_KEY).details["reduction_ratio"] == 0.8


def test_vh_g4_never_cooler_than_the_base():
    """A base warmer than the cap is not changed (2700 K < 4000 K cap)."""
    rig = Rig(effective=10.0)
    result = settle(rig, base_k=2700.0)
    assert result.effective.kelvin == 2700


def test_vh_t03_the_base_follows_at_once():
    rig = Rig(effective=20.0)
    settle(rig, minutes=120)
    delta = rig.delta
    result = rig.step(base_k=6000.0)  # the curve moves: no lag of the base
    assert 1_000_000 / (mired(6000) + rig.delta) == pytest.approx(result.effective.kelvin, abs=10)
    assert abs(rig.delta - delta) <= RELEASE_RATE * 27 / 60 + 1e-9  # only the correction is smoothed


def test_vh_t04_t15_release_and_tighten_rates():
    rig = Rig(handover=DISABLED, effective=20.0)
    rig.step()
    for _ in range(20):
        before = rig.delta
        rig.step()
        assert rig.delta - before <= TIGHTEN_RATE * 27 / 60 + 1e-9
    settle(rig, minutes=120)
    rig.effective = 100.0  # the daylight is gone
    for _ in range(20):
        before = rig.delta
        rig.step()
        assert 0 <= before - rig.delta <= RELEASE_RATE * 27 / 60 + 1e-9
    settle(rig, minutes=60)
    assert rig.delta == 0


@pytest.mark.parametrize("interval", [10, 27, 60])
def test_vh_t07_same_dynamics_for_intervals_up_to_60_s(interval):
    rig = Rig(handover=DISABLED, effective=20.0)
    for _ in range(int(600 / interval)):
        rig.step(dt=interval)
    reference = Rig(handover=DISABLED, effective=20.0)
    for _ in range(int(600 / 27)):
        reference.step(dt=27)
    assert rig.delta == pytest.approx(reference.delta, rel=0.1)


@pytest.mark.parametrize("interval", [120, 300])
def test_e04_18_longer_intervals_are_never_faster(interval):
    """dt_control is limited to 60 s (EC-PRD-07): at most the rate of 60 s per update."""
    rig = Rig(handover=DISABLED, effective=20.0)
    for _ in range(5):
        before = rig.delta or 0
        rig.step(dt=interval)
        assert rig.delta - before <= TIGHTEN_RATE + 1e-9


def test_vh_t12_envelope_is_continuous():
    base = mired(6500)
    for point in (0.15, 0.30, 0.50, 0.75, 0.90):
        left, right = envelope_mired(point - 1e-6, base), envelope_mired(point + 1e-6, base)
        assert left == pytest.approx(right, abs=0.01)
    assert envelope_mired(0.95, base) == base
    assert envelope_mired(0.05, base) == pytest.approx(mired(4000))


# ---------------------------------------------------------------- bypass, hold (VH §12)
def test_vh_prd_02_scenario_bypass_and_return_to_auto():
    rig = Rig(effective=20.0)
    settle(rig, minutes=60)
    result = rig.step(mode="focus")
    assert result.modifier(HARMONY_KEY).status == STATUS_BYPASSED
    assert result.effective.kelvin == 6500
    result = rig.step()  # back in Auto: the raw value at once, no lag
    raw = result.modifier(HARMONY_KEY).details["raw_delta_mired"]
    assert rig.delta == pytest.approx(raw, abs=0.1)


def test_vh_t05_adapt_brightness_off_is_bypassed_without_windup():
    rig = Rig(effective=20.0)
    settle(rig, minutes=60)
    result = rig.step(adapt_brightness=False)
    assert result.modifier(HARMONY_KEY).status == STATUS_BYPASSED
    assert result.effective.kelvin == 6500
    rig.step()
    assert rig.delta <= TIGHTEN_RATE * 27 / 60 + 1e-9  # builds up again from 0


def test_vh_t06_adapt_color_off_holds_the_correction():
    rig = Rig(effective=20.0)
    settle(rig, minutes=60)
    delta = rig.delta
    for _ in range(10):
        result = rig.step(adapt_color=False)
    assert result.modifier(HARMONY_KEY).status == STATUS_HOLD
    assert rig.delta == delta


def test_hcl_off_holds_and_peek_shows_the_correction():
    rig = Rig(effective=20.0)
    settle(rig, minutes=60)
    stepped = rig.step()
    result = rig.peek(hcl_active=False)
    assert result.effective.kelvin == stepped.effective.kelvin


# ---------------------------------------------------------------- estimator (VH §9/§10, §16)
def test_vh_t09_t16_no_estimator_and_unknown_daylight_are_the_same():
    a = Rig(effective=20.0)
    b = Rig(effective=20.0, outdoor=outdoor(UNKNOWN_DAYLIGHT, 0.4))
    assert settle(a).effective.kelvin == settle(b).effective.kelvin


def test_vh_t10_confidence_blends_continuously():
    values = []
    for c in (0.0, 0.25, 0.5, 0.75, 1.0):
        values.append(raw_delta(100, 20, 6500, "balanced", outdoor(CLEAR_DIRECT, c))[0])
    assert values[0] == pytest.approx(raw_delta(100, 20, 6500, "balanced", None)[0])
    assert values == sorted(values)  # CLEAR_DIRECT (1.0) strengthens
    weaker = [raw_delta(100, 20, 6500, "balanced", outdoor(TWILIGHT, c))[0] for c in (0.0, 0.5, 1.0)]
    assert weaker == sorted(weaker, reverse=True)  # TWILIGHT (0.45) weakens on purpose


def test_vh_t14_offsets_are_in_mired():
    """BRIGHT_OVERCAST shifts the cap by -8 mired at full confidence, at any base."""
    for kelvin in (6500, 5800):
        with_offset = raw_delta(100, 5, kelvin, "strong", outdoor(BRIGHT_OVERCAST, 1.0))
        assert with_offset[1]["influence"] == pytest.approx(0.9)
        plain = raw_delta(100, 5, kelvin, "strong", outdoor(BRIGHT_OVERCAST, 0.0))
        # influence differs (weight), compare the caps through the targets
        cap_with = mired(kelvin) + with_offset[0] / 0.9
        cap_plain = mired(kelvin) + plain[0] / plain[1]["influence"]
        assert cap_with - cap_plain == pytest.approx(-8.0, abs=0.01)


def test_vh_t11_night_releases_the_correction():
    rig = Rig(effective=20.0)
    settle(rig, minutes=60)
    rig.outdoor = outdoor(NIGHT, 0.9)
    result = rig.step()
    assert result.modifier(HARMONY_KEY).reason == "harmony_night"
    settle(rig, minutes=60)
    assert rig.delta == 0


def test_vh_t18_reduction_of_the_same_step():
    rig = Rig(handover=None, effective=20.0)
    result = rig.step()  # the first step seeds with the reduction of this very step
    assert result.modifier(HARMONY_KEY).details["reduction_ratio"] == 0.8
    assert rig.delta == pytest.approx(result.modifier(HARMONY_KEY).details["raw_delta_mired"], abs=0.1)


# ---------------------------------------------------------------- lifecycle (VH §12, O17 = C)
def test_vh_t13_start_seeds_the_raw_value():
    rig = Rig(handover=None, effective=20.0)
    result = rig.step()
    assert result.effective.kelvin == pytest.approx(4855, abs=10)  # no cold start


def test_vh_t19_feature_enabled_builds_up_without_a_jump():
    rig = Rig(handover=DISABLED, effective=20.0)
    result = rig.step()
    assert rig.delta <= TIGHTEN_RATE * 27 / 60 + 1e-9
    assert result.effective.kelvin >= 6400


def test_vh_t17_e04_17_changed_parameters_continue_from_the_handed_over_correction():
    """Reload after saving the options: the correction of the old setup
    continues and moves rate limited to the new target (balanced -> strong)."""
    old = Rig(profile="balanced", effective=20.0)
    settle(old, minutes=120)
    new = Rig(profile="strong", handover=old.delta, effective=20.0)
    new.step()  # the first step of a setup has no elapsed time
    assert new.delta == old.delta
    new.step()
    assert 0 < new.delta - old.delta <= TIGHTEN_RATE * 27 / 60 + 1e-9
    same = Rig(profile="balanced", handover=old.delta, effective=20.0)
    same.step()
    same.step()
    assert same.delta == pytest.approx(old.delta, abs=0.01)  # identical reload: no jump


# ---------------------------------------------------------------- RM-B58 (review 29.10.2026)
@pytest.mark.parametrize("base_k", [2000.0, 2700.0])
def test_rm_b58_a_base_warmer_than_the_envelope_gets_no_correction(base_k):
    """The curve jumps from 6500 K to a warm value (curve saved) while a
    correction of about 52 mired is in effect: 0.9.0b2 sent 1830 K / 2390 K
    (warmer than the envelope, below 2000 K). The applied correction is
    limited to the envelope; the stored one is still released at its rate."""
    rig = Rig(effective=20.0)
    settle(rig, minutes=120)
    before = rig.delta
    assert before > 50
    result = rig.step(base_k=base_k)
    assert result.effective.kelvin == base_k
    assert before - rig.delta <= RELEASE_RATE * 27 / 60 + 1e-9


@pytest.mark.parametrize("character", [None, TWILIGHT, BRIGHT_OVERCAST])
def test_rm_b58_never_warmer_than_the_warmest_point_of_the_envelope(character):
    """Strong, full reduction, then the base 6500 K -> 4300 K: the applied
    correction ends at the warm end of the envelope with the largest offset
    (4000 K + 15 mired, about 3770 K); 0.9.0b2: about 3200 K."""
    rig = Rig(profile="strong", effective=5.0, outdoor=None if character is None else outdoor(character, 1.0))
    settle(rig, minutes=120)
    assert rig.delta > 45
    result = rig.step(base_k=4300.0)
    assert result.effective.kelvin >= 1_000_000 / WARMEST_MIRED - 10
    assert WARMEST_MIRED == pytest.approx(mired(4000) + 15)


def test_rm_b58_a_change_of_the_character_does_not_move_the_limit():
    """Review 0.9.0b3: a limit that depends on the character offset would jump
    by up to 23 mired when the character changes."""
    rig = Rig(profile="strong", effective=5.0, outdoor=outdoor(LOW_SUN_DIRECT, 1.0))
    settle(rig, minutes=120)
    sent = [mired(rig.step(base_k=4600.0).effective.kelvin)]
    rig.outdoor = outdoor(BRIGHT_OVERCAST, 1.0)
    for _ in range(10):
        sent.append(mired(rig.step(base_k=4600.0).effective.kelvin))
    assert max(abs(b - a) for a, b in zip(sent, sent[1:])) <= RELEASE_RATE * 27 / 60 + 0.5


def test_rm_b58_the_correction_is_released_at_its_rate_when_the_daylight_goes():
    """The limit does not make the release faster: the daylight compensation
    raises the brightness at once or at 11 %/min, the colour temperature
    returns at most 10 mired/min (VH-PRD-13)."""
    for raise_per_step in (11 * 27 / 60, 100.0):
        rig = Rig(effective=20.0)
        settle(rig, minutes=120)
        sent = [mired(rig.step().effective.kelvin)]
        for _ in range(40):
            rig.effective = min(100.0, rig.effective + raise_per_step)
            sent.append(mired(rig.step().effective.kelvin))
        assert max(a - b for a, b in zip(sent, sent[1:])) <= RELEASE_RATE * 27 / 60 + 0.5
        assert sent[-1] == pytest.approx(mired(6500), abs=0.5)


def test_rm_b58_no_jump_along_the_evening_curve():
    """The curve falls from 6500 K to 2200 K in 3 h with a constant reduction:
    the colour temperature changes smoothly (no step larger than the change
    of the curve plus the rate of the correction) and is never below 2000 K."""
    rig = Rig(effective=20.0)
    settle(rig, minutes=120)
    steps = 400
    kelvins = [6500 - (6500 - 2200) * i / steps for i in range(steps + 1)]
    sent = [mired(rig.step(base_k=k).effective.kelvin) for k in kelvins]
    curve_step = max(mired(b) - mired(a) for a, b in zip(kelvins, kelvins[1:]))
    assert max(abs(b - a) for a, b in zip(sent, sent[1:])) <= curve_step + RELEASE_RATE * 27 / 60 + 1.0
    assert max(sent) <= mired(2000)


# ---------------------------------------------------------------- RM-B59 (review 29.10.2026)
def test_rm_b59_rounding_is_never_cooler_than_the_base():
    """VH-PRD-03 after the rounding to 10 K: base 6507 K, result 6506.998 K
    was published as 6510 K."""
    from custom_components.hcl_lighting.logic.environmental_controller import _published

    assert _published(HCLSetpoint(80, 6507.0), HCLSetpoint(80, 6506.998)).kelvin == 6500
    for base in range(2000, 7001, 7):
        for kelvin in (base - 0.001, base - 4.9, base - 5.0, base - 12.0):
            published = _published(HCLSetpoint(80, float(base)), HCLSetpoint(80, kelvin)).kelvin
            assert published <= base and published % 10 == 0
            assert abs(published - kelvin) < 10


# ---------------------------------------------------------------- RM-B61 (review 0.9.0b3)
@pytest.mark.parametrize("base_k", [2028.0, 2878.0, 2935.0])
def test_rm_b61_a_correction_limited_to_zero_keeps_the_base(base_k):
    """A stored correction, the curve warmer than the limit: the applied
    correction is 0 and the base is published unchanged (0.9.0b3: 2020 K,
    2880 K, 2940 K through the conversion to mired and back)."""
    rig = Rig(effective=20.0)
    settle(rig, minutes=120)
    assert rig.delta > 45
    result = rig.step(base_k=base_k)
    assert result.effective.kelvin == base_k
    assert result.modifier(HARMONY_KEY).details["delta_mired"] == 0
