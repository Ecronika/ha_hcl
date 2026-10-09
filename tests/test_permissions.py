"""Permissions of the actions and the user of light commands."""
from __future__ import annotations

import pytest

from datetime import timedelta
from homeassistant.core import Context
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import area_registry as ar, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.hcl_lighting.const import DOMAIN

from .support.entries import ADAPT, CT_ATTRS, DIM, SELECT, SENSOR, SWITCH, core, hcl_on, set_light, setup_entry
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


def _user_without_light_b(user):
    """May use all HCL entities and light.a, not light.b."""
    user.mock_policy(
        {"entities": {"entity_ids": {SWITCH: True, SELECT: True, SENSOR: True, ADAPT: True, "light.a": True}}}
    )
    return Context(user_id=user.id)


# ---------------------------------------------------------------- RM-B31
@pytest.mark.parametrize(
    "service,data",
    [
        ("apply", {"entity_id": SWITCH}),
        ("set_scenario", {"entity_id": SELECT, "scenario": "focus"}),
        ("set_manual_control", {"entity_id": SWITCH, "manual_control": False}),
        # the release of one light runs an update of the whole instance
        ("set_manual_control", {"entity_id": SWITCH, "manual_control": False, "lights": ["light.a"]}),
        ("update_curve", {"entity_id": SENSOR, "mode": "revert"}),
    ],
)
async def test_rm_b31_actions_need_control_of_all_lights_they_drive(
    hass, no_frontend_registration, hass_read_only_user, service, data
):
    lights, _entry = await _two_lights(hass)
    ctx = _user_without_light_b(hass_read_only_user)
    with pytest.raises(Unauthorized):
        await hass.services.async_call(DOMAIN, service, data, blocking=True, context=ctx)
    await hass.async_block_till_done()
    assert lights.calls == []
    assert hass.states.get(SELECT).state == "auto"


async def test_rm_b31_pausing_needs_no_control_of_other_lights(
    hass, no_frontend_registration, hass_read_only_user
):
    """manual_control: true sends no light command."""
    lights, entry = await _two_lights(hass)
    ctx = _user_without_light_b(hass_read_only_user)
    await hass.services.async_call(
        DOMAIN, "set_manual_control", {"entity_id": SWITCH, "lights": ["light.a"]}, blocking=True, context=ctx
    )
    assert core(hass, entry)["override_manager"].is_overridden("light.a")


@pytest.mark.parametrize(
    "domain,service,entity_id,data",
    [
        ("select", "select_option", SELECT, {"option": "focus"}),
        ("switch", "turn_on", SWITCH, {}),
        ("switch", "turn_on", ADAPT, {}),
    ],
)
async def test_rm_b31_entity_actions_need_control_of_all_lights(
    hass, no_frontend_registration, hass_read_only_user, domain, service, entity_id, data
):
    lights, _entry = await _two_lights(hass, switch_on=False)
    await hass.services.async_call("switch", "turn_off", {"entity_id": ADAPT}, blocking=True)
    await hcl_on(hass) if entity_id != SWITCH else None
    lights.calls.clear()
    before = hass.states.get(entity_id).state
    ctx = _user_without_light_b(hass_read_only_user)
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            domain, service, {"entity_id": entity_id, **data}, blocking=True, context=ctx
        )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == before
    assert lights.calls == []


async def test_rm_b31_light_commands_carry_the_user(
    hass, no_frontend_registration, hass_read_only_user
):
    lights, _entry = await _two_lights(hass)
    hass_read_only_user.mock_policy({"entities": {"all": True}})
    ctx = Context(user_id=hass_read_only_user.id)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": SELECT, "option": "focus"}, blocking=True, context=ctx
    )
    await hass.async_block_till_done()
    sent = lights.for_light("light.b")[-1].context
    assert sent.user_id == hass_read_only_user.id and sent.parent_id == ctx.id


async def test_rm_b31_automatic_scenario_end_is_no_user_action(
    hass, no_frontend_registration, hass_read_only_user, freezer
):
    """The end of a scenario (timer) runs without the user who chose it."""
    lights, _entry = await _two_lights(hass)
    hass_read_only_user.mock_policy({"entities": {"all": True}})
    await hass.services.async_call(
        DOMAIN, "set_scenario", {"entity_id": SELECT, "scenario": "focus", "duration": 1},
        blocking=True, context=Context(user_id=hass_read_only_user.id),
    )
    await hass.async_block_till_done()
    hass_read_only_user.mock_policy({"entities": {"entity_ids": {SELECT: True}}})  # rights removed meanwhile
    lights.calls.clear()
    end = dt_util.utcnow() + timedelta(minutes=1, seconds=1)
    freezer.move_to(end)
    async_fire_time_changed(hass, end)
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "auto"
    sent = lights.for_light("light.a")
    assert sent and sent[-1].context.user_id is None


async def test_rm_b31_periodic_updates_run_without_user(hass, no_frontend_registration, hass_read_only_user, freezer):
    lights, _entry = await _two_lights(hass)
    hass_read_only_user.mock_policy({"entities": {"all": True}})
    await hass.services.async_call(
        "select", "select_option", {"entity_id": SELECT, "option": "focus"},
        blocking=True, context=Context(user_id=hass_read_only_user.id),
    )
    await hass.async_block_till_done()
    for eid in ("light.a", "light.b"):  # the lights drifted away from the values
        set_light(hass, eid, "on", **DIM)
    lights.calls.clear()
    later = dt_util.utcnow() + timedelta(minutes=5)
    freezer.move_to(later)
    async_fire_time_changed(hass, later)
    await hass.async_block_till_done()
    sent = lights.calls
    assert sent and all(c.context.user_id is None for c in sent)


# ---------------------------------------------------------------- RM-B34
async def test_rm_b34_switching_on_checks_the_lights_of_the_area_now(
    hass, no_frontend_registration, hass_read_only_user
):
    """A light joined the area while HCL was off: switching HCL on needs control of it."""
    lights = FakeLights(hass)
    area = ar.async_get(hass).async_create("Wohnzimmer")
    reg = er.async_get(hass)
    for name in ("a", "b"):
        reg.async_get_or_create("light", "test", name, suggested_object_id=name)
        set_light(hass, f"light.{name}", "on", **DIM)
    reg.async_update_entity("light.a", area_id=area.id)
    entry = MockConfigEntry(
        domain=DOMAIN, title="HCL", data={"name": "HCL", "target": {"area_id": [area.id]}}, options={}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hcl_on(hass)
    await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    # light.b joins the area while HCL is off
    reg.async_update_entity("light.b", area_id=area.id)
    await hass.async_block_till_done()
    lights.calls.clear()
    hass_read_only_user.mock_policy(
        {"entities": {"entity_ids": {SWITCH: True, SELECT: True, SENSOR: True, ADAPT: True, "light.a": True}}}
    )
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": SWITCH}, blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).state == "off"
    assert lights.calls == []


# ---------------------------------------------------------------- RM-B07
@pytest.mark.parametrize(
    "service,data",
    [
        ("apply", {"entity_id": SWITCH}),
        ("set_manual_control", {"entity_id": SWITCH}),
        ("set_scenario", {"entity_id": SELECT, "scenario": "focus"}),
        ("update_curve", {"entity_id": SENSOR, "mode": "revert"}),
    ],
)
async def test_rm_b07_writing_actions_need_control_permission(
    hass, no_frontend_registration, hass_read_only_user, service, data
):
    FakeLights(hass)  # light commands succeed (apply reports failed ones)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN, service, data, blocking=True, context=Context(user_id=hass_read_only_user.id)
        )
    # admins and calls without a user (automations) are allowed
    await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_rm_b07_explicit_lights_need_control_permission(hass, no_frontend_registration, hass_read_only_user):
    FakeLights(hass)  # light commands succeed (apply reports failed ones)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    set_light(hass, "light.b", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.a", "light.b"])
    await hcl_on(hass)
    hass_read_only_user.mock_policy({"entities": {"entity_ids": {SWITCH: True, "light.a": True}}})
    ctx = Context(user_id=hass_read_only_user.id)
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "lights": ["light.a"]}, blocking=True, context=ctx)
    with pytest.raises(Unauthorized):
        await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "lights": ["light.b"]}, blocking=True, context=ctx)


async def test_rm_b07_get_curve_needs_read_permission(hass, no_frontend_registration, hass_read_only_user):
    set_light(hass, "light.a", "on", **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    result = await hass.services.async_call(
        DOMAIN, "get_curve", {"entity_id": SENSOR}, blocking=True, return_response=True,
        context=Context(user_id=hass_read_only_user.id),
    )
    assert result["points"]
    hass_read_only_user.mock_policy({"entities": {"entity_ids": {SWITCH: True}}})
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN, "get_curve", {"entity_id": SENSOR}, blocking=True, return_response=True,
            context=Context(user_id=hass_read_only_user.id),
        )


# ---------------------------------------------------------------- RM-B08
async def test_rm_b08_light_commands_keep_the_origin(hass, no_frontend_registration, hass_admin_user):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    controller = core(hass, entry)["controller"]
    for service, data in (
        ("apply", {"entity_id": SWITCH, "release_manual_control": True}),
        ("set_scenario", {"entity_id": SELECT, "scenario": "focus"}),
        ("set_manual_control", {"entity_id": SWITCH, "manual_control": False}),
        ("update_curve", {"entity_id": SENSOR, "mode": "revert"}),
    ):
        set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
        core(hass, entry)["override_manager"].reset_override("light.a")
        lights.calls.clear()
        origin = Context(user_id=hass_admin_user.id)
        await hass.services.async_call(DOMAIN, service, data, blocking=True, context=origin)
        await hass.async_block_till_done()
        sent = lights.for_light("light.a")
        assert sent, service
        assert sent[-1].context.parent_id == origin.id, service
        # 0.7.0b12 (RM-B31): the light command runs as the user who caused it
        assert sent[-1].context.user_id == origin.user_id, service
        assert controller.is_own_context(sent[-1].context), service
    # switching HCL on
    await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    lights.calls.clear()
    origin = Context(user_id=hass_admin_user.id)
    await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True, context=origin)
    await hass.async_block_till_done()
    assert lights.for_light("light.a")[-1].context.parent_id == origin.id
    assert lights.for_light("light.a")[-1].context.user_id == origin.user_id
