"""Entities of an instance: switch, select and sensor attributes, names, recorder."""
from __future__ import annotations

import pytest

from datetime import timedelta
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed, async_mock_service

from custom_components.hcl_lighting.const import CONF_MAX_BRIGHTNESS, CONF_MIN_BRIGHTNESS, DOMAIN
from custom_components.hcl_lighting.logic.hcl_math import default_points
from custom_components.hcl_lighting.sensor import HCLLightingCurveSensor

from .support.entries import CT_ATTRS, SELECT, SENSOR, SWITCH, calls_for, hcl_on, select_scenario, set_light, setup_entry, switch_entity
from .support.lights import FakeLights


async def _curve_call(hass, mode, points=None):
    data = {"entity_id": "sensor.hcl_curve_data", "mode": mode}
    if points is not None:
        data["points"] = points
    await hass.services.async_call(DOMAIN, "update_curve", data, blocking=True)
    await hass.async_block_till_done()


ADAPT_B = "switch.hcl_adapt_brightness"


ADAPT_K = "switch.hcl_adapt_colour_temperature"


TARGET_B = "sensor.hcl_target_brightness"


TARGET_K = "sensor.hcl_target_colour_temperature"


async def _light_on(hass, options=None):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options=options)
    await hcl_on(hass)
    return calls, entry


UNRECORDED = {"calculated_brightness", "calculated_color_temp", "target_entities", "manual_control"}


# ---------------------------------------------------------------- B-36 (sensor part)
@pytest.mark.usefixtures("evening")
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
@pytest.mark.usefixtures("evening")
async def test_b30_sensor_exposes_anchor_times(hass, no_frontend_registration):
    await setup_entry(hass, ["light.a"], options={"wake_time": "09:00:00", "sleep_time": "00:30:00"})
    attrs = hass.states.get("sensor.hcl_curve_data").attributes
    assert attrs["wake_time"] == "09:00"
    assert attrs["sleep_time"] == "00:30"


@pytest.mark.usefixtures("evening")
async def test_b30_anchor_times_default(hass, no_frontend_registration):
    await setup_entry(hass, ["light.a"])
    attrs = hass.states.get("sensor.hcl_curve_data").attributes
    assert (attrs["wake_time"], attrs["sleep_time"]) == ("07:00", "22:00")


# ------------------------------------------------------------------ Ä-10
async def test_a10_names_and_visibility(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    ent_reg = er.async_get(hass)
    select = ent_reg.async_get(SELECT)
    assert select is not None and select.entity_category is None
    assert ent_reg.async_get(SWITCH) is not None
    ids = {e.entity_id for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)}
    assert {SWITCH, SELECT, ADAPT_B, ADAPT_K, "sensor.hcl_curve_data"} <= ids


# ------------------------------------------------------------------ Ä-14
async def test_a14_curve_sensor_timestamp_and_recorder(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    state = hass.states.get("sensor.hcl_curve_data")
    assert state.attributes["device_class"] == "timestamp"
    assert dt_util.parse_datetime(state.state) is not None
    sensor = next(e for e in hass.data["entity_components"]["sensor"].entities if e.entity_id == "sensor.hcl_curve_data")
    assert {"samples", "control_points"} <= sensor._unrecorded_attributes
    assert state.attributes["control_points"]  # still available for the card


# ---------------------------------------------------------------- F-01
@pytest.mark.usefixtures("evening")
async def test_f01_setpoint_sensors_equal_the_sent_values(hass, no_frontend_registration):
    calls, _entry = await _light_on(hass)
    sent = calls_for(calls, "light.a")[-1].data
    assert hass.states.get(TARGET_B).state == str(sent["brightness_pct"])
    assert hass.states.get(TARGET_K).state == str(sent["color_temp_kelvin"])
    assert hass.states.get(TARGET_B).attributes["unit_of_measurement"] == "%"
    assert hass.states.get(TARGET_K).attributes["unit_of_measurement"] == "K"
    assert "state_class" not in hass.states.get(TARGET_B).attributes  # no long-term statistics


@pytest.mark.usefixtures("evening")
async def test_f01_setpoint_sensors_follow_scenarios(hass, no_frontend_registration):
    await _light_on(hass)
    await select_scenario(hass, "focus")
    assert (hass.states.get(TARGET_B).state, hass.states.get(TARGET_K).state) == ("100", "5500")
    await select_scenario(hass, "guest")
    assert hass.states.get(TARGET_B).state == "unknown"
    await select_scenario(hass, "sleep")
    assert hass.states.get(TARGET_B).state == "0"


@pytest.mark.usefixtures("evening")
async def test_f01_setpoint_sensors_update_over_time(hass, no_frontend_registration, freezer):
    await _light_on(hass)
    before = hass.states.get(TARGET_B).state
    freezer.tick(timedelta(hours=1))  # 21:00, dimmer
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(TARGET_B).state != before


async def test_rm_f05_curve_sensor_names_its_instance(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    state = hass.states.get(SENSOR)
    assert state.attributes["instance"] == "HCL"
    # live value for the card, not stored in the history database
    assert "instance" in state.state_info["unrecorded_attributes"]


async def test_rm_f05_instance_follows_a_renamed_entry(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    hass.config_entries.async_update_entry(entry, title="Küche")
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).attributes["instance"] == "Küche"


# ---------------------------------------------------------------- RM-T10
async def test_rm_t10_switch_attributes_are_live_but_not_recorded(hass, no_frontend_registration):
    FakeLights(hass)
    for eid in ("light.c", "light.a", "light.b"):
        set_light(hass, eid, "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.c", "light.a", "light.b"])
    await hcl_on(hass)
    state = hass.states.get(SWITCH)
    # still in the live state (automations, templates, card) ...
    assert UNRECORDED <= set(state.attributes)
    assert state.attributes["calculated_brightness"] is not None
    # ... but excluded from the history database
    assert UNRECORDED <= set(state.state_info["unrecorded_attributes"])


async def test_rm_t10_target_entities_are_sorted_and_stable(hass, no_frontend_registration):
    FakeLights(hass)
    lights = [f"light.l{n:02d}" for n in range(20, 0, -1)]
    for eid in lights:
        set_light(hass, eid, "off", **CT_ATTRS)
    await setup_entry(hass, lights)
    await hcl_on(hass)
    assert hass.states.get(SWITCH).attributes["target_entities"] == sorted(lights)
    changes = []
    unsub = hass.bus.async_listen(
        "state_changed", callback(lambda e: changes.append(e) if e.data["entity_id"] == SWITCH else None)
    )
    # resolving the same lights again (e.g. a registry update) changes nothing

    sw = switch_entity(hass)
    sw._resolved_targets = set(reversed(sorted(sw._resolved_targets)))
    sw.async_write_ha_state()
    await hass.async_block_till_done()
    unsub()
    assert changes == []


# ---------------------------------------------------------------- B-13
async def test_b13_curve_sensor_exposes_brightness_limits(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await setup_entry(hass, ["light.a"], options={CONF_MIN_BRIGHTNESS: 5, CONF_MAX_BRIGHTNESS: 60})
    attrs = hass.states.get("sensor.hcl_curve_data").attributes
    assert attrs["min_brightness"] == 5
    assert attrs["max_brightness"] == 60


# ---------------------------------------------------------------- B-26
async def test_b26_mode_select_belongs_to_hcl_device(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    set_light(hass, "light.b", "off", **CT_ATTRS)
    entry1 = await setup_entry(hass, ["light.a"])
    ent_reg = er.async_get(hass)

    def entities(entry):
        return {e.domain: e for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)}

    e1 = entities(entry1)
    assert e1["select"].device_id is not None
    assert e1["select"].device_id == e1["switch"].device_id == e1["sensor"].device_id
    assert e1["select"].entity_id == "select.hcl_scenario"


    entry2 = MockConfigEntry(domain=DOMAIN, title="Kitchen", data={"name": "Kitchen", "target": {"entity_id": ["light.b"]}})
    entry2.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry2.entry_id)
    await hass.async_block_till_done()
    e2 = entities(entry2)
    assert e2["select"].entity_id == "select.kitchen_scenario"
    assert e2["select"].device_id == e2["switch"].device_id
    # The curve sensor still finds its own mode select (used by the card).
    assert hass.states.get("sensor.kitchen_curve_data").attributes["mode_entity_id"] == "select.kitchen_scenario"


async def test_b26_existing_select_entity_id_is_kept(hass, no_frontend_registration):
    """Installations created before the fix keep their registered entity_id."""
    set_light(hass, "light.a", "off", **CT_ATTRS)

    entry = MockConfigEntry(domain=DOMAIN, title="HCL", data={"name": "HCL", "target": {"entity_id": ["light.a"]}})
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "select", DOMAIN, f"{entry.entry_id}_mode", suggested_object_id="mode", config_entry=entry
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("select.mode") is not None
    assert hass.states.get("sensor.hcl_curve_data").attributes["mode_entity_id"] == "select.mode"


# ---------------------------------------------------------------- B-27
async def test_b27_new_entry_exposes_mode_entity_id_immediately(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await setup_entry(hass, ["light.a"])  # first setup: select not yet in the registry
    assert hass.states.get("sensor.hcl_curve_data").attributes["mode_entity_id"] == "select.hcl_scenario"


async def test_b27_renamed_mode_select_is_followed(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    er.async_get(hass).async_update_entity("select.hcl_scenario", new_entity_id="select.wohnzimmer_hcl")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.hcl_curve_data").attributes["mode_entity_id"] == "select.wohnzimmer_hcl"


# ---------------------------------------------------------------- RM-R08
async def test_rm_r08_curve_sensor_has_the_default_curve_of_the_anchor_times(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await setup_entry(hass, ["light.a"], options={"wake_time": "06:15:00", "sleep_time": "23:00:00"})
    attrs = hass.states.get(SENSOR).attributes
    assert attrs["default_points"] == default_points("06:15", "23:00")
    assert "default_points" in HCLLightingCurveSensor._unrecorded_attributes


# ---------------------------------------------------------------- RM-T21
async def test_rm_t21_entities_share_one_device_and_take_their_icons_from_icons_json(hass, no_frontend_registration):
    import json
    from pathlib import Path

    from homeassistant.helpers import device_registry as dr

    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) == 7
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1 and devices[0].identifiers == {(DOMAIN, entry.entry_id)}
    assert {e.device_id for e in entities} == {devices[0].id}
    icons = json.loads(
        (Path(__file__).parents[1] / "custom_components" / DOMAIN / "icons.json").read_text(encoding="utf-8")
    )["entity"]
    for e in entities:
        assert e.original_icon is None, e.entity_id  # no icon in the code
        if e.translation_key != "hcl_curve_sensor":  # timestamp sensor: icon of its device class
            assert icons[e.domain][e.translation_key]["default"].startswith("mdi:"), e.entity_id
