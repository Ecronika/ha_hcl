"""0.7.0b9: RM-R01 … RM-R03 of the roadmap (beta options become fixed behaviour)."""
from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

from custom_components.hcl_lighting.const import DOMAIN

from .helpers import CT_ATTRS, set_light, setup_entry

SWITCH = "switch.hcl_hcl_active"
SELECT = "select.hcl_scenario"
SENSOR = "sensor.hcl_curve_data"
TARGET_B = "sensor.hcl_target_brightness"
OLD_OPTIONS = ("brightness_scaling", "scenario_limits", "night_end_at_wake")


@pytest.fixture(autouse=True)
def _evening(freezer):
    """20:00: the default curve asks for 17 %."""
    freezer.move_to(dt_util.now().replace(hour=20, minute=0, second=0, microsecond=0))


def _last(calls, entity_id="light.a"):
    return [c for c in calls if entity_id in c.data["entity_id"]][-1].data


async def _light_on(hass, options=None):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options=options)
    await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    await hass.async_block_till_done()
    return calls, entry


async def _select(hass, option):
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": option}, blocking=True)
    await hass.async_block_till_done()


# ---------------------------------------------------------------- RM-R01
@pytest.mark.parametrize("old", [{}, {"scenario_limits": False}])
async def test_rm_r01_scenarios_always_within_min_max(hass, no_frontend_registration, old):
    calls, _entry = await _light_on(hass, options={"min_brightness": 50, "max_brightness": 60, **old})
    await _select(hass, "focus")  # 100 %
    assert _last(calls)["brightness_pct"] == 60
    await _select(hass, "relax")  # 40 %
    assert _last(calls)["brightness_pct"] == 50
    scenarios = hass.states.get(SENSOR).attributes["scenarios"]
    assert scenarios["focus"]["b"] == 60 and scenarios["cleaning"]["b"] == 60


async def test_rm_r01_night_light_is_not_limited(hass, no_frontend_registration):
    calls, _entry = await _light_on(hass, options={"min_brightness": 10})
    await _select(hass, "night_light")
    assert _last(calls)["brightness_pct"] == 3
    assert hass.states.get(TARGET_B).state == "3"


# ---------------------------------------------------------------- RM-R02
@pytest.mark.parametrize("old", [{}, {"brightness_scaling": True}])
async def test_rm_r02_min_max_only_clip(hass, no_frontend_registration, old):
    calls, _entry = await _light_on(hass, options={"min_brightness": 20, "max_brightness": 60, **old})
    assert _last(calls)["brightness_pct"] == 20  # curve 17 % clipped (scaled: 23 %)
    assert hass.states.get(TARGET_B).state == "20"
    attrs = hass.states.get(SENSOR).attributes
    assert "brightness_scaling" not in attrs
    samples = [s[2] for s in attrs["samples"]]
    assert min(samples) == 20 and max(samples) == 60
    assert 50 in samples  # the midday dip (50 %) is within the limits and stays as it is


# ---------------------------------------------------------------- RM-R03
@pytest.mark.parametrize("mode", ["sleep", "night_light"])
@pytest.mark.parametrize("old", [{}, {"night_end_at_wake": False}])
async def test_rm_r03_night_modes_end_at_the_wake_time(hass, no_frontend_registration, freezer, mode, old):
    await _light_on(hass, options=old or None)
    await _select(hass, mode)
    until = dt_util.parse_datetime(hass.states.get(SELECT).attributes["until"])
    assert dt_util.as_local(until).strftime("%H:%M") == "07:00" and until > dt_util.utcnow()
    freezer.move_to(until + timedelta(seconds=1))
    async_fire_time_changed(hass, until + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "auto"


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


# ---------------------------------------------------------------- options flow
async def test_rm_r01_r03_options_gone_from_the_flow_and_the_entry(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(
        hass, ["light.a"], options={"brightness_scaling": True, "scenario_limits": False, "night_end_at_wake": True}
    )
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    fields = {str(k) for k in flow["data_schema"].schema}
    base = {"target": {"entity_id": ["light.a"]}, "wake_time": "07:00:00", "midday_time": "12:30:00",
            "sleep_time": "22:00:00", "smart_transition": False, "min_brightness": 10, "max_brightness": 100}
    result = await hass.config_entries.options.async_configure(flow["flow_id"], base)
    fields |= {str(k) for k in result["data_schema"].schema}
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {"update_interval": 27, "transition": 20, "turn_on_transition": 0, "override_timeout": 240,
         "override_reset_on_off": True, "persist_overrides": False, "respect_turn_on_values": False},
    )
    fields |= {str(k) for k in result["data_schema"].schema}
    assert not fields & set(OLD_OPTIONS)
    result = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert not set(entry.options) & set(OLD_OPTIONS)
