"""Daylight Estimator (RM-E03, spec DE v1.4): pure model, decision table,
freshness and the provider."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.hcl_lighting.logic import daylight_estimator as de
from custom_components.hcl_lighting.logic.daylight_estimator import (
    BRIGHT_OVERCAST,
    CLEAR_DIRECT,
    DARK_OVERCAST,
    FOG_LOW_CONTRAST,
    LOW_SUN_DIRECT,
    MIXED_VARIABLE,
    NIGHT,
    PRECIPITATION_DARK,
    TWILIGHT,
    UNKNOWN_DAYLIGHT,
    WeatherReading,
    cloud_factor,
    estimate,
    haurwitz_ghi,
)

NOW = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
CONDITIONS = [
    "clear-night", "cloudy", "exceptional", "fog", "hail", "lightning", "lightning-rainy", "partlycloudy",
    "pouring", "rainy", "snowy", "snowy-rainy", "sunny", "windy", "windy-variant",
]


def weather(condition="sunny", coverage=None, age=600.0, entity="weather.home"):
    return WeatherReading(entity, condition, coverage, age)


NO_WEATHER = WeatherReading(None, None, None, None)


# ---------------------------------------------------------------- D0 model
@pytest.mark.parametrize(("elevation", "ghi"), [(10, 137), (30, 490), (60, 890)])
def test_de_t11_haurwitz_golden_cases(elevation, ghi):
    assert haurwitz_ghi(elevation) == pytest.approx(ghi, abs=1.0)


@pytest.mark.parametrize("elevation", [5, 13, 20, 45])
def test_de_t19_haurwitz_is_the_only_clear_sky_model(elevation):
    import math

    cz = math.sin(math.radians(elevation))
    assert haurwitz_ghi(elevation) == pytest.approx(1098.0 * cz * math.exp(-0.057 / cz))


@pytest.mark.parametrize("elevation", [-5, -1, 0])
def test_de_t21_no_daylight_level_at_or_below_the_horizon(elevation):
    state = estimate(NOW, elevation, 180, NO_WEATHER, None)
    assert state.diagnostics.daylight_level == 0
    assert state.daylight_character == (TWILIGHT if elevation < 0 else UNKNOWN_DAYLIGHT)


def test_de_t05_daylight_level_is_normalised_to_800_w_m2():
    assert estimate(NOW, 30, 180, NO_WEATHER, None).diagnostics.daylight_level == pytest.approx(490 / 800, abs=0.002)
    assert estimate(NOW, 60, 180, NO_WEATHER, None).diagnostics.daylight_level == 1.0  # clamped


def test_de_t07_t12_t17_d0_by_day_is_unknown_daylight():
    """D0 knows no sky: the level is the clear-sky potential (diagnosis), the
    character UNKNOWN_DAYLIGHT, confidence 0.40 (DE-PRD-15/20)."""
    state = estimate(NOW, 40, 180, NO_WEATHER, None)
    assert (state.quality_level, state.confidence, state.daylight_character) == ("D0", 0.40, UNKNOWN_DAYLIGHT)
    assert state.diagnostics.ghi_est_w_m2 is None
    assert state.reason == "outdoor_no_weather"


# ---------------------------------------------------------------- D1 model
@pytest.mark.parametrize(("coverage", "n"), [(0, 0.0), (50, 0.5), (100, 1.0)])
def test_de_t04_cloud_coverage_in_percent(coverage, n):
    state = estimate(NOW, 30, 180, weather("cloudy", coverage), None)
    assert state.diagnostics.ghi_est_w_m2 == pytest.approx(haurwitz_ghi(30) * cloud_factor(n), abs=0.1)
    assert state.confidence == 0.80


def test_de_t18_without_cloud_coverage_the_condition_surrogate_is_used():
    state = estimate(NOW, 30, 180, weather("cloudy"), None)
    assert state.diagnostics.ghi_est_w_m2 == pytest.approx(haurwitz_ghi(30) * cloud_factor(0.90), abs=0.1)
    assert (state.quality_level, state.confidence) == ("D1", 0.65)


@pytest.mark.parametrize("condition", CONDITIONS + ["something-new"])
@pytest.mark.parametrize("elevation", [-20, -3, 4, 30])
def test_de_t03_every_condition_gives_a_valid_state(condition, elevation):
    state = estimate(NOW, elevation, 180, weather(condition, 40), None)
    assert state.quality_level in ("D0", "D1")
    assert 0 <= state.confidence <= 1
    assert 0 <= state.diagnostics.daylight_level <= 1
    assert state.daylight_character in de.DAYTIME | {NIGHT, TWILIGHT}


@pytest.mark.parametrize("condition", ["exceptional", "something-new"])
def test_de_t08_exceptional_or_unknown_condition(condition):
    state = estimate(NOW, 30, 180, weather(condition, 40), None)
    assert state.daylight_character == UNKNOWN_DAYLIGHT
    assert state.confidence <= 0.30
    assert state.quality_level == "D0"


def test_clear_night_by_day_is_inconsistent():
    state = estimate(NOW, 30, 180, weather("clear-night", 0), None)
    assert (state.daylight_character, state.quality_level) == (UNKNOWN_DAYLIGHT, "D0")
    assert state.confidence <= 0.30


# ---------------------------------------------------------------- freshness
@pytest.mark.parametrize("state", ["unavailable", "unknown"])
def test_de_t06_t14_unavailable_weather_is_d0(state):
    reading = WeatherReading("weather.home", None, None, None)  # what read_weather returns
    result = estimate(NOW, 30, 180, reading, None)
    assert (result.quality_level, result.confidence, result.reason) == ("D0", 0.40, "outdoor_weather_unavailable")


@pytest.mark.parametrize(
    ("hours", "coverage", "quality", "confidence"),
    [
        (2.9, 40, "D1", 0.80),
        (3.0, 40, "D1", 0.80),
        (3.5, 40, "D0", 0.60),  # half way from 0.80 to 0.40
        (4.0, 40, "D0", 0.40),
        (9.0, 40, "D0", 0.40),
        (3.5, None, "D0", 0.525),  # from 0.65
    ],
)
def test_de_t06_t16_stale_weather_decays_by_age(hours, coverage, quality, confidence):
    """Time based (DE-PRD-19): the same age gives the same confidence whatever
    the update interval."""
    state = estimate(NOW, 30, 180, weather("cloudy", coverage, age=hours * 3600), None)
    assert state.quality_level == quality
    assert state.confidence == pytest.approx(confidence)
    if quality == "D0":
        assert state.daylight_character == UNKNOWN_DAYLIGHT


def test_night_confidence_is_at_least_0_9():
    assert estimate(NOW, -20, 0, NO_WEATHER, None).confidence == 0.90


# ---------------------------------------------------------------- decision table (DE §6)
@pytest.mark.parametrize(
    ("condition", "elevation", "coverage", "expected"),
    [
        ("fog", 30, 100, FOG_LOW_CONTRAST),
        ("rainy", 30, 100, PRECIPITATION_DARK),
        ("pouring", 30, 100, PRECIPITATION_DARK),
        ("hail", 30, 100, PRECIPITATION_DARK),
        ("lightning", 30, 100, PRECIPITATION_DARK),
        ("lightning-rainy", 30, 100, PRECIPITATION_DARK),
        ("snowy-rainy", 30, 100, PRECIPITATION_DARK),
        ("sunny", 5, 0, LOW_SUN_DIRECT),
        ("sunny", 30, 0, CLEAR_DIRECT),
        ("partlycloudy", 30, 50, MIXED_VARIABLE),
        ("windy", 30, 50, MIXED_VARIABLE),
        ("windy-variant", 30, 50, MIXED_VARIABLE),
        ("cloudy", 60, 30, BRIGHT_OVERCAST),  # level 1.0
        ("cloudy", 10, 100, DARK_OVERCAST),  # level 0.04
        ("snowy", 60, 30, BRIGHT_OVERCAST),
        ("sunny", -3, 0, TWILIGHT),  # astronomy first
        ("rainy", -20, 100, NIGHT),
    ],
)
def test_de_t20_character_decision_table(condition, elevation, coverage, expected):
    assert estimate(NOW, elevation, 180, weather(condition, coverage), None).daylight_character == expected


@pytest.mark.parametrize(
    ("previous", "elevation", "expected"),
    [
        (NIGHT, -5.5, NIGHT), (NIGHT, -4.9, TWILIGHT),
        (TWILIGHT, -6.5, TWILIGHT), (TWILIGHT, -7.1, NIGHT),
        (None, -6.0, NIGHT), (None, -5.9, TWILIGHT),
        (TWILIGHT, 0.5, TWILIGHT), (TWILIGHT, 1.1, UNKNOWN_DAYLIGHT),
        (UNKNOWN_DAYLIGHT, -0.5, UNKNOWN_DAYLIGHT), (UNKNOWN_DAYLIGHT, -1.1, TWILIGHT),
    ],
)
def test_de_t13_t22_solar_hysteresis(previous, elevation, expected):
    assert estimate(NOW, elevation, 180, NO_WEATHER, previous).daylight_character == expected


def test_de_t22_sunny_and_cloudy_do_not_flutter():
    # sunny around 8 degrees: the character holds within +/-1 degree
    for start, expected in ((LOW_SUN_DIRECT, LOW_SUN_DIRECT), (CLEAR_DIRECT, CLEAR_DIRECT)):
        previous = start
        for elevation in (7.5, 8.0, 8.5, 7.5, 8.5):
            previous = de._weather_character("sunny", elevation, 0.5, previous)
            assert previous == expected
    # cloudy around 0.35: Schmitt trigger 0.30/0.40
    for start, expected in ((DARK_OVERCAST, DARK_OVERCAST), (BRIGHT_OVERCAST, BRIGHT_OVERCAST)):
        previous = start
        for level in (0.31, 0.35, 0.39, 0.35):
            previous = de._weather_character("cloudy", 30, level, previous)
            assert previous == expected
    assert de._weather_character("cloudy", 30, 0.40, DARK_OVERCAST) == BRIGHT_OVERCAST
    assert de._weather_character("cloudy", 30, 0.29, BRIGHT_OVERCAST) == DARK_OVERCAST


# ---------------------------------------------------------------- provider
async def test_de_t01_t02_t10_provider_is_deterministic_and_peek_keeps_the_state(hass, freezer):
    """Solar position from get_astral_location (2024.12-compatible), the same
    moment gives the same state; only step() commits the character."""
    from custom_components.hcl_lighting.logic.daylight_estimator import OutdoorLightProvider
    from custom_components.hcl_lighting.logic.environmental_controller import (
        EnvironmentalContext,
        StepTime,
    )

    await hass.config.async_update(latitude=53.55, longitude=9.99, elevation=10)
    when = datetime(2026, 6, 21, 11, 0, tzinfo=timezone.utc)
    freezer.move_to(when)  # the weather reports now (fresh)
    hass.states.async_set("weather.home", "sunny", {"cloud_coverage": 10})
    provider = OutdoorLightProvider(hass, None)  # the only weather entity
    ctx = EnvironmentalContext("auto", True, True, True, 27.0, 3, 100)
    a, next_a = provider.evaluate(None, ctx, StepTime(when, 0.0, 0.0, 0.0, False))
    b, _ = provider.evaluate(None, ctx, StepTime(when, 0.0, 0.0, 0.0, False))
    assert a.payload.diagnostics == b.payload.diagnostics
    assert a.payload.diagnostics.solar_elevation_deg == pytest.approx(59.9, abs=0.5)  # Hamburg, midsummer noon
    assert (a.quality, a.payload.daylight_character, next_a) == ("D1", CLEAR_DIRECT, CLEAR_DIRECT)
    assert a.payload.diagnostics.weather_entity_id == "weather.home"


async def test_de_prd_04_weather_auto_detect_only_with_exactly_one_entity(hass):
    assert de.resolve_weather_entity(hass, None) is None
    hass.states.async_set("weather.a", "sunny")
    assert de.resolve_weather_entity(hass, None) == "weather.a"
    hass.states.async_set("weather.b", "cloudy")
    assert de.resolve_weather_entity(hass, None) is None
    assert de.resolve_weather_entity(hass, "weather.b") == "weather.b"


async def test_de_t06_read_weather_age_from_last_reported(hass, freezer):
    hass.states.async_set("weather.home", "cloudy", {"cloud_coverage": 80})
    freezer.tick(timedelta(hours=2))
    from homeassistant.util import dt as dt_util

    reading = de.read_weather(hass, "weather.home", dt_util.utcnow())
    assert reading.condition == "cloudy" and reading.cloud_coverage == 80
    assert reading.age_s == pytest.approx(7200, abs=1)
    hass.states.async_set("weather.home", "unavailable")
    assert de.read_weather(hass, "weather.home", dt_util.utcnow()).condition is None


def test_de_t08_exceptional_stays_low_also_when_stale():
    state = estimate(NOW, 30, 180, weather("exceptional", 40, age=3.2 * 3600), None)
    assert state.confidence <= 0.30
