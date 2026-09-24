"""Regression tests for the bugs fixed in 0.6.1 (B-31 … B-38, backend part)."""
from __future__ import annotations

from datetime import timedelta

import pytest
import voluptuous as vol
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.hcl_lighting.const import DOMAIN, REENGAGE_INTERVAL_SECONDS, REENGAGE_STEPS

from .helpers import CT_ATTRS, core, set_light, setup_entry, switch_entity

REENGAGE_DURATION = REENGAGE_STEPS * REENGAGE_INTERVAL_SECONDS
SWITCH = "switch.hcl_hcl_active"
SELECT = "select.hcl_scenario"


@pytest.fixture(autouse=True)
def _evening(freezer):
    """20:00: the default curve asks for warm, dim light (≠ the 100 %/6500 K test light)."""
    freezer.move_to(dt_util.now().replace(hour=20, minute=0, second=0, microsecond=0))


def _calls_for(calls, entity_id):
    out = []
    for call in calls:
        ids = call.data.get("entity_id")
        ids = [ids] if isinstance(ids, str) else list(ids or [])
        if entity_id in ids:
            out.append(call)
    return out


async def _hcl_on(hass):
    await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    await hass.async_block_till_done()


async def _select(hass, option):
    await hass.services.async_call(
        "select", "select_option", {"entity_id": SELECT, "option": option}, blocking=True
    )
    await hass.async_block_till_done()


# ---------------------------------------------------------------- B-32
async def _expired_override(hass):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    sw = switch_entity(hass)
    om = core(hass, entry)["override_manager"]
    await _hcl_on(hass)
    om._override_state.setdefault("light.a", {})["manual_override_time"] = dt_util.now() - timedelta(hours=5)
    calls.clear()
    await sw._update_hcl()
    await hass.async_block_till_done()
    return calls, sw, om


async def test_b32_reengage_sends_only_the_smooth_transition(hass, no_frontend_registration):
    calls, _sw, om = await _expired_override(hass)
    sent = _calls_for(calls, "light.a")
    assert [c.data.get("transition") for c in sent] == [REENGAGE_DURATION]
    assert not om.is_overridden("light.a")


async def test_b32_following_cycles_leave_the_reengaging_light_alone(hass, no_frontend_registration, freezer):
    calls, sw, _om = await _expired_override(hass)
    calls.clear()
    for _ in range(3):  # three normal cycles within the smooth transition
        freezer.tick(timedelta(seconds=30))
        await sw._update_hcl()
        await hass.async_block_till_done()
    assert _calls_for(calls, "light.a") == []


async def test_b32_normal_updates_resume_after_the_transition(hass, no_frontend_registration, freezer):
    calls, sw, _om = await _expired_override(hass)
    calls.clear()
    freezer.tick(timedelta(seconds=REENGAGE_DURATION + 10))
    await sw._update_hcl()
    await hass.async_block_till_done()
    sent = _calls_for(calls, "light.a")
    assert sent and sent[-1].data.get("transition") != REENGAGE_DURATION


async def test_b32_scenario_change_ends_the_smooth_return(hass, no_frontend_registration):
    calls, _sw, _om = await _expired_override(hass)
    calls.clear()
    await _select(hass, "focus")
    sent = _calls_for(calls, "light.a")
    assert sent, "a scenario change must reach a light that is returning to HCL"


# ---------------------------------------------------------------- B-33
async def _after_hcl_command(hass, freezer):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    om = core(hass, entry)["override_manager"]
    await _hcl_on(hass)
    sent = _calls_for(calls, "light.a")
    assert sent
    freezer.tick(timedelta(seconds=60))  # well after the ignore window
    return sent[-1].context, om


async def test_b33_late_state_report_with_hcl_context_is_not_manual(hass, no_frontend_registration, freezer):
    ctx, om = await _after_hcl_command(hass, freezer)
    hass.states.async_set(
        "light.a", "on", {**CT_ATTRS, "brightness": 150, "color_temp_kelvin": 4000}, context=ctx
    )
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")


async def test_b33_child_context_of_hcl_command_is_not_manual(hass, no_frontend_registration, freezer):
    ctx, om = await _after_hcl_command(hass, freezer)
    hass.states.async_set(
        "light.a", "on", {**CT_ATTRS, "brightness": 150, "color_temp_kelvin": 4000},
        context=Context(parent_id=ctx.id),
    )
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")


async def test_b33_foreign_state_change_is_still_manual(hass, no_frontend_registration, freezer):
    _ctx, om = await _after_hcl_command(hass, freezer)
    hass.states.async_set(
        "light.a", "on", {**CT_ATTRS, "brightness": 150, "color_temp_kelvin": 4000}, context=Context()
    )
    await hass.async_block_till_done()
    assert om.is_overridden("light.a")


# ---------------------------------------------------------------- B-31
async def _reload_in(hass, option):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
    await _select(hass, option)
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    calls.clear()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    return calls, entry


async def test_b31_reload_in_guest_mode_sends_nothing(hass, no_frontend_registration):
    calls, _entry = await _reload_in(hass, "guest")
    assert hass.states.get(SELECT).state == "guest"
    assert _calls_for(calls, "light.a") == []


async def test_b31_reload_in_focus_mode_applies_focus_first(hass, no_frontend_registration):
    calls, _entry = await _reload_in(hass, "focus")
    sent = _calls_for(calls, "light.a")
    assert sent
    assert sent[0].data.get("brightness_pct") == 100
    assert sent[0].data.get("color_temp_kelvin") == 5500


async def test_b31_expired_timed_scenario_restores_as_auto(hass, no_frontend_registration, freezer):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"scenario_duration": 30})
    await _hcl_on(hass)
    await _select(hass, "focus")
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=45))
    calls.clear()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "auto"
    assert all(c.data.get("color_temp_kelvin") != 5500 for c in _calls_for(calls, "light.a"))


# ---------------------------------------------------------------- B-34
XY_CT_ATTRS = {
    "supported_color_modes": ["color_temp", "xy"],
    "color_mode": "color_temp",
    "min_color_temp_kelvin": 2700,
    "max_color_temp_kelvin": 6500,
}


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [(2800, 2600, "xy_sim"), (2600, 2800, "ct"), (6400, 6800, "xy_sim"), (6800, 6400, "ct")],
)
async def test_b34_range_check_does_not_depend_on_earlier_queries(
    hass, no_frontend_registration, first, second, expected
):
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=4000, **XY_CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    ctl = switch_entity(hass).controller
    ctl._get_capability("light.a", first)
    assert ctl._get_capability("light.a", second) == expected


# ---------------------------------------------------------------- B-35
@pytest.mark.parametrize("mode", ["rgbw", "rgbww"])
async def test_b35_rgbw_and_rgbww_lights_get_colour(hass, no_frontend_registration, mode):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(
        hass, "light.a", "on", brightness=255, supported_color_modes=[mode], color_mode=mode,
        xy_color=(0.31, 0.32),
    )
    await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
    sent = _calls_for(calls, "light.a")
    assert sent and "xy_color" in sent[-1].data


# ---------------------------------------------------------------- B-37
async def test_b37_duplicate_times_are_rejected(hass, no_frontend_registration):
    await setup_entry(hass, ["light.a"])
    before = hass.states.get("sensor.hcl_curve_data").attributes.get("control_points")
    points = [
        {"t": 420, "b": 30, "k": 3000},
        {"t": 600, "b": 100, "k": 6000},
        {"t": 600, "b": 10, "k": 2200},
        {"t": 1320, "b": 10, "k": 2200},
    ]
    with pytest.raises((vol.Invalid, HomeAssistantError)):
        await hass.services.async_call(
            DOMAIN, "update_curve",
            {"entity_id": "sensor.hcl_curve_data", "mode": "save", "points": points},
            blocking=True,
        )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.hcl_curve_data").attributes.get("control_points") == before


# ---------------------------------------------------------------- B-36 (sensor part)
async def _curve_call(hass, mode, points=None):
    data = {"entity_id": "sensor.hcl_curve_data", "mode": mode}
    if points is not None:
        data["points"] = points
    await hass.services.async_call(DOMAIN, "update_curve", data, blocking=True)
    await hass.async_block_till_done()


async def test_b36_sensor_reports_whether_a_preview_is_active(hass, no_frontend_registration):
    await setup_entry(hass, ["light.a"])
    attrs = lambda: hass.states.get("sensor.hcl_curve_data").attributes  # noqa: E731
    assert attrs()["preview_active"] is False
    points = [{"t": 420, "b": 30, "k": 3000}, {"t": 1320, "b": 10, "k": 2200}]
    await _curve_call(hass, "preview", points)
    assert attrs()["preview_active"] is True
    await _curve_call(hass, "revert")
    assert attrs()["preview_active"] is False
    await _curve_call(hass, "apply", points)
    assert attrs()["preview_active"] is True
    await _curve_call(hass, "save", points)
    assert attrs()["preview_active"] is False
    assert attrs()["control_points"] == points


# ---------------------------------------------------------------- B-30 (sensor part)
async def test_b30_sensor_exposes_anchor_times(hass, no_frontend_registration):
    await setup_entry(hass, ["light.a"], options={"wake_time": "09:00:00", "sleep_time": "00:30:00"})
    attrs = hass.states.get("sensor.hcl_curve_data").attributes
    assert attrs["wake_time"] == "09:00"
    assert attrs["sleep_time"] == "00:30"


async def test_b30_anchor_times_default(hass, no_frontend_registration):
    await setup_entry(hass, ["light.a"])
    attrs = hass.states.get("sensor.hcl_curve_data").attributes
    assert (attrs["wake_time"], attrs["sleep_time"]) == ("07:00", "22:00")
