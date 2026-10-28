"""Visual Harmony (RM-E04) with the Daylight Estimator (RM-E03) in a Home
Assistant instance: options, cycles, sensors, reload, diagnostics."""
from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.hcl_lighting.logic.visual_harmony import HARMONY_KEY

from .support.daylight import LUX_SENSOR
from .support.entries import core
from .test_daylight import TARGET_B, TARGET_K, _cycles, _daylight, _daylight_step

HARMONY = {"harmony_profile": "balanced"}


@pytest.fixture
async def noon(hass, freezer):
    """12:00 Europe/Berlin (default curve: 100 % / 6000 K), as in test_daylight."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-01-15 11:00:00+00:00")
    return freezer


@pytest.fixture(autouse=True)
async def _hamburg(hass):
    """Solar position of Hamburg (noon in January: sun at about 14 degrees)."""
    await hass.config.async_update(latitude=53.55, longitude=9.99, elevation=10)


def _sent_kelvin(fake, eid="light.a"):
    calls = [c for c in fake.for_light(eid) if "color_temp_kelvin" in c.data]
    return calls[-1].data["color_temp_kelvin"] if calls else None


async def test_rm_e04_strong_daylight_makes_the_light_warmer(hass, noon, no_frontend_registration):
    """Noon (curve 6000 K): the daylight compensation lowers the brightness,
    Visual Harmony limits the colour temperature softly; the target sensor
    shows base, effective and the own reason."""
    hass.states.async_set("weather.home", "sunny", {"cloud_coverage": 10})
    fake, entry = await _daylight(hass, lux=3000, options=HARMONY)
    await _cycles(hass, noon, 120)
    sent = _sent_kelvin(fake)
    assert sent is not None and sent < 5800
    state = hass.states.get(TARGET_K)
    assert int(state.state) < state.attributes["base_value"]
    assert state.attributes["environment_reason"] == "harmony_warming"
    assert state.attributes["outdoor_quality"] == "D1"  # the only weather entity
    assert state.attributes["harmony_delta_mired"] > 0
    assert {"harmony_delta_mired", "daylight_character"} <= type(
        hass.data["entity_components"]["sensor"].get_entity(TARGET_K)
    )._unrecorded_attributes


async def test_rm_e04_without_reduction_no_change(hass, noon, no_frontend_registration):
    fake, entry = await _daylight(hass, lux=100, options=HARMONY)  # below the target: no reduction
    await _cycles(hass, noon, 40)
    state = hass.states.get(TARGET_K)
    assert int(state.state) == state.attributes["base_value"]
    assert state.attributes["environment_reason"] == "harmony_no_reduction"


async def test_rm_e04_harmony_needs_the_daylight_compensation(hass, no_frontend_registration):
    from .support.entries import CT_ATTRS, set_light, setup_entry

    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    flow, _ = await _daylight_step(hass, entry)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"daylight_enabled": False, "harmony_profile": "balanced", "daylight_advanced": {}}
    )
    assert result["errors"] == {"harmony_profile": "harmony_requires_daylight"}
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {"daylight_enabled": True, "daylight_sensor": LUX_SENSOR, "daylight_target_lux": 500,
         "harmony_profile": "strong", "harmony_weather": "weather.home", "daylight_advanced": {}},
    )
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert entry.options["harmony_profile"] == "strong"
    assert entry.options["harmony_weather"] == "weather.home"


async def test_e04_17_options_save_hands_the_correction_over(hass, noon, no_frontend_registration):
    """O17 = C: the reload after saving the options continues with the
    correction in effect (no jump, no cold start); after a restart of Home
    Assistant (no handover) the raw value is seeded."""
    fake, entry = await _daylight(hass, lux=3000, options=HARMONY)
    await _cycles(hass, noon, 120)
    before = core(hass, entry).environment.state(HARMONY_KEY).delta_mired
    assert before > 0
    hass.config_entries.async_update_entry(entry, options={**entry.options, "harmony_profile": "strong"})
    await hass.async_block_till_done()
    env = core(hass, entry).environment
    assert env.state(HARMONY_KEY).delta_mired == before  # handed over
    await _cycles(hass, noon, 3)
    # rate limited towards strong: at most 5 mired per step of at most 60 s
    assert 0 < env.state(HARMONY_KEY).delta_mired - before <= 2 * 5 + 1e-6
    # switched off and on again: starts at 0 (VH-PRD-15)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "harmony_profile": "off"})
    await hass.async_block_till_done()
    assert core(hass, entry).environment.state(HARMONY_KEY) is None
    hass.config_entries.async_update_entry(entry, options={**entry.options, "harmony_profile": "balanced"})
    await hass.async_block_till_done()
    assert core(hass, entry).environment.state(HARMONY_KEY).delta_mired == 0


async def test_de_t09_no_forecast_service_and_diagnostics(hass, noon, no_frontend_registration):
    from custom_components.hcl_lighting.diagnostics import async_get_config_entry_diagnostics

    forecasts = async_mock_service(hass, "weather", "get_forecasts")
    hass.states.async_set("weather.home", "cloudy", {"cloud_coverage": 90})
    fake, entry = await _daylight(hass, lux=3000, options={**HARMONY, "harmony_weather": "weather.home"})
    await _cycles(hass, noon, 5)
    assert forecasts == []
    diag = await async_get_config_entry_diagnostics(hass, entry)
    outdoor = diag["environment"]["now"]["outdoor_light"]
    assert outdoor["quality"] == "D1" and outdoor["character"] in ("dark_overcast", "bright_overcast")
    assert outdoor["weather_entity"] is True
    assert "weather.home" not in str(diag)  # pseudonymised
    harmony = next(m for m in diag["environment"]["now"]["modifiers"] if m["key"] == HARMONY_KEY)
    assert harmony["reduction_ratio"] > 0
    # no position of the home (review 28.10.2026): no azimuth, no irradiance,
    # the elevation in whole degrees
    assert not {"solar_azimuth_deg", "ghi_clear_w_m2", "ghi_est_w_m2"} & set(outdoor)
    assert isinstance(outdoor["solar_elevation_deg"], int)


async def test_rm_e04_brightness_sensor_keeps_the_daylight_status(hass, noon, no_frontend_registration):
    """Review 28.10.2026: with Visual Harmony the target brightness still shows
    the status and reason of the daylight compensation (e.g. its hold during
    manual control), the colour temperature those of Visual Harmony."""
    fake, entry = await _daylight(hass, lux=3000, options=HARMONY)
    await _cycles(hass, noon, 5)
    core(hass, entry).override_manager.set_override("light.a")
    await _cycles(hass, noon, 3)
    brightness = hass.states.get(TARGET_B).attributes
    assert (brightness["environment_status"], brightness["environment_reason"]) == ("hold", "daylight_hold_manual_control")
    kelvin = hass.states.get(TARGET_K).attributes
    assert kelvin["environment_reason"].startswith("harmony_")
