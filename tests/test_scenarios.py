"""Scenarios: values, durations, transitions, night modes, Guest (removed in 0.9.0)."""
from __future__ import annotations

import logging
import pytest
import voluptuous as vol

from datetime import timedelta
from homeassistant.core import State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed, async_mock_service, mock_restore_cache, mock_restore_cache_with_extra_data

from custom_components.hcl_lighting.const import DOMAIN, MODE_SLEEP, SCENARIO_DEFAULTS

from .support.entries import ADAPT, CT_ATTRS, SELECT, SENSOR, SWITCH, calls_for, core, hcl_on, light_on, select_scenario, set_light, setup_entry, switch_entity, timer_cycle


ADAPT_B = "switch.hcl_adapt_brightness"


TARGET_B = "sensor.hcl_target_brightness"


@pytest.fixture
def _at_sleep_time(freezer):
    """22:00 (sleep time): the default curve asks for 10 %."""
    freezer.move_to(dt_util.now().replace(hour=22, minute=0, second=0, microsecond=0))


def _last(calls, entity_id="light.a"):
    return [c for c in calls if entity_id in c.data["entity_id"]][-1].data




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


@pytest.mark.parametrize(("minutes", "expected"), [(-5, "auto"), (20, "relax")])
async def test_a07_timed_scenario_restored(hass, no_frontend_registration, minutes, expected):
    until = (dt_util.utcnow() + timedelta(minutes=minutes)).isoformat()
    mock_restore_cache_with_extra_data(hass, [(State(SELECT, "relax"), {"until": until})])
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await setup_entry(hass, ["light.a"], options={"scenario_duration": 30})
    assert hass.states.get(SELECT).state == expected


@pytest.mark.parametrize(
    ("until", "expected", "timed"),
    [
        (timedelta(minutes=-5), "auto", False),
        (timedelta(minutes=20), "relax", True),
        (None, "relax", False),
        (12345, "relax", False),  # not a time (damaged store): no end, no error
        ("not a time", "relax", False),
    ],
)
async def test_rm_t27_scenario_is_restored_once_for_controller_and_select(
    hass, no_frontend_registration, until, expected, timed
):
    """One restore path: the controller (first light command) and the mode
    select show the same scenario and end time."""
    if isinstance(until, timedelta):
        until = (dt_util.utcnow() + until).isoformat()
    mock_restore_cache_with_extra_data(hass, [(State(SELECT, "relax"), {"until": until})])
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"scenario_duration": 30})
    state = hass.states.get(SELECT)
    assert state.state == expected
    assert core(hass, entry).controller.active_mode == expected
    assert (state.attributes["until"] is not None) == timed


async def test_a07_no_duration_by_default(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "focus"}, blocking=True)
    assert hass.states.get(SELECT).attributes["until"] is None


# ---------------------------------------------------------------- Ä-18
@pytest.mark.usefixtures("evening")
async def test_a18_scenario_change_uses_the_update_transition_by_default(hass, no_frontend_registration):
    calls, _entry = await light_on(hass)
    await select_scenario(hass, "focus")
    assert calls_for(calls, "light.a")[-1].data["transition"] == 20


@pytest.mark.usefixtures("evening")
async def test_a18_scenario_transition_option(hass, no_frontend_registration):
    calls, _entry = await light_on(hass, options={"scenario_transition": 2})
    await select_scenario(hass, "focus")
    assert calls_for(calls, "light.a")[-1].data["transition"] == 2


@pytest.mark.usefixtures("evening")
async def test_a18_long_scenario_transition_is_not_cut_short(hass, no_frontend_registration, freezer):
    calls, _entry = await light_on(hass, options={"scenario_transition": 120})
    await select_scenario(hass, "relax")
    assert calls_for(calls, "light.a")[-1].data["transition"] == 120
    calls.clear()
    freezer.tick(timedelta(seconds=30))
    await timer_cycle(hass)
    await hass.async_block_till_done()
    assert calls_for(calls, "light.a") == []


@pytest.mark.usefixtures("evening")
async def test_a18_restore_after_reload_is_no_scenario_change(hass, no_frontend_registration):
    calls, entry = await light_on(hass, options={"scenario_transition": 2})
    await select_scenario(hass, "focus")
    set_light(hass, "light.a", "on", brightness=10, color_temp_kelvin=3000, **CT_ATTRS)
    await hass.async_block_till_done()
    core(hass, entry).override_manager.reset_override("light.a")  # the change above is no manual control here
    calls.clear()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert calls_for(calls, "light.a")[-1].data["transition"] == 20


# ---------------------------------------------------------------- Ä-04 night light
@pytest.mark.usefixtures("evening")
async def test_a04_night_light_dims_lights_that_are_on(hass, no_frontend_registration):
    calls, _entry = await light_on(hass)
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
    assert not core(hass, entry).override_manager.is_overridden("light.a")


@pytest.mark.usefixtures("evening")
async def test_a04_night_light_values_are_configurable(hass, no_frontend_registration):
    calls, _entry = await light_on(hass, options={"night_light_brightness": 8, "night_light_kelvin": 2000})
    await select_scenario(hass, "night_light")
    data = calls_for(calls, "light.a")[-1].data
    assert (data["brightness_pct"], data["color_temp_kelvin"]) == (8, 2000)


# ---------------------------------------------------------------- RM-R01
@pytest.mark.usefixtures("_at_sleep_time")
@pytest.mark.parametrize("old", [{}, {"scenario_limits": False}])
async def test_rm_r01_scenarios_always_within_min_max(hass, no_frontend_registration, old):
    calls, _entry = await light_on(hass, options={"min_brightness": 50, "max_brightness": 60, **old})
    await select_scenario(hass, "focus")  # 100 %
    assert _last(calls)["brightness_pct"] == 60
    await select_scenario(hass, "relax")  # 40 %
    assert _last(calls)["brightness_pct"] == 50
    scenarios = hass.states.get(SENSOR).attributes["scenarios"]
    assert scenarios["focus"]["b"] == 60 and scenarios["cleaning"]["b"] == 60


@pytest.mark.usefixtures("_at_sleep_time")
async def test_rm_r01_night_light_is_not_limited(hass, no_frontend_registration):
    calls, _entry = await light_on(hass, options={"min_brightness": 10})
    await select_scenario(hass, "night_light")
    assert _last(calls)["brightness_pct"] == 3
    assert hass.states.get(TARGET_B).state == "3"


# ---------------------------------------------------------------- RM-R02
@pytest.mark.usefixtures("_at_sleep_time")
@pytest.mark.parametrize("old", [{}, {"brightness_scaling": True}])
async def test_rm_r02_min_max_only_clip(hass, no_frontend_registration, old):
    calls, _entry = await light_on(hass, options={"min_brightness": 20, "max_brightness": 60, **old})
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
    await light_on(hass, options=old or None)
    await select_scenario(hass, mode)
    until = dt_util.parse_datetime(hass.states.get(SELECT).attributes["until"])
    assert dt_util.as_local(until).strftime("%H:%M") == "07:00" and until > dt_util.utcnow()
    freezer.move_to(until + timedelta(seconds=1))
    async_fire_time_changed(hass, until + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "auto"


@pytest.mark.usefixtures("_at_sleep_time")
async def test_rm_r03_duration_zero_keeps_the_night_mode(hass, no_frontend_registration, freezer):
    await light_on(hass)
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
    await timer_cycle(hass)
    await hass.async_block_till_done()

    assert calls_for(calls, "light.a") == [], "Sleep mode must not switch a manually switched-on light off again"
    assert core(hass, entry).override_manager.is_overridden("light.a")


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


# ---------------------------------------------------------------- RM-R12 (removed in 0.9.0)
async def test_rm_r12_guest_is_no_longer_a_scenario(hass, no_frontend_registration):
    from homeassistant.exceptions import ServiceValidationError

    await light_on(hass)
    assert "guest" not in hass.states.get(SELECT).attributes["options"]
    with pytest.raises(ServiceValidationError):
        await select_scenario(hass, "guest")
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(DOMAIN, "set_scenario", {"entity_id": SELECT, "scenario": "guest"}, blocking=True)
    assert hass.states.get(SELECT).state == "auto"


@pytest.mark.usefixtures("evening")
@pytest.mark.parametrize("hcl_active", ["on", "off"])
async def test_rm_r12_restored_guest_starts_in_auto_with_hcl_off(hass, no_frontend_registration, caplog, hcl_active):
    """An instance left in Guest (0.8.x) starts in Auto with "HCL active" off
    (Guest sent no values either); no light command, the repair issue of 0.8.x
    is removed."""
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = MockConfigEntry(domain=DOMAIN, title="HCL", options={"target": {"entity_id": ["light.a"]}}, minor_version=2)
    entry.add_to_hass(hass)
    # entities of the earlier version (the restore of the first command reads the registry)
    er.async_get(hass).async_get_or_create(
        "select", DOMAIN, f"{entry.entry_id}_mode", config_entry=entry, suggested_object_id="hcl_scenario"
    )
    mock_restore_cache(hass, [State(SELECT, "guest"), State(SWITCH, hcl_active)])
    issue_id = f"guest_deprecated_{entry.entry_id}"
    ir.async_create_issue(hass, DOMAIN, issue_id, is_fixable=False, severity=ir.IssueSeverity.WARNING,
                          translation_key="guest_deprecated")
    with caplog.at_level(logging.WARNING):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "auto"
    assert hass.states.get(SWITCH).state == "off"
    assert calls_for(calls, "light.a") == []
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert "Guest was removed" in caplog.text


# ---------------------------------------------------------------- RM-B52 (review 17.10.2026)
@pytest.mark.parametrize("byte", [1, 3, 4])
async def test_rm_b52_sleep_switches_off_a_very_dim_light(hass, no_frontend_registration, byte):
    """Sleep (0 %) must switch off a light that is on, also at 1 % (brightness byte <= 3)."""
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=byte, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    set_light(hass, "light.a", "on", brightness=byte, color_temp_kelvin=2000, **CT_ATTRS)
    await hass.async_block_till_done()
    calls.clear()
    await select_scenario(hass, "sleep")
    sent = [c.data for c in calls_for(calls, "light.a")]
    assert any(d.get("brightness_pct") == 0 for d in sent), sent


async def test_rm_b52_sleep_switches_off_a_dim_light_without_brightness_adaptation(hass, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=2, supported_color_modes=["brightness"], color_mode="brightness")
    await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    await hass.services.async_call("switch", "turn_off", {"entity_id": ADAPT}, blocking=True)
    set_light(hass, "light.a", "on", brightness=2, supported_color_modes=["brightness"], color_mode="brightness")
    await hass.async_block_till_done()
    calls.clear()
    await select_scenario(hass, "sleep")
    assert [c.data.get("brightness_pct") for c in calls_for(calls, "light.a")] == [0]


async def test_rm_b52_sleep_leaves_a_manually_controlled_dim_light_alone(hass, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    core(hass, entry).override_manager.set_override("light.a")
    calls.clear()
    await select_scenario(hass, "sleep")
    assert calls_for(calls, "light.a") == []


# ---------------------------------------------------------------- RM-T30 (review 17.10.2026)
async def test_rm_t30_sleep_values_come_from_the_scenario_table(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    controller = core(hass, entry).controller
    await select_scenario(hass, "sleep")
    expected = (SCENARIO_DEFAULTS[MODE_SLEEP]["brightness"], SCENARIO_DEFAULTS[MODE_SLEEP]["kelvin"])
    assert controller.calculate_base_values(dt_util.now()) == expected
