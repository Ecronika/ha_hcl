"""Saving, previewing and reverting the curve (update_curve, options) and its validation."""
from __future__ import annotations

import pytest
import voluptuous as vol

from datetime import datetime
from homeassistant.core import Context, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.hcl_lighting.const import CONF_CURVE_CONFIG, CONF_MAX_BRIGHTNESS, CONF_MIN_BRIGHTNESS, CONF_SLEEP_TIME, CONF_WAKE_TIME, DOMAIN
from custom_components.hcl_lighting.logic.hcl_math import HCLCalculator

from .support.curves import CUSTOM_POINTS
from .support.entries import CT_ATTRS, DIM, SENSOR, SWITCH, core, hcl_on, set_light, setup_entry
from .support.lights import FakeLights


async def _two_lights(hass, switch_on=True):
    lights = FakeLights(hass)
    for eid in ("light.a", "light.b"):
        set_light(hass, eid, "on", **DIM)
    entry = await setup_entry(hass, ["light.a", "light.b"])
    if switch_on:
        await hcl_on(hass)
    lights.calls.clear()
    return lights, entry


POINTS = [{"t": 0, "b": 20, "k": 2200}, {"t": 720, "b": 90, "k": 5500}, {"t": 1200, "b": 40, "k": 3000}]


def _hcl_entities(hass):

    return {e.entity_id for e in er.async_get(hass).entities.values() if e.platform == DOMAIN}


async def _run_options_flow(hass, entry, **changes):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    current = {
        "target": {"entity_id": ["light.a"]},
        CONF_WAKE_TIME: "07:00:00",
        CONF_SLEEP_TIME: "22:00:00",
        "smart_transition": False,
        CONF_MIN_BRIGHTNESS: 10,
        CONF_MAX_BRIGHTNESS: 100,
    }
    current.update(changes)
    result = await hass.config_entries.options.async_configure(result["flow_id"], current)
    # Steps "behavior" and "scenarios" with their defaults
    while result["type"] == "form" and result["step_id"] in ("behavior", "scenarios"):
        page = {"advanced": {}} if result["step_id"] == "behavior" else {}
        result = await hass.config_entries.options.async_configure(result["flow_id"], page)
    await hass.async_block_till_done()
    return result


# ---------------------------------------------------------------- B-37
@pytest.mark.usefixtures("evening")
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


# ---------------------------------------------------------------- B-41
@pytest.mark.usefixtures("evening")
def test_b41_stored_contradictory_midnight_points_keep_the_00_00_value():
    calc = HCLCalculator()
    calc.calculate_curve_from_points(
        [{"t": 0, "b": 10, "k": 2200}, {"t": 720, "b": 50, "k": 4000}, {"t": 1440, "b": 90, "k": 6500}]
    )
    assert [p["t"] for p in calc.active_curve] == [0, 720]
    assert calc.get_hcl_values(datetime(2026, 1, 1, 0, 0), 1, 100) == (10, 2200)


@pytest.mark.usefixtures("evening")
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


# ---------------------------------------------------------------- RM-H06
async def test_rm_h06_update_curve_reports_wrong_input_as_validation_error(
    hass, no_frontend_registration
):
    await _two_lights(hass)
    hass.states.async_set("sensor.other", "1")
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "update_curve", {"entity_id": "sensor.other", "mode": "revert"}, blocking=True
        )
    assert err.value.translation_key == "not_hcl_entity"
    assert str(err.value) == "sensor.other is not an HCL Lighting entity"


# ---------------------------------------------------------------- RM-B40
async def test_rm_b40_update_curve_stores_only_t_b_k(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    points = [dict(p) for p in CUSTOM_POINTS]
    points[0]["note"] = "x" * 50
    await hass.services.async_call(
        DOMAIN, "update_curve", {"entity_id": "sensor.hcl_curve_data", "mode": "save", "points": points},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_CURVE_CONFIG]["points"] == CUSTOM_POINTS


# ---------------------------------------------------------------- RM-T13
async def test_rm_t13_saving_the_curve_does_not_reload(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    calc = core(hass, entry)["calculator"]
    ours = _hcl_entities(hass)
    unavailable = []
    unsub = hass.bus.async_listen(
        "state_changed",
        callback(lambda e: unavailable.append(e.data["entity_id"])
                 if e.data["entity_id"] in ours and e.data["new_state"] is not None
                 and e.data["new_state"].state == "unavailable" else None),
    )
    reloads = []
    real_reload = hass.config_entries.async_reload

    async def _reload(entry_id):
        reloads.append(entry_id)
        return await real_reload(entry_id)

    hass.config_entries.async_reload = _reload
    lights.calls.clear()
    context = Context()
    await hass.services.async_call(
        DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": "save", "points": POINTS},
        blocking=True, context=context,
    )
    await hass.async_block_till_done()
    unsub()
    assert reloads == []
    assert unavailable == []
    # saved, active and shown
    assert entry.options[CONF_CURVE_CONFIG] == {"points": POINTS, "version": 2}
    assert calc.active_curve == POINTS
    assert calc.preview_active is False
    attrs = hass.states.get(SENSOR).attributes
    assert attrs["control_points"] == POINTS
    assert attrs["preview_active"] is False
    # the lights follow the saved curve at once (command linked to the call)
    assert lights.for_light("light.a")
    assert lights.for_light("light.a")[-1].context.parent_id == context.id


async def test_rm_t13_saved_curve_survives_a_reload(hass, no_frontend_registration):
    FakeLights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hass.services.async_call(
        DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": "save", "points": POINTS}, blocking=True
    )
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert core(hass, entry)["calculator"].active_curve == POINTS
    assert hass.states.get(SENSOR).attributes["control_points"] == POINTS


async def test_rm_t13_other_option_changes_still_reload(hass, no_frontend_registration):
    FakeLights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    first = core(hass, entry)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "transition": 7})
    await hass.async_block_till_done()
    assert core(hass, entry) is not first  # set up again
    # options and curve saved one after the other: the options still reload
    second = core(hass, entry)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "transition": 9})
    await hass.services.async_call(
        DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": "save", "points": POINTS}, blocking=True
    )
    await hass.async_block_till_done()
    assert core(hass, entry) is not second
    assert entry.options["transition"] == 9
    assert entry.options[CONF_CURVE_CONFIG]["points"] == POINTS
    assert core(hass, entry)["calculator"].active_curve == POINTS


async def test_rm_t13_save_ends_a_running_transition_protection(hass, no_frontend_registration):
    """Like the reload before (RM-B22): the saved curve reaches the light at once."""
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 120}, blocking=True)
    om = core(hass, entry)["override_manager"]
    assert om.is_reengaging("light.a")
    lights.calls.clear()
    await hass.services.async_call(
        DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": "save", "points": POINTS}, blocking=True
    )
    await hass.async_block_till_done()
    assert lights.for_light("light.a")
    assert not om.is_reengaging("light.a")


# ---------------------------------------------------------------- B-03
async def test_b03_options_save_keeps_custom_curve(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(
        hass,
        ["light.a"],
        options={
            CONF_WAKE_TIME: "07:00:00",
                CONF_SLEEP_TIME: "22:00:00",
            CONF_CURVE_CONFIG: {"points": CUSTOM_POINTS, "version": 2},
        },
    )
    await _run_options_flow(hass, entry, **{CONF_MAX_BRIGHTNESS: 80})
    assert entry.options[CONF_MAX_BRIGHTNESS] == 80
    assert entry.options.get(CONF_CURVE_CONFIG, {}).get("points") == CUSTOM_POINTS


async def test_b03_changed_anchor_times_regenerate_curve(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(
        hass,
        ["light.a"],
        options={
            CONF_WAKE_TIME: "07:00:00",
                CONF_SLEEP_TIME: "22:00:00",
            CONF_CURVE_CONFIG: {"points": CUSTOM_POINTS, "version": 2},
        },
    )
    await _run_options_flow(hass, entry, **{CONF_WAKE_TIME: "06:00:00"})
    assert CONF_CURVE_CONFIG not in entry.options
    curve = core(hass, entry)["calculator"].active_curve
    assert {"t": 360, "k": 3000, "b": 30} in curve  # regenerated from the new wake time


# ---------------------------------------------------------------- B-21
async def test_b21_update_curve_service_validates_input(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    for bad in (
        {"entity_id": "sensor.hcl_curve_data", "mode": "save"},  # no points
        {"entity_id": "sensor.hcl_curve_data", "mode": "save", "points": [{"t": 5000, "b": 50, "k": 3000}] * 2},
        {"entity_id": "sensor.hcl_curve_data", "mode": "preview", "points": [{"t": 60, "b": 50}]},
        {"entity_id": "sensor.hcl_curve_data", "mode": "bogus", "points": CUSTOM_POINTS},
    ):
        with pytest.raises((vol.Invalid, HomeAssistantError)):
            await hass.services.async_call(DOMAIN, "update_curve", bad, blocking=True)
    assert CONF_CURVE_CONFIG not in entry.options


async def test_b21_update_curve_valid_calls_still_work(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hass.services.async_call(
        DOMAIN, "update_curve", {"entity_id": "sensor.hcl_curve_data", "mode": "preview", "points": CUSTOM_POINTS}, blocking=True
    )
    await hass.services.async_call(DOMAIN, "update_curve", {"entity_id": "sensor.hcl_curve_data", "mode": "revert"}, blocking=True)
    await hass.services.async_call(
        DOMAIN, "update_curve", {"entity_id": "sensor.hcl_curve_data", "mode": "save", "points": CUSTOM_POINTS}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_CURVE_CONFIG]["points"] == CUSTOM_POINTS
