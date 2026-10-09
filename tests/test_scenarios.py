"""Scenarios: values, durations, transitions, night modes, Guest (deprecated)."""
from __future__ import annotations

import logging
import pytest

from datetime import timedelta
from homeassistant.core import State
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service, mock_restore_cache, mock_restore_cache_with_extra_data

from custom_components.hcl_lighting.const import DOMAIN

from .support.entries import CT_ATTRS, SELECT, SENSOR, calls_for, core, hcl_on, select_scenario, set_light, setup_entry, switch_entity
from .support.lights import FakeLights


ADAPT_B = "switch.hcl_adapt_brightness"


async def _light_on(hass, options=None):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options=options)
    await hcl_on(hass)
    return calls, entry


TARGET_B = "sensor.hcl_target_brightness"


@pytest.fixture
def _at_sleep_time(freezer):
    """22:00 (sleep time): the default curve asks for 10 %."""
    freezer.move_to(dt_util.now().replace(hour=22, minute=0, second=0, microsecond=0))


def _last(calls, entity_id="light.a"):
    return [c for c in calls if entity_id in c.data["entity_id"]][-1].data


def _guest_issue(hass, entry):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"guest_deprecated_{entry.entry_id}")


# ------------------------------------------------------------------ Ä-02
async def test_a02_sleep_still_switches_off_without_brightness_adaptation(hass, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=2700, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    await hass.services.async_call("switch", "turn_off", {"entity_id": ADAPT_B}, blocking=True)
    await switch_entity(hass).async_turn_on()
    calls.clear()
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "sleep"}, blocking=True)
    await hass.async_block_till_done()
    assert calls_for(calls, "light.a")[-1].data["brightness_pct"] == 0


# ------------------------------------------------------------------ Ä-07
async def test_a07_configured_scenario_values(hass, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    await setup_entry(hass, ["light.a"], options={"focus_brightness": 80, "focus_kelvin": 5000})
    await switch_entity(hass).async_turn_on()
    calls.clear()
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "focus"}, blocking=True)
    await hass.async_block_till_done()
    last = calls_for(calls, "light.a")[-1].data
    assert last["brightness_pct"] == 80 and last["color_temp_kelvin"] == 5000
    scen = hass.states.get("sensor.hcl_curve_data").attributes["scenarios"]
    assert scen["focus"] == {"b": 80, "k": 5000} and scen["relax"] == {"b": 40, "k": 2700}


async def test_a07_scenario_duration(hass, freezer, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await setup_entry(hass, ["light.a"], options={"scenario_duration": 30})
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "focus"}, blocking=True)
    assert hass.states.get(SELECT).attributes["until"] is not None
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "auto"
    assert hass.states.get(SELECT).attributes["until"] is None
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "guest"}, blocking=True)
    assert hass.states.get(SELECT).attributes["until"] is None  # guest/sleep are not timed


@pytest.mark.parametrize(("minutes", "expected"), [(-5, "auto"), (20, "relax")])
async def test_a07_timed_scenario_restored(hass, no_frontend_registration, minutes, expected):
    until = (dt_util.utcnow() + timedelta(minutes=minutes)).isoformat()
    mock_restore_cache_with_extra_data(hass, [(State(SELECT, "relax"), {"until": until})])
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await setup_entry(hass, ["light.a"], options={"scenario_duration": 30})
    assert hass.states.get(SELECT).state == expected


async def test_a07_no_duration_by_default(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "focus"}, blocking=True)
    assert hass.states.get(SELECT).attributes["until"] is None


# ---------------------------------------------------------------- Ä-18
@pytest.mark.usefixtures("evening")
async def test_a18_scenario_change_uses_the_update_transition_by_default(hass, no_frontend_registration):
    calls, _entry = await _light_on(hass)
    await select_scenario(hass, "focus")
    assert calls_for(calls, "light.a")[-1].data["transition"] == 20


@pytest.mark.usefixtures("evening")
async def test_a18_scenario_transition_option(hass, no_frontend_registration):
    calls, _entry = await _light_on(hass, options={"scenario_transition": 2})
    await select_scenario(hass, "focus")
    assert calls_for(calls, "light.a")[-1].data["transition"] == 2


@pytest.mark.usefixtures("evening")
async def test_a18_long_scenario_transition_is_not_cut_short(hass, no_frontend_registration, freezer):
    calls, _entry = await _light_on(hass, options={"scenario_transition": 120})
    await select_scenario(hass, "relax")
    assert calls_for(calls, "light.a")[-1].data["transition"] == 120
    calls.clear()
    sw = switch_entity(hass)
    freezer.tick(timedelta(seconds=30))
    await sw._update_hcl()
    await hass.async_block_till_done()
    assert calls_for(calls, "light.a") == []


@pytest.mark.usefixtures("evening")
async def test_a18_restore_after_reload_is_no_scenario_change(hass, no_frontend_registration):
    calls, entry = await _light_on(hass, options={"scenario_transition": 2})
    await select_scenario(hass, "focus")
    set_light(hass, "light.a", "on", brightness=10, color_temp_kelvin=3000, **CT_ATTRS)
    await hass.async_block_till_done()
    core(hass, entry)["override_manager"].reset_override("light.a")  # the change above is no manual control here
    calls.clear()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert calls_for(calls, "light.a")[-1].data["transition"] == 20


# ---------------------------------------------------------------- Ä-04 night light
@pytest.mark.usefixtures("evening")
async def test_a04_night_light_dims_lights_that_are_on(hass, no_frontend_registration):
    calls, _entry = await _light_on(hass)
    await select_scenario(hass, "night_light")
    data = calls_for(calls, "light.a")[-1].data
    assert (data["brightness_pct"], data["color_temp_kelvin"]) == (3, 2200)
    assert all(c.service == "turn_on" for c in calls)


@pytest.mark.usefixtures("evening")
async def test_a04_light_switched_on_in_night_light_gets_night_values(hass, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    await select_scenario(hass, "night_light")
    calls.clear()
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=4000, **CT_ATTRS)
    await hass.async_block_till_done()
    data = calls_for(calls, "light.a")[-1].data
    assert (data["brightness_pct"], data["color_temp_kelvin"]) == (3, 2200)
    assert not core(hass, entry)["override_manager"].is_overridden("light.a")


@pytest.mark.usefixtures("evening")
async def test_a04_night_light_values_are_configurable(hass, no_frontend_registration):
    calls, _entry = await _light_on(hass, options={"night_light_brightness": 8, "night_light_kelvin": 2000})
    await select_scenario(hass, "night_light")
    data = calls_for(calls, "light.a")[-1].data
    assert (data["brightness_pct"], data["color_temp_kelvin"]) == (8, 2000)


# ---------------------------------------------------------------- RM-R01
@pytest.mark.usefixtures("_at_sleep_time")
@pytest.mark.parametrize("old", [{}, {"scenario_limits": False}])
async def test_rm_r01_scenarios_always_within_min_max(hass, no_frontend_registration, old):
    calls, _entry = await _light_on(hass, options={"min_brightness": 50, "max_brightness": 60, **old})
    await select_scenario(hass, "focus")  # 100 %
    assert _last(calls)["brightness_pct"] == 60
    await select_scenario(hass, "relax")  # 40 %
    assert _last(calls)["brightness_pct"] == 50
    scenarios = hass.states.get(SENSOR).attributes["scenarios"]
    assert scenarios["focus"]["b"] == 60 and scenarios["cleaning"]["b"] == 60


@pytest.mark.usefixtures("_at_sleep_time")
async def test_rm_r01_night_light_is_not_limited(hass, no_frontend_registration):
    calls, _entry = await _light_on(hass, options={"min_brightness": 10})
    await select_scenario(hass, "night_light")
    assert _last(calls)["brightness_pct"] == 3
    assert hass.states.get(TARGET_B).state == "3"


# ---------------------------------------------------------------- RM-R02
@pytest.mark.usefixtures("_at_sleep_time")
@pytest.mark.parametrize("old", [{}, {"brightness_scaling": True}])
async def test_rm_r02_min_max_only_clip(hass, no_frontend_registration, old):
    calls, _entry = await _light_on(hass, options={"min_brightness": 20, "max_brightness": 60, **old})
    assert _last(calls)["brightness_pct"] == 20  # curve 10 % clipped (scaled: 24 %)
    assert hass.states.get(TARGET_B).state == "20"
    attrs = hass.states.get(SENSOR).attributes
    assert "brightness_scaling" not in attrs
    samples = [s[2] for s in attrs["samples"]]
    assert min(samples) == 20 and max(samples) == 60
    assert any(20 < s < 60 for s in samples)  # values within the limits stay as they are


# ---------------------------------------------------------------- RM-R03
@pytest.mark.usefixtures("_at_sleep_time")
@pytest.mark.parametrize("mode", ["sleep", "night_light"])
@pytest.mark.parametrize("old", [{}, {"night_end_at_wake": False}])
async def test_rm_r03_night_modes_end_at_the_wake_time(hass, no_frontend_registration, freezer, mode, old):
    await _light_on(hass, options=old or None)
    await select_scenario(hass, mode)
    until = dt_util.parse_datetime(hass.states.get(SELECT).attributes["until"])
    assert dt_util.as_local(until).strftime("%H:%M") == "07:00" and until > dt_util.utcnow()
    freezer.move_to(until + timedelta(seconds=1))
    async_fire_time_changed(hass, until + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "auto"


@pytest.mark.usefixtures("_at_sleep_time")
async def test_rm_r03_duration_zero_keeps_the_night_mode(hass, no_frontend_registration, freezer):
    await _light_on(hass)
    await hass.services.async_call(
        DOMAIN, "set_scenario", {"entity_id": SELECT, "scenario": "night_light", "duration": 0}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).attributes["until"] is None
    freezer.tick(timedelta(hours=14))  # past the next wake time
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "night_light"


# ---------------------------------------------------------------- B-01
async def test_b01_sleep_mode_allows_manual_turn_on(hass, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    sw = switch_entity(hass)
    await sw.async_turn_on()
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.hcl_scenario", "option": "sleep"}, blocking=True
    )
    await hass.async_block_till_done()
    calls.clear()

    # User switches the light on at night (wall switch / app).
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=2700, **CT_ATTRS)
    await hass.async_block_till_done()
    await sw._update_hcl()
    await hass.async_block_till_done()

    assert calls_for(calls, "light.a") == [], "Sleep mode must not switch a manually switched-on light off again"
    assert core(hass, entry)["override_manager"].is_overridden("light.a")


async def test_b01_sleep_mode_still_turns_off_lights_on_activation(hass, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=2700, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    sw = switch_entity(hass)
    await sw.async_turn_on()
    calls.clear()
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.hcl_scenario", "option": "sleep"}, blocking=True
    )
    await hass.async_block_till_done()
    sent = calls_for(calls, "light.a")
    assert sent and sent[-1].data["brightness_pct"] == 0


# ---------------------------------------------------------------- RM-R12
async def test_rm_r12_guest_warns_and_shows_a_repair_issue(hass, no_frontend_registration, caplog):
    FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=100, color_temp_kelvin=3000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    assert _guest_issue(hass, entry) is None
    with caplog.at_level(logging.WARNING):
        await select_scenario(hass, "guest")
    assert hass.states.get(SELECT).state == "guest"  # still works in 0.8.0
    issue = _guest_issue(hass, entry)
    assert issue is not None and issue.translation_key == "guest_deprecated"
    assert issue.severity == ir.IssueSeverity.WARNING and not issue.is_fixable
    assert "deprecated" in caplog.text
    await select_scenario(hass, "auto")
    assert _guest_issue(hass, entry) is None
    await select_scenario(hass, "guest")
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _guest_issue(hass, entry) is None


async def test_rm_r12_guest_restored_after_a_restart_shows_the_issue(hass, no_frontend_registration):
    mock_restore_cache(hass, [State(SELECT, "guest")])
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    assert hass.states.get(SELECT).state == "guest"
    assert _guest_issue(hass, entry) is not None
