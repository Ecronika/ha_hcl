"""Daylight Estimator (RM-E03, spec DE v1.4): outdoor light state D0/D1.

A qualitative, explainable state of the daylight outside from the position of
the sun (D0, Haurwitz clear-sky model) and optionally a weather entity (D1,
Kasten/Czeplak cloud model). No virtual lux or colour temperature sensor, no
network I/O, no service call (DE-PRD-11). Its only consumer is Visual Harmony
(RM-E04); the indoor lux sensor stays authoritative for the daylight
compensation. Stable for consumers: quality, confidence, character, reason
(DE-PRD-17); everything else is diagnosis.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.sun import get_astral_location

from .environmental_controller import (
    STATUS_ACTIVE,
    STATUS_DEGRADED,
    EnvironmentalContext,
    EnvironmentalStateSnapshot,
    StepTime,
)

OUTDOOR_KEY = "outdoor_light"

QUALITY_D0 = "D0"
QUALITY_D1 = "D1"

# Daylight character (DE §6)
NIGHT = "night"
TWILIGHT = "twilight"
LOW_SUN_DIRECT = "low_sun_direct"
CLEAR_DIRECT = "clear_direct"
MIXED_VARIABLE = "mixed_variable"
BRIGHT_OVERCAST = "bright_overcast"
DARK_OVERCAST = "dark_overcast"
FOG_LOW_CONTRAST = "fog_low_contrast"
PRECIPITATION_DARK = "precipitation_dark"
UNKNOWN_DAYLIGHT = "unknown_daylight"
DAYTIME = frozenset(
    {LOW_SUN_DIRECT, CLEAR_DIRECT, MIXED_VARIABLE, BRIGHT_OVERCAST, DARK_OVERCAST,
     FOG_LOW_CONTRAST, PRECIPITATION_DARK, UNKNOWN_DAYLIGHT}
)

GHI_REFERENCE = 800.0  # W/m2, product normalisation of daylight_level (DE-PRD-09)
WEATHER_FRESH_S = 3 * 3600.0  # DE-PRD-07
WEATHER_DECAY_S = 3600.0  # linear confidence decay after that (DE-PRD-19)

# Weather condition families (all conditions of Home Assistant, DE §10)
_PRECIPITATION = frozenset({"rainy", "pouring", "snowy-rainy", "hail", "lightning", "lightning-rainy"})
_MIXED = frozenset({"partlycloudy", "windy", "windy-variant"})
_OVERCAST = frozenset({"cloudy", "snowy"})
# Cloud cover n (0..1) of a condition when the entity has no cloud_coverage (DE §9)
_CLOUD_SURROGATE = {
    "sunny": 0.10, "partlycloudy": 0.50, "windy": 0.50, "windy-variant": 0.50, "cloudy": 0.90,
    "fog": 0.95, "snowy": 1.0, **{c: 1.0 for c in _PRECIPITATION},
}
# Probability of direct sun by condition (diagnosis only)
_DIRECT_SUN = {"sunny": 0.9, "partlycloudy": 0.5, "windy": 0.5, "windy-variant": 0.5, "cloudy": 0.1}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def haurwitz_ghi(elevation_deg: float) -> float:
    """Clear-sky global horizontal irradiance (W/m2), Haurwitz; 0 at or below
    the horizon (DE-PRD-14/22/24)."""
    cos_z = math.sin(math.radians(elevation_deg))
    if cos_z <= 0:
        return 0.0
    return 1098.0 * cos_z * math.exp(-0.057 / cos_z)


def cloud_factor(n: float) -> float:
    """All-sky attenuation by Kasten/Czeplak for the cloud cover n (0..1)."""
    return 1.0 - 0.75 * _clamp(n, 0.0, 1.0) ** 3.4


@dataclass(frozen=True, slots=True)
class DaylightDiagnostics:
    """Model values without API guarantee (DE §5)."""

    daylight_level: float  # 0..1; D0: clear-sky potential
    direct_sun_probability: float | None
    ghi_clear_w_m2: float
    ghi_est_w_m2: float | None
    solar_elevation_deg: float
    solar_azimuth_deg: float
    weather_entity_id: str | None
    weather_age_seconds: float | None


@dataclass(frozen=True, slots=True)
class OutdoorLightState:
    """Outdoor light state (DE §5): quality, confidence, character and reason
    are the stable fields for consumers."""

    timestamp: datetime
    quality_level: str
    confidence: float
    daylight_character: str
    reason: str
    diagnostics: DaylightDiagnostics | None = None


@dataclass(frozen=True, slots=True)
class WeatherReading:
    """What the estimator needs from the weather entity."""

    entity_id: str | None
    condition: str | None  # None: no weather entity, unavailable or unknown
    cloud_coverage: float | None  # percent
    age_s: float | None


def _astronomical(elevation: float, previous: str | None) -> str | None:
    """NIGHT/TWILIGHT from the solar elevation with +/-1 degree hysteresis
    against the previous character (DE §6); None: daytime."""
    if previous == NIGHT:
        night = elevation <= -5.0  # leaves the night upwards only above -5 degrees
    elif previous == TWILIGHT:
        night = elevation < -7.0  # enters the night only below -7 degrees
    else:
        night = elevation <= -6.0
    if night:
        return NIGHT
    if previous in (NIGHT, TWILIGHT):
        day = elevation > 1.0
    elif previous in DAYTIME:
        day = elevation >= -1.0
    else:
        day = elevation >= 0.0
    return None if day else TWILIGHT


def _weather_character(condition: str, elevation: float, level: float, previous: str | None) -> str:
    """Daytime character of D1 by the normative decision table (DE §6)."""
    if condition == "fog":
        return FOG_LOW_CONTRAST
    if condition in _PRECIPITATION:
        return PRECIPITATION_DARK
    if condition == "sunny":
        if previous == LOW_SUN_DIRECT:
            low = elevation < 9.0
        elif previous == CLEAR_DIRECT:
            low = elevation < 7.0
        else:
            low = elevation < 8.0
        return LOW_SUN_DIRECT if low else CLEAR_DIRECT
    if condition in _MIXED:
        return MIXED_VARIABLE
    if condition in _OVERCAST:
        if previous == DARK_OVERCAST:
            bright = level >= 0.40
        elif previous == BRIGHT_OVERCAST:
            bright = level >= 0.30
        else:
            bright = level >= 0.35
        return BRIGHT_OVERCAST if bright else DARK_OVERCAST
    return UNKNOWN_DAYLIGHT  # exceptional, unknown, clear-night by day


def estimate(
    now: datetime, elevation: float, azimuth: float, weather: WeatherReading, previous: str | None
) -> OutdoorLightState:
    """Outdoor light state for one moment (pure; DE §7-§13)."""
    ghi_clear = haurwitz_ghi(elevation)
    condition = weather.condition
    known = condition in _CLOUD_SURROGATE
    c_fresh = 0.80 if weather.cloud_coverage is not None else 0.65
    if condition is None:
        quality, confidence = QUALITY_D0, 0.40
        reason = "outdoor_no_weather" if weather.entity_id is None else "outdoor_weather_unavailable"
    elif weather.age_s is not None and weather.age_s > WEATHER_FRESH_S:
        decay = _clamp((weather.age_s - WEATHER_FRESH_S) / WEATHER_DECAY_S, 0.0, 1.0)
        quality, confidence, reason = QUALITY_D0, c_fresh - (c_fresh - 0.40) * decay, "outdoor_weather_stale"
    elif not known and condition != "clear-night":
        quality, confidence, reason = QUALITY_D0, 0.30, "outdoor_weather_unknown_condition"
    else:
        quality, confidence, reason = QUALITY_D1, c_fresh, "outdoor_weather"
    if condition is not None and not known and condition != "clear-night":
        confidence = min(confidence, 0.30)  # exceptional or unknown, also when stale (DE §11)

    ghi_est = None
    direct = None
    n = None
    if quality == QUALITY_D1 and known:
        n = (
            _clamp(weather.cloud_coverage / 100.0, 0.0, 1.0)
            if weather.cloud_coverage is not None
            else _CLOUD_SURROGATE[condition]
        )
        ghi_est = ghi_clear * cloud_factor(n)
        direct = _DIRECT_SUN.get(condition, 0.05) if elevation > 0 else 0.0
    level = _clamp((ghi_est if ghi_est is not None else ghi_clear) / GHI_REFERENCE, 0.0, 1.0)

    character = _astronomical(elevation, previous)
    if character is None:
        if quality == QUALITY_D1 and known:
            character = _weather_character(condition, elevation, level, previous)
        else:
            # D0 by day: no assumed sky (DE-PRD-20); clear-night by day is inconsistent
            character = UNKNOWN_DAYLIGHT
            if quality == QUALITY_D1:
                quality, confidence, reason = QUALITY_D0, 0.30, "outdoor_weather_unknown_condition"
    if character == NIGHT:
        confidence = max(confidence, 0.90)
    return OutdoorLightState(
        timestamp=now,
        quality_level=quality,
        confidence=round(confidence, 4),
        daylight_character=character,
        reason=reason,
        diagnostics=DaylightDiagnostics(
            daylight_level=round(level, 4),
            direct_sun_probability=direct,
            ghi_clear_w_m2=round(ghi_clear, 1),
            ghi_est_w_m2=None if ghi_est is None else round(ghi_est, 1),
            solar_elevation_deg=round(elevation, 2),
            solar_azimuth_deg=round(azimuth, 2),
            weather_entity_id=weather.entity_id,
            weather_age_seconds=None if weather.age_s is None else round(weather.age_s),
        ),
    )


def resolve_weather_entity(hass: HomeAssistant, configured: str | None) -> str | None:
    """The configured weather entity, else the only one (DE-PRD-04)."""
    if configured:
        return configured
    entities = hass.states.async_entity_ids("weather")
    return entities[0] if len(entities) == 1 else None


def read_weather(hass: HomeAssistant, entity_id: str | None, now: datetime) -> WeatherReading:
    """Condition, cloud cover and age of the weather entity (DE-PRD-05/07/16)."""
    state = hass.states.get(entity_id) if entity_id else None
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return WeatherReading(entity_id, None, None, None)
    coverage = state.attributes.get("cloud_coverage")
    if not isinstance(coverage, (int, float)) or isinstance(coverage, bool) or not math.isfinite(coverage):
        coverage = None
    age = max(0.0, (now - state.last_reported).total_seconds())
    return WeatherReading(entity_id, state.state, coverage, age)


class OutdoorLightProvider:
    """State provider of the Daylight Estimator; its state is the previous
    character (hysteresis, committed only by step(), DE-PRD-25)."""

    key = OUTDOOR_KEY

    def __init__(self, hass: HomeAssistant, weather_entity: str | None) -> None:
        self._hass = hass
        self._weather = weather_entity

    def initial_state(self) -> str | None:
        return None

    def evaluate(
        self, state: str | None, ctx: EnvironmentalContext, time: StepTime
    ) -> tuple[EnvironmentalStateSnapshot[OutdoorLightState], str | None]:
        location, elevation_m = get_astral_location(self._hass)
        elevation = location.solar_elevation(time.now, elevation_m)
        azimuth = location.solar_azimuth(time.now, elevation_m)
        weather = read_weather(self._hass, resolve_weather_entity(self._hass, self._weather), time.now)
        result = estimate(time.now, elevation, azimuth, weather, state)
        status = STATUS_ACTIVE if result.quality_level == QUALITY_D1 or weather.entity_id is None else STATUS_DEGRADED
        snapshot = EnvironmentalStateSnapshot(
            self.key, status, result.quality_level, result.confidence, result, result.reason
        )
        return snapshot, result.daylight_character
