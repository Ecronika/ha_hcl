"""Tests for the changes of release 0.6.0 (review items Ä-xx)."""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
    mock_restore_cache,
    mock_restore_cache_with_extra_data,
)

from custom_components.hcl_lighting import DATA_OVERRIDE_MANAGERS
from custom_components.hcl_lighting.const import DOMAIN

from .helpers import CT_ATTRS, core, set_light, setup_entry, switch_entity

COMPONENT = Path(__file__).parent.parent / "custom_components" / "hcl_lighting"
SWITCH = "switch.hcl_hcl_active"
SELECT = "select.hcl_scenario"
ADAPT_B = "switch.hcl_adapt_brightness"
ADAPT_K = "switch.hcl_adapt_colour_temperature"


def _calls_for(calls, entity_id):
    out = []
    for c in calls:
        ids = c.data.get("entity_id")
        ids = [ids] if isinstance(ids, str) else list(ids or [])
        if entity_id in ids:
            out.append(c)
    return out


@pytest.fixture
async def noon(hass: HomeAssistant, freezer):
    """11:00 Europe/Berlin (curve plateau: 100 % / 6500 K)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-01-15 10:00:00+00:00")
    return freezer


async def _user_turn_on(hass, **data):
    """A light command from outside HCL (app, scene, automation)."""
    await hass.services.async_call("light", "turn_on", data, blocking=True)
    await hass.async_block_till_done()


async def _active(hass, entry, lights=("light.a",), **options):
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    await switch_entity(hass).async_turn_on()
    await hass.async_block_till_done()
    return core(hass, entry)


# ------------------------------------------------------------------ Ä-01
async def test_a01_ha_command_with_values_pauses_light(hass, noon, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    sw = switch_entity(hass)
    await sw.async_turn_on()
    await hass.async_block_till_done()
    om = core(hass, entry)["override_manager"]
    assert not om.is_overridden("light.a"), "HCL's own commands are no manual control"

    # Inside the ignore window, towards the HCL target: previously undetectable
    await _user_turn_on(hass, entity_id="light.a", brightness_pct=90)
    assert om.is_overridden("light.a")
    calls.clear()
    await sw._update_hcl()
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.a") == []
    assert hass.states.get(SWITCH).attributes["manual_control"] == ["light.a"]


async def test_a01_area_target_and_toggle_and_plain_turn_on(hass, noon, no_frontend_registration):
    async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "light", "toggle")
    area = ar.async_get(hass).async_create("Wohnen")
    ent = er.async_get(hass).async_get_or_create("light", "test", "1", suggested_object_id="a")
    er.async_get(hass).async_update_entity(ent.entity_id, area_id=area.id)
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    set_light(hass, "light.other", "on", brightness=128, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await switch_entity(hass).async_turn_on()
    om = core(hass, entry)["override_manager"]

    await _user_turn_on(hass, entity_id="light.a")  # no values
    await hass.services.async_call("light", "toggle", {"entity_id": "light.a", "brightness_pct": 5}, blocking=True)
    await _user_turn_on(hass, entity_id="light.other", brightness_pct=5)  # not an HCL light
    assert not om.is_overridden("light.a")

    await _user_turn_on(hass, area_id=area.id, color_temp_kelvin=2700)
    assert om.is_overridden("light.a")


async def test_a01_turn_on_values_default_and_option(hass, noon, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await switch_entity(hass).async_turn_on()
    # Default (unchanged behaviour): HCL values are applied on turn-on
    await _user_turn_on(hass, entity_id="light.a", brightness_pct=5)
    set_light(hass, "light.a", "on", brightness=13, color_temp_kelvin=2200, **CT_ATTRS)
    await hass.async_block_till_done()
    fast = [c for c in _calls_for(calls, "light.a") if c.data.get("brightness_pct") == 100]
    assert fast, "fast path must still apply HCL by default"
    assert not core(hass, entry)["override_manager"].is_overridden("light.a")

    # Option: keep the values of turn-on commands
    set_light(hass, "light.a", "off", **CT_ATTRS)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "respect_turn_on_values": True})
    await hass.async_block_till_done()
    calls.clear()
    await _user_turn_on(hass, entity_id="light.a", brightness_pct=5)
    set_light(hass, "light.a", "on", brightness=13, color_temp_kelvin=2200, **CT_ATTRS)
    await hass.async_block_till_done()
    assert [c for c in _calls_for(calls, "light.a") if c.data.get("brightness_pct") == 100] == []
    assert core(hass, entry)["override_manager"].is_overridden("light.a")


# ------------------------------------------------------------------ Ä-02
async def test_a02_adapt_switches_filter_commands(hass, noon, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    assert hass.states.get(ADAPT_B).state == "on" and hass.states.get(ADAPT_K).state == "on"
    sw = switch_entity(hass)

    await hass.services.async_call("switch", "turn_off", {"entity_id": ADAPT_B}, blocking=True)
    await sw.async_turn_on()
    await hass.async_block_till_done()
    sent = _calls_for(calls, "light.a")
    assert sent and all("brightness_pct" not in c.data for c in sent)
    assert sent[-1].data["color_temp_kelvin"] == 6500

    calls.clear()
    await hass.services.async_call("switch", "turn_on", {"entity_id": ADAPT_B}, blocking=True)
    await hass.services.async_call("switch", "turn_off", {"entity_id": ADAPT_K}, blocking=True)
    await hass.async_block_till_done()
    sent = _calls_for(calls, "light.a")
    assert sent and all("color_temp_kelvin" not in c.data for c in sent)
    assert sent[-1].data["brightness_pct"] == 100

    calls.clear()
    await hass.services.async_call("switch", "turn_off", {"entity_id": ADAPT_B}, blocking=True)
    await sw._update_hcl()
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.a") == []


async def test_a02_brightness_change_is_no_override_when_not_adapted(hass, noon, no_frontend_registration):
    async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hass.services.async_call("switch", "turn_off", {"entity_id": ADAPT_B}, blocking=True)
    await switch_entity(hass).async_turn_on()
    om = core(hass, entry)["override_manager"]
    await _user_turn_on(hass, entity_id="light.a", brightness_pct=30)
    noon.tick(timedelta(seconds=60))
    set_light(hass, "light.a", "on", brightness=77, color_temp_kelvin=6500, **CT_ATTRS)
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")
    await _user_turn_on(hass, entity_id="light.a", color_temp_kelvin=2700)
    assert om.is_overridden("light.a")


async def test_a02_sleep_still_switches_off_without_brightness_adaptation(hass, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=2700, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    await hass.services.async_call("switch", "turn_off", {"entity_id": ADAPT_B}, blocking=True)
    await switch_entity(hass).async_turn_on()
    calls.clear()
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "sleep"}, blocking=True)
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.a")[-1].data["brightness_pct"] == 0


async def test_a02_flags_survive_reload_and_restart(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    # Restart: the entity is registered and its last state was stored
    entry = MockConfigEntry(domain=DOMAIN, title="HCL", data={"name": "HCL", "target": {"entity_id": ["light.a"]}})
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "switch", DOMAIN, f"{entry.entry_id}_adapt_color",
        suggested_object_id="hcl_adapt_colour_temperature", config_entry=entry,
    )
    mock_restore_cache(hass, [State(ADAPT_K, "off")])
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert core(hass, entry)["controller"].adapt_color is False  # restart
    assert hass.states.get(ADAPT_K).state == "off"
    await hass.services.async_call("switch", "turn_off", {"entity_id": ADAPT_B}, blocking=True)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "max_brightness": 90})
    await hass.async_block_till_done()
    ctl = core(hass, entry)["controller"]
    assert ctl.adapt_brightness is False and ctl.adapt_color is False  # reload


# ------------------------------------------------------------------ Ä-06
async def test_a06_timeout_option_and_never(hass, noon, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"override_timeout": 30})
    sw = switch_entity(hass)
    await sw.async_turn_on()
    om = core(hass, entry)["override_manager"]
    om.set_override("light.a")
    noon.tick(timedelta(minutes=20))
    calls.clear()
    await sw._update_hcl()
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.a") == []
    noon.tick(timedelta(minutes=11))
    await sw._update_hcl()
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a") and _calls_for(calls, "light.a")

    hass.config_entries.async_update_entry(entry, options={**entry.options, "override_timeout": 0})
    await hass.async_block_till_done()
    om = core(hass, entry)["override_manager"]
    om.set_override("light.a")
    noon.tick(timedelta(days=2))
    await switch_entity(hass)._update_hcl()
    assert om.is_overridden("light.a")


async def test_a06_reset_on_off_disabled(hass, noon, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"override_reset_on_off": False})
    await switch_entity(hass).async_turn_on()
    om = core(hass, entry)["override_manager"]
    om.set_override("light.a")
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await hass.async_block_till_done()
    assert om.is_overridden("light.a")
    calls.clear()
    set_light(hass, "light.a", "on", brightness=20, color_temp_kelvin=3000, **CT_ATTRS)
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.a") == [], "paused light keeps its own values when switched on"


async def test_a06_default_reset_on_off_and_off_lights_cleared(hass, noon, no_frontend_registration):
    async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    sw = switch_entity(hass)
    await sw.async_turn_on()
    om = core(hass, entry)["override_manager"]
    om.set_override("light.a")
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).attributes["manual_control"] == ["light.a"]
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")
    assert hass.states.get(SWITCH).attributes["manual_control"] == []
    # A pause for a light that is off (switch-off not seen) is cleared by the cycle
    om.set_override("light.a")
    await sw._update_hcl()
    assert not om.is_overridden("light.a")


async def test_a06_persist_across_restart(hass, hass_storage, no_frontend_registration):
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"persist_overrides": True})
    core(hass, entry)["override_manager"].set_override("light.a")
    await hass.config_entries.async_unload(entry.entry_id)
    hass.bus.async_fire("homeassistant_final_write")
    await hass.async_block_till_done()
    assert f"{DOMAIN}.overrides.{entry.entry_id}" in hass_storage
    hass.data[DATA_OVERRIDE_MANAGERS].pop(entry.entry_id)  # restart: in-memory state gone
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert core(hass, entry)["override_manager"].is_overridden("light.a")


async def test_a06_no_persistence_by_default(hass, hass_storage, no_frontend_registration):
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    core(hass, entry)["override_manager"].set_override("light.a")
    await hass.config_entries.async_unload(entry.entry_id)
    hass.data[DATA_OVERRIDE_MANAGERS].pop(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert not core(hass, entry)["override_manager"].is_overridden("light.a")


# ------------------------------------------------------------------ Ä-07
async def test_a07_configured_scenario_values(hass, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    await setup_entry(hass, ["light.a"], options={"focus_brightness": 80, "focus_kelvin": 5000})
    await switch_entity(hass).async_turn_on()
    calls.clear()
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "focus"}, blocking=True)
    await hass.async_block_till_done()
    last = _calls_for(calls, "light.a")[-1].data
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


# ------------------------------------------------------------------ Ä-11
async def test_a11_interval_and_transitions(hass, noon, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    await setup_entry(
        hass, ["light.a"], options={"update_interval": 60, "transition": 5, "turn_on_transition": 2}
    )
    await switch_entity(hass).async_turn_on()
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.a")[-1].data["transition"] == 5
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)  # drift away
    calls.clear()
    noon.tick(timedelta(seconds=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.a") == []
    noon.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.a")
    calls.clear()
    set_light(hass, "light.a", "off", **CT_ATTRS)
    set_light(hass, "light.a", "on", brightness=13, color_temp_kelvin=2200, **CT_ATTRS)
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.a")[-1].data["transition"] == 2


async def test_a11_options_flow_validation_and_steps(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    base = {"target": {"entity_id": ["light.a"]}, "wake_time": "07:00:00", "midday_time": "12:30:00",
            "sleep_time": "22:00:00", "smart_transition": False, "min_brightness": 10, "max_brightness": 100}
    result = await hass.config_entries.options.async_configure(flow["flow_id"], base)
    assert result["step_id"] == "behavior"
    bad = {"update_interval": 20, "transition": 20, "turn_on_transition": 0, "override_timeout": 240,
           "override_reset_on_off": True, "persist_overrides": False, "respect_turn_on_values": False}
    result = await hass.config_entries.options.async_configure(flow["flow_id"], bad)
    assert result["errors"] == {"base": "transition_too_long"}
    result = await hass.config_entries.options.async_configure(flow["flow_id"], {**bad, "transition": 10})
    assert result["step_id"] == "scenarios"
    result = await hass.config_entries.options.async_configure(flow["flow_id"], {"focus_brightness": 90})
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert entry.options["transition"] == 10 and entry.options["focus_brightness"] == 90
    assert entry.options["relax_kelvin"] == 2700  # defaults filled in


# ------------------------------------------------------------------ Ä-12
async def test_a12_setup_with_anchor_times(hass, no_frontend_registration):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert {"wake_time", "midday_time", "sleep_time"} <= {str(k) for k in result["data_schema"].schema}
    data = {"name": "Büro", "target": {"entity_id": ["light.a"]},
            "wake_time": "06:00:00", "midday_time": "12:00:00", "sleep_time": "09:00:00"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
    assert result["errors"] == {"base": "active_span_too_short"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**data, "sleep_time": "21:00:00"})
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    entry = result["result"]
    assert core(hass, entry)["calculator"].active_curve[0]["t"] == 360  # curve from the setup anchors


# ------------------------------------------------------------------ Ä-13
async def test_a13_new_light_in_target_area_is_picked_up(hass, freezer, no_frontend_registration):
    async_mock_service(hass, "light", "turn_on")
    area = ar.async_get(hass).async_create("Wohnen")
    entry = MockConfigEntry(domain=DOMAIN, title="HCL", data={"name": "HCL", "target": {"area_id": [area.id]}})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    sw = switch_entity(hass)
    await sw.async_turn_on()
    assert sw._resolved_targets == set()
    ent = er.async_get(hass).async_get_or_create("light", "test", "new", suggested_object_id="neu")
    set_light(hass, ent.entity_id, "on", brightness=10, **CT_ATTRS)
    er.async_get(hass).async_update_entity(ent.entity_id, area_id=area.id)
    freezer.tick(timedelta(seconds=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert sw._resolved_targets == {ent.entity_id}


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


# ------------------------------------------------------------------ Ä-15 / Ä-16
async def test_a15_service_registered_once_and_translated(hass, no_frontend_registration):
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    assert hass.services.has_service(DOMAIN, "update_curve")
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.services.has_service(DOMAIN, "update_curve")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "update_curve", {"entity_id": "sensor.hcl_curve_data", "mode": "revert"}, blocking=True
        )
    for name in ("en.json", "de.json"):
        data = json.loads((COMPONENT / "translations" / name).read_text(encoding="utf-8"))
        assert data["services"]["update_curve"]["name"]


async def test_a16_frontend_registered_once(hass):
    """Static path once per run; setup of further entries and reloads only check it."""
    from unittest.mock import AsyncMock
    from custom_components.hcl_lighting import _async_register_lovelace_resource

    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "http", {})
    hass.http.async_register_static_paths = AsyncMock()
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    hass.config_entries.async_update_entry(entry, options={"max_brightness": 90})  # reload
    await hass.async_block_till_done()
    second = MockConfigEntry(domain=DOMAIN, title="Zwei", data={"name": "Zwei", "target": {"entity_id": ["light.a"]}})
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()
    await _async_register_lovelace_resource(hass)
    assert hass.http.async_register_static_paths.await_count == 1