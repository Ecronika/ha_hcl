"""Tests for release 0.7.0 (F-01, Ä-04, Ä-05, Ä-07, Ä-18, B-41 …)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

from custom_components.hcl_lighting.const import DOMAIN
from custom_components.hcl_lighting.logic.hcl_math import HCLCalculator

from .helpers import CT_ATTRS, core, set_light, setup_entry, switch_entity

SWITCH = "switch.hcl_hcl_active"
SELECT = "select.hcl_scenario"
TARGET_B = "sensor.hcl_target_brightness"
TARGET_K = "sensor.hcl_target_colour_temperature"


@pytest.fixture(autouse=True)
def _evening(freezer):
    """20:00: the default curve asks for 17 % / 2337 K."""
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


async def _light_on(hass, options=None):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options=options)
    await _hcl_on(hass)
    return calls, entry


# ---------------------------------------------------------------- F-01
async def test_f01_setpoint_sensors_equal_the_sent_values(hass, no_frontend_registration):
    calls, _entry = await _light_on(hass)
    sent = _calls_for(calls, "light.a")[-1].data
    assert hass.states.get(TARGET_B).state == str(sent["brightness_pct"])
    assert hass.states.get(TARGET_K).state == str(sent["color_temp_kelvin"])
    assert hass.states.get(TARGET_B).attributes["unit_of_measurement"] == "%"
    assert hass.states.get(TARGET_K).attributes["unit_of_measurement"] == "K"
    assert "state_class" not in hass.states.get(TARGET_B).attributes  # no long-term statistics


async def test_f01_setpoint_sensors_follow_scenarios(hass, no_frontend_registration):
    await _light_on(hass)
    await _select(hass, "focus")
    assert (hass.states.get(TARGET_B).state, hass.states.get(TARGET_K).state) == ("100", "5500")
    await _select(hass, "guest")
    assert hass.states.get(TARGET_B).state == "unknown"
    await _select(hass, "sleep")
    assert hass.states.get(TARGET_B).state == "0"


async def test_f01_setpoint_sensors_update_over_time(hass, no_frontend_registration, freezer):
    await _light_on(hass)
    before = hass.states.get(TARGET_B).state
    freezer.tick(timedelta(hours=1))  # 21:00, dimmer
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(TARGET_B).state != before


# ---------------------------------------------------------------- Ä-05
def _calc_at(hour, minute, min_b, max_b, scale):
    calc = HCLCalculator()
    return calc.get_hcl_values(datetime(2026, 1, 1, hour, minute), min_b, max_b, scale=scale)[0]


def test_a05_scaling_maps_curve_range_onto_min_max():
    # default curve: 20:00 = 17 %, 11:00 = 100 %, 12:30 = 50 %
    assert _calc_at(20, 0, 20, 60, scale=False) == 20      # clipped
    assert _calc_at(20, 0, 20, 60, scale=True) == 23       # 20 + 7 * 40/90
    assert _calc_at(12, 30, 20, 60, scale=False) == 50
    assert _calc_at(12, 30, 20, 60, scale=True) == 38      # 20 + 40 * 40/90, dip is kept
    assert _calc_at(11, 0, 20, 60, scale=True) == 60


def test_a05_scaling_with_default_limits_changes_nothing():
    for hour in range(24):
        assert _calc_at(hour, 0, 10, 100, scale=True) == _calc_at(hour, 0, 10, 100, scale=False)


async def test_a05_option_reaches_the_lights(hass, no_frontend_registration):
    calls, _entry = await _light_on(
        hass, options={"min_brightness": 20, "max_brightness": 60, "brightness_scaling": True}
    )
    assert _calls_for(calls, "light.a")[-1].data["brightness_pct"] == 23
    attrs = hass.states.get("sensor.hcl_curve_data").attributes
    assert attrs["brightness_scaling"] is True
    assert max(s[2] for s in attrs["samples"]) == 60


# ---------------------------------------------------------------- Ä-07 / B-15
async def test_a07_scenarios_within_limits_when_enabled(hass, no_frontend_registration):
    calls, _entry = await _light_on(
        hass, options={"min_brightness": 50, "max_brightness": 60, "scenario_limits": True}
    )
    await _select(hass, "focus")
    assert _calls_for(calls, "light.a")[-1].data["brightness_pct"] == 60
    await _select(hass, "relax")
    assert _calls_for(calls, "light.a")[-1].data["brightness_pct"] == 50
    scenarios = hass.states.get("sensor.hcl_curve_data").attributes["scenarios"]
    assert scenarios["focus"]["b"] == 60 and scenarios["night_light"]["b"] == 3


async def test_a07_scenarios_unlimited_by_default(hass, no_frontend_registration):
    calls, _entry = await _light_on(hass, options={"min_brightness": 50, "max_brightness": 60})
    await _select(hass, "focus")
    assert _calls_for(calls, "light.a")[-1].data["brightness_pct"] == 100


# ---------------------------------------------------------------- Ä-18
async def test_a18_scenario_change_uses_the_update_transition_by_default(hass, no_frontend_registration):
    calls, _entry = await _light_on(hass)
    await _select(hass, "focus")
    assert _calls_for(calls, "light.a")[-1].data["transition"] == 20


async def test_a18_scenario_transition_option(hass, no_frontend_registration):
    calls, _entry = await _light_on(hass, options={"scenario_transition": 2})
    await _select(hass, "focus")
    assert _calls_for(calls, "light.a")[-1].data["transition"] == 2


async def test_a18_long_scenario_transition_is_not_cut_short(hass, no_frontend_registration, freezer):
    calls, _entry = await _light_on(hass, options={"scenario_transition": 120})
    await _select(hass, "relax")
    assert _calls_for(calls, "light.a")[-1].data["transition"] == 120
    calls.clear()
    sw = switch_entity(hass)
    freezer.tick(timedelta(seconds=30))
    await sw._update_hcl()
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.a") == []


async def test_a18_restore_after_reload_is_no_scenario_change(hass, no_frontend_registration):
    calls, entry = await _light_on(hass, options={"scenario_transition": 2})
    await _select(hass, "focus")
    set_light(hass, "light.a", "on", brightness=10, color_temp_kelvin=3000, **CT_ATTRS)
    await hass.async_block_till_done()
    core(hass, entry)["override_manager"].reset_override("light.a")  # the change above is no manual control here
    calls.clear()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.a")[-1].data["transition"] == 20


# ---------------------------------------------------------------- Ä-04 night light
async def test_a04_night_light_dims_lights_that_are_on(hass, no_frontend_registration):
    calls, _entry = await _light_on(hass)
    await _select(hass, "night_light")
    data = _calls_for(calls, "light.a")[-1].data
    assert (data["brightness_pct"], data["color_temp_kelvin"]) == (3, 2200)
    assert all(c.service == "turn_on" for c in calls)


async def test_a04_light_switched_on_in_night_light_gets_night_values(hass, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
    await _select(hass, "night_light")
    calls.clear()
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=4000, **CT_ATTRS)
    await hass.async_block_till_done()
    data = _calls_for(calls, "light.a")[-1].data
    assert (data["brightness_pct"], data["color_temp_kelvin"]) == (3, 2200)
    assert not core(hass, entry)["override_manager"].is_overridden("light.a")


async def test_a04_night_light_values_are_configurable(hass, no_frontend_registration):
    calls, _entry = await _light_on(hass, options={"night_light_brightness": 8, "night_light_kelvin": 2000})
    await _select(hass, "night_light")
    data = _calls_for(calls, "light.a")[-1].data
    assert (data["brightness_pct"], data["color_temp_kelvin"]) == (8, 2000)


async def test_a04_night_modes_end_at_wake_time_when_enabled(hass, no_frontend_registration, freezer):
    await _light_on(hass, options={"night_end_at_wake": True})
    await _select(hass, "sleep")
    until = dt_util.parse_datetime(hass.states.get(SELECT).attributes["until"])
    assert dt_util.as_local(until).hour == 7 and until > dt_util.utcnow()
    freezer.move_to(until + timedelta(seconds=1))
    async_fire_time_changed(hass, until + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "auto"


async def test_a04_night_modes_stay_by_default(hass, no_frontend_registration):
    await _light_on(hass)
    await _select(hass, "night_light")
    assert hass.states.get(SELECT).attributes["until"] is None


# ---------------------------------------------------------------- B-41
def test_b41_midnight_24_00_is_the_same_moment_as_00_00():
    calc = HCLCalculator()
    calc.calculate_curve_from_points(
        [{"t": 540, "b": 20, "k": 2700}, {"t": 1200, "b": 21, "k": 2700}, {"t": 1440, "b": 5, "k": 2200}]
    )
    assert [p["t"] for p in calc.active_curve] == [0, 540, 1200]
    # 00:00 is exactly the point value (before 0.7.0 the curve was extrapolated here)
    assert calc.get_hcl_values(datetime(2026, 1, 1, 0, 0), 1, 100) == (5, 2200)


def test_b41_stored_contradictory_midnight_points_keep_the_00_00_value():
    calc = HCLCalculator()
    calc.calculate_curve_from_points(
        [{"t": 0, "b": 10, "k": 2200}, {"t": 720, "b": 50, "k": 4000}, {"t": 1440, "b": 90, "k": 6500}]
    )
    assert [p["t"] for p in calc.active_curve] == [0, 720]
    assert calc.get_hcl_values(datetime(2026, 1, 1, 0, 0), 1, 100) == (10, 2200)


async def test_b41_service_rejects_contradictory_midnight_points(hass, no_frontend_registration):
    await setup_entry(hass, ["light.a"])
    points = [{"t": 0, "b": 10, "k": 2200}, {"t": 720, "b": 50, "k": 4000}, {"t": 1440, "b": 90, "k": 6500}]
    with pytest.raises((vol.Invalid, HomeAssistantError)):
        await hass.services.async_call(
            DOMAIN, "update_curve",
            {"entity_id": "sensor.hcl_curve_data", "mode": "preview", "points": points}, blocking=True,
        )
    same = [{"t": 0, "b": 10, "k": 2200}, {"t": 720, "b": 50, "k": 4000}, {"t": 1440, "b": 10, "k": 2200}]
    await hass.services.async_call(
        DOMAIN, "update_curve",
        {"entity_id": "sensor.hcl_curve_data", "mode": "preview", "points": same}, blocking=True,
    )
    await hass.async_block_till_done()
    assert [p["t"] for p in hass.states.get("sensor.hcl_curve_data").attributes["control_points"]] == [0, 720]


# ---------------------------------------------------------------- F-02 services
async def test_f02_apply_sends_now_and_never_switches_on(hass, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    set_light(hass, "light.b", "off", **CT_ATTRS)
    await setup_entry(hass, ["light.a", "light.b"])
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SELECT, "transition": 1}, blocking=True)
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.a")[-1].data["transition"] == 1
    assert _calls_for(calls, "light.b") == []


async def test_f02_apply_skips_or_releases_manual_control(hass, no_frontend_registration):
    calls, entry = await _light_on(hass)
    om = core(hass, entry)["override_manager"]
    om.set_override("light.a")
    calls.clear()
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH}, blocking=True)
    assert _calls_for(calls, "light.a") == []
    await hass.services.async_call(
        DOMAIN, "apply", {"entity_id": SWITCH, "release_manual_control": True}, blocking=True
    )
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.a") and not om.is_overridden("light.a")


async def test_f02_apply_rejects_foreign_lights_and_guest_mode(hass, no_frontend_registration):
    from homeassistant.exceptions import ServiceValidationError

    await _light_on(hass)
    # ServiceNotFound is a ServiceValidationError too: check the messages
    with pytest.raises(ServiceValidationError, match="Not controlled by this HCL instance: light.other"):
        await hass.services.async_call(
            DOMAIN, "apply", {"entity_id": SWITCH, "lights": ["light.other"]}, blocking=True
        )
    await _select(hass, "guest")
    with pytest.raises(ServiceValidationError, match="Guest mode"):
        await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH}, blocking=True)
    with pytest.raises(ServiceValidationError, match="is not an HCL Lighting entity"):
        await hass.services.async_call(DOMAIN, "apply", {"entity_id": "light.a"}, blocking=True)


async def test_f02_set_manual_control(hass, no_frontend_registration):
    calls, entry = await _light_on(hass)
    om = core(hass, entry)["override_manager"]
    await hass.services.async_call(
        DOMAIN, "set_manual_control", {"entity_id": SWITCH, "lights": ["light.a"]}, blocking=True
    )
    assert om.is_overridden("light.a")
    assert hass.states.get(SWITCH).attributes["manual_control"] == ["light.a"]
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    calls.clear()
    await hass.services.async_call(
        DOMAIN, "set_manual_control", {"entity_id": SWITCH, "manual_control": False}, blocking=True
    )
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")
    assert _calls_for(calls, "light.a")  # follows HCL again right away


async def test_f02_set_scenario_with_duration(hass, no_frontend_registration, freezer):
    await _light_on(hass)
    await hass.services.async_call(
        DOMAIN, "set_scenario", {"entity_id": SWITCH, "scenario": "focus", "duration": 30}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "focus"
    assert hass.states.get(SELECT).attributes["until"] is not None
    later = dt_util.utcnow() + timedelta(minutes=31)
    freezer.move_to(later)
    async_fire_time_changed(hass, later)
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "auto"


async def test_f02_get_curve_returns_points(hass, no_frontend_registration):
    await setup_entry(hass, ["light.a"])
    result = await hass.services.async_call(
        DOMAIN, "get_curve", {"entity_id": SELECT}, blocking=True, return_response=True
    )
    assert len(result["points"]) == 12 and result["saved_points"] is None
    assert (result["wake_time"], result["sleep_time"], result["preview_active"]) == ("07:00", "22:00", False)


# ---------------------------------------------------------------- F-07 event, logbook, diagnostics
async def test_f07_manual_control_fires_events(hass, no_frontend_registration):
    events = []
    hass.bus.async_listen("hcl_lighting_manual_control", events.append)
    _calls, entry = await _light_on(hass)
    om = core(hass, entry)["override_manager"]
    om.set_override("light.a")
    om.set_override("light.a")  # no second event without change
    om.reset_override("light.a")
    await hass.async_block_till_done()
    assert [(e.data["entity_id"], e.data["manual_control"]) for e in events] == [
        ("light.a", True), ("light.a", False)
    ]
    assert events[0].data["instance"] == "HCL"


async def test_f07_logbook_describes_the_event(hass, no_frontend_registration):
    from custom_components.hcl_lighting import logbook as hcl_logbook
    from homeassistant.core import Event

    described = {}
    hcl_logbook.async_describe_events(hass, lambda domain, event, fn: described.setdefault(event, fn))
    fn = described["hcl_lighting_manual_control"]
    entry = fn(Event("hcl_lighting_manual_control", {"entity_id": "light.a", "manual_control": True, "instance": "Wohnen"}))
    assert entry["entity_id"] == "light.a" and entry["name"] == "HCL Wohnen" and entry["message"]


async def test_f07_diagnostics(hass, no_frontend_registration):
    from custom_components.hcl_lighting.diagnostics import async_get_config_entry_diagnostics

    _calls, entry = await _light_on(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["targets"] == ["light.a"]
    assert diag["lights"]["light.a"]["capability"] == "ct"
    assert diag["setpoint"]["brightness"] == 17 and diag["scenario"] == "auto"


# ---------------------------------------------------------------- Ä-20 card hint
async def test_a20_card_hint_is_a_one_time_notification(hass, no_frontend_registration):
    from homeassistant.components import persistent_notification
    from homeassistant.helpers import issue_registry as ir

    entry = await setup_entry(hass, ["light.a"])
    notifications = persistent_notification._async_get_or_create_notifications(hass)
    nid = f"{DOMAIN}_card_{entry.entry_id}"
    assert "sensor.hcl_curve_data" in notifications[nid]["message"]
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"setup_curve_card_{entry.entry_id}") is None
    persistent_notification.async_dismiss(hass, nid)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert nid not in notifications


async def test_a20_upgrade_removes_the_old_repair_issue_without_new_hint(hass, no_frontend_registration):
    from homeassistant.components import persistent_notification
    from homeassistant.helpers import issue_registry as ir
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain=DOMAIN, title="HCL", data={"name": "HCL", "target": {"entity_id": ["light.a"]}})
    entry.add_to_hass(hass)
    ir.async_create_issue(
        hass, DOMAIN, f"setup_curve_card_{entry.entry_id}", is_fixable=False,
        severity=ir.IssueSeverity.WARNING, translation_key="setup_curve_card",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"setup_curve_card_{entry.entry_id}") is None
    assert f"{DOMAIN}_card_{entry.entry_id}" not in persistent_notification._async_get_or_create_notifications(hass)


# ---------------------------------------------------------------- F-08 conflicts
async def _two_instances(hass, lights_a, lights_b):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    async_mock_service(hass, "light", "turn_on")
    entries = []
    for title, lights in (("A", lights_a), ("B", lights_b)):
        entry = MockConfigEntry(domain=DOMAIN, title=title, data={"name": title, "target": {"entity_id": lights}})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entries.append(entry)
    for entity_id in ("switch.a_hcl_active", "switch.b_hcl_active"):
        await hass.services.async_call("switch", "turn_on", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()
    return entries


async def test_f08_light_in_two_instances_raises_a_repair_issue(hass, no_frontend_registration):
    from homeassistant.helpers import issue_registry as ir

    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    set_light(hass, "light.b", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    await _two_instances(hass, ["light.a"], ["light.a", "light.b"])
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "light_in_multiple_instances_light.a")
    assert issue is not None and issue.translation_placeholders["instances"] == "A, B"
    assert ir.async_get(hass).async_get_issue(DOMAIN, "light_in_multiple_instances_light.b") is None
    # brightness in A, colour in B is allowed
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.a_adapt_colour_temperature"}, blocking=True)
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.b_adapt_brightness"}, blocking=True)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "light_in_multiple_instances_light.a") is None


async def test_f08_issue_disappears_when_an_instance_is_off(hass, no_frontend_registration):
    from homeassistant.helpers import issue_registry as ir

    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    await _two_instances(hass, ["light.a"], ["light.a"])
    assert ir.async_get(hass).async_get_issue(DOMAIN, "light_in_multiple_instances_light.a") is not None
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.b_hcl_active"}, blocking=True)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "light_in_multiple_instances_light.a") is None


# ---------------------------------------------------------------- B-11 group members
async def test_b11_changed_group_members_are_picked_up(hass, no_frontend_registration, freezer):
    async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    set_light(hass, "light.b", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    hass.states.async_set("light.grp", "on", {"entity_id": ["light.a"], **CT_ATTRS})
    await setup_entry(hass, ["light.grp"])
    await _hcl_on(hass)
    sw = switch_entity(hass)
    assert sw.resolved_targets == {"light.a"}
    hass.states.async_set("light.grp", "on", {"entity_id": ["light.a", "light.b"], **CT_ATTRS})
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert sw.resolved_targets == {"light.a", "light.b"}


# ---------------------------------------------------------------- B-52 / Ä-26 registration
async def test_b52_missing_lovelace_is_retried_and_version_from_manifest(hass):
    import json
    from pathlib import Path
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.hcl_lighting import _async_register_lovelace_resource

    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    assert await _async_register_lovelace_resource(hass) is False  # no Lovelace yet
    collection = MagicMock()
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    collection.__class__ = ResourceStorageCollection
    collection.async_get_info = AsyncMock()
    collection.async_items = MagicMock(return_value=[
        {"id": "old", "type": "module", "url": "/hcl_lighting_static/hcl-curve-card.js?v=0.6.1"}
    ])
    collection.async_update_item = AsyncMock()
    collection.async_create_item = AsyncMock()
    collection.async_delete_item = AsyncMock()
    hass.data["lovelace"] = MagicMock(resources=collection)
    assert await _async_register_lovelace_resource(hass) is True
    version = json.loads((Path(__file__).parents[1] / "custom_components/hcl_lighting/manifest.json").read_text())["version"]
    collection.async_update_item.assert_awaited_once_with(
        "old", {"res_type": "module", "url": f"/hcl_lighting_static/hcl-curve-card.js?v={version}"}
    )
    collection.async_create_item.assert_not_awaited()
    collection.async_delete_item.assert_not_awaited()
    assert hass.http.async_register_static_paths.await_count == 1


async def test_b52_failed_registration_is_not_marked_done(hass):
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.hcl_lighting import _async_register_lovelace_resource
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    collection = MagicMock()
    collection.__class__ = ResourceStorageCollection
    collection.async_get_info = AsyncMock()
    collection.async_items = MagicMock(return_value=[])
    collection.async_create_item = AsyncMock(side_effect=RuntimeError("storage"))
    hass.data["lovelace"] = MagicMock(resources=collection)
    assert await _async_register_lovelace_resource(hass) is False
    collection.async_create_item = AsyncMock(return_value={"id": "new"})
    assert await _async_register_lovelace_resource(hass) is True
