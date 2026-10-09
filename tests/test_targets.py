"""Target resolution: areas, devices, floors, labels, groups; conflicts between instances."""
from __future__ import annotations

import pytest

from datetime import timedelta
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EntityCategory
from homeassistant.core import CoreState, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er, floor_registry as fr, label_registry as lr
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed, async_mock_service, mock_restore_cache

from custom_components.hcl_lighting.const import DOMAIN

from .support.entries import CT_ATTRS, DIM, SWITCH, core, hcl_on, set_light, setup_entry, switch_entity
from .support.lights import FakeLights


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


async def _registry_setup(hass):
    other = MockConfigEntry(domain="demo")
    other.add_to_hass(hass)
    areas = ar.async_get(hass)
    living = areas.async_create("Living")
    kitchen = areas.async_create("Kitchen")
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(config_entry_id=other.entry_id, identifiers={("demo", "d1")})
    devices.async_update_device(device.id, area_id=living.id)
    ents = er.async_get(hass)

    def light(uid, **changes):
        entry = ents.async_get_or_create("light", "demo", uid, device_id=device.id, config_entry=other)
        if changes:
            ents.async_update_entity(entry.entity_id, **changes)
        return entry.entity_id

    ids = {
        "plain": light("plain"),
        "own_area": light("own_area", area_id=kitchen.id),
        "hidden": light("hidden", hidden_by=er.RegistryEntryHider.USER),
        "config": light("config", entity_category=EntityCategory.CONFIG),
    }
    return living, kitchen, device, ids


try:  # Home Assistant 2026.1+ (TargetSelection; label rules of 2026)
    from homeassistant.helpers import target as _ha_target

    NEW_TARGETS = hasattr(_ha_target, "TargetSelection")
except ImportError:
    NEW_TARGETS = False


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
    assert sw.resolved_targets == set()
    ent = er.async_get(hass).async_get_or_create("light", "test", "new", suggested_object_id="neu")
    set_light(hass, ent.entity_id, "on", brightness=10, **CT_ATTRS)
    er.async_get(hass).async_update_entity(ent.entity_id, area_id=area.id)
    freezer.tick(timedelta(seconds=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert sw.resolved_targets == {ent.entity_id}


# ---------------------------------------------------------------- F-08 conflicts
@pytest.mark.usefixtures("evening")
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


@pytest.mark.usefixtures("evening")
async def test_f08_issue_disappears_when_an_instance_is_off(hass, no_frontend_registration):
    from homeassistant.helpers import issue_registry as ir

    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    await _two_instances(hass, ["light.a"], ["light.a"])
    assert ir.async_get(hass).async_get_issue(DOMAIN, "light_in_multiple_instances_light.a") is not None
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.b_hcl_active"}, blocking=True)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "light_in_multiple_instances_light.a") is None


@pytest.mark.usefixtures("evening")
async def test_rm_t01_unloaded_instance_no_longer_counts(hass, no_frontend_registration):
    """RM-T01: the runtime data lives in the entry; an unloaded instance is gone
    for conflicts and actions."""
    from homeassistant.exceptions import ServiceValidationError
    from homeassistant.helpers import issue_registry as ir

    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entries = await _two_instances(hass, ["light.a"], ["light.a"])
    assert ir.async_get(hass).async_get_issue(DOMAIN, "light_in_multiple_instances_light.a") is not None
    assert await hass.config_entries.async_unload(entries[1].entry_id)
    await hass.async_block_till_done()
    assert not hasattr(entries[1], "runtime_data")
    assert ir.async_get(hass).async_get_issue(DOMAIN, "light_in_multiple_instances_light.a") is None
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "apply", {"entity_id": "switch.b_hcl_active"}, blocking=True)


# ---------------------------------------------------------------- B-11 group members
@pytest.mark.usefixtures("evening")
async def test_b11_changed_group_members_are_picked_up(hass, no_frontend_registration, freezer):
    async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    set_light(hass, "light.b", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    hass.states.async_set("light.grp", "on", {"entity_id": ["light.a"], **CT_ATTRS})
    await setup_entry(hass, ["light.grp"])
    await hcl_on(hass)
    sw = switch_entity(hass)
    assert sw.resolved_targets == {"light.a"}
    hass.states.async_set("light.grp", "on", {"entity_id": ["light.a", "light.b"], **CT_ATTRS})
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert sw.resolved_targets == {"light.a", "light.b"}


# ---------------------------------------------------------------- RM-B35
async def test_rm_b35_empty_target_in_the_options_does_not_fall_back(hass, no_frontend_registration):
    """An empty target stored in the options (e.g. by an older version) means
    no lights, not the lights of the first setup."""
    set_light(hass, "light.a", "on", **DIM)
    entry = MockConfigEntry(
        domain=DOMAIN, title="HCL", data={"name": "HCL", "target": {"entity_id": ["light.a"]}},
        options={"target": {}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    sw = switch_entity(hass)
    assert sw.controlled_lights() == set()
    await hcl_on(hass)
    assert sw.resolved_targets == set()


# ---------------------------------------------------------------- RM-B06
async def test_rm_b06_area_follows_home_assistant(hass, no_frontend_registration):
    set_light(hass, "light.x", "on", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.x"])
    living, kitchen, device, ids = await _registry_setup(hass)
    controller = core(hass, entry).controller
    # an entity with its own area belongs to that area, not to the device's
    assert controller.resolve_targets({"area_id": [living.id]}) == {ids["plain"]}
    assert controller.resolve_targets({"area_id": kitchen.id}) == {ids["own_area"]}


async def test_rm_b06_device_skips_hidden_and_config_entities(hass, no_frontend_registration):
    set_light(hass, "light.x", "on", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.x"])
    _living, _kitchen, device, ids = await _registry_setup(hass)
    controller = core(hass, entry).controller
    assert controller.resolve_targets({"device_id": [device.id]}) == {ids["plain"], ids["own_area"]}
    # given directly, they are used
    assert controller.resolve_targets({"entity_id": [ids["hidden"], ids["config"]]}) == {ids["hidden"], ids["config"]}


# ---------------------------------------------------------------- RM-B09
async def test_rm_b09_group_listener_is_released_when_hcl_is_off(hass, no_frontend_registration):
    set_light(hass, "light.a", "on", **CT_ATTRS)
    hass.states.async_set("light.group", "on", {"entity_id": ["light.a"]})
    await setup_entry(hass, ["light.group"])
    await hcl_on(hass)
    sw = switch_entity(hass)
    assert sw._group_listener_remove_callback is not None
    await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    assert sw._group_listener_remove_callback is None
    await hcl_on(hass)
    assert sw._group_listener_remove_callback is not None
    set_light(hass, "light.b", "on", **CT_ATTRS)
    hass.states.async_set("light.group", "on", {"entity_id": ["light.a", "light.b"]})
    await hass.async_block_till_done()
    assert sw._cancel_reresolve is not None  # still watched while on


# ---------------------------------------------------------------- RM-B17 (review RM-B16)
@pytest.mark.skipif(not hasattr(dr.DeviceRegistry, "async_get_or_create_child"), reason="no child devices in this HA version")
async def test_rm_b17_device_includes_its_child_devices(hass, no_frontend_registration):
    set_light(hass, "light.x", "on", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.x"])
    other = MockConfigEntry(domain="demo")
    other.add_to_hass(hass)
    devices = dr.async_get(hass)
    parent = devices.async_get_or_create(config_entry_id=other.entry_id, identifiers={("demo", "hub")})
    child = devices.async_get_or_create_child(
        config_entry_id=other.entry_id, identifiers={("demo", "lamp")}, parent_device_id=parent.id
    )
    light = er.async_get(hass).async_get_or_create("light", "demo", "lamp", device_id=child.id, config_entry=other)
    controller = core(hass, entry).controller
    assert controller.resolve_targets({"device_id": [parent.id]}) == {light.entity_id}


async def test_rm_b17_label_follows_the_running_home_assistant(hass, no_frontend_registration):
    set_light(hass, "light.x", "on", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.x"])
    other = MockConfigEntry(domain="demo")
    other.add_to_hass(hass)
    label = lr.async_get(hass).async_create("HCL")
    ents = er.async_get(hass)
    config_light = ents.async_get_or_create("light", "demo", "led", config_entry=other)
    ents.async_update_entity(config_light.entity_id, entity_category=EntityCategory.CONFIG, labels={label.label_id})
    result = core(hass, entry).controller.resolve_targets({"label_id": [label.label_id]})
    # a labelled configuration light: 2024.7 skips it, 2026.x includes it
    assert (config_light.entity_id in result) is NEW_TARGETS


# ---------------------------------------------------------------- RM-B19
async def test_rm_b19_targets_are_resolved(hass, no_frontend_registration):
    """End to end on the installed Home Assistant (CI: 2024.7, 2025.7, 2025.8, current)."""
    set_light(hass, "light.a", "on", **CT_ATTRS)
    set_light(hass, "light.b", "on", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a", "light.b"])
    assert core(hass, entry).controller.resolve_targets({"entity_id": ["light.a", "light.b"]}) == {
        "light.a", "light.b"
    }
    await hcl_on(hass)
    assert switch_entity(hass).resolved_targets == {"light.a", "light.b"}


# ---------------------------------------------------------------- B-10
async def test_b10_floor_and_label_targets_are_resolved(hass, no_frontend_registration):
    ent_reg = er.async_get(hass)
    floor = fr.async_get(hass).async_create("EG")
    area = ar.async_get(hass).async_create("Wohnen", floor_id=floor.floor_id)
    label = lr.async_get(hass).async_create("HCL")
    e1 = ent_reg.async_get_or_create("light", "test", "1", suggested_object_id="floor_light")
    ent_reg.async_update_entity(e1.entity_id, area_id=area.id)
    e2 = ent_reg.async_get_or_create("light", "test", "2", suggested_object_id="label_light")
    ent_reg.async_update_entity(e2.entity_id, labels={label.label_id})
    set_light(hass, e1.entity_id, "off", **CT_ATTRS)
    set_light(hass, e2.entity_id, "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.unused"])
    ctl = core(hass, entry).controller
    assert ctl.resolve_targets({"floor_id": [floor.floor_id]}) == {e1.entity_id}
    assert ctl.resolve_targets({"label_id": label.label_id}) == {e2.entity_id}


# ---------------------------------------------------------------- B-11
async def test_b11_group_loaded_after_startup_is_expanded(hass, no_frontend_registration):
    async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=10, color_temp_kelvin=2700, **CT_ATTRS)
    set_light(hass, "light.b", "on", brightness=10, color_temp_kelvin=2700, **CT_ATTRS)
    mock_restore_cache(hass, [State("switch.hcl_hcl_active", "on")])
    hass.set_state(CoreState.not_running)
    await setup_entry(hass, ["light.group"])  # group platform not loaded yet
    sw = switch_entity(hass)
    assert sw.is_on
    # Group appears later during startup.
    hass.states.async_set("light.group", "on", {"entity_id": ["light.a", "light.b"], **CT_ATTRS})
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert sw.resolved_targets == {"light.a", "light.b"}


# ---------------------------------------------------------------- RM-B44
async def _area_instance_switched_off(hass):
    """Instance for an area with light.a; HCL was on and is off now."""
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
    lights.calls.clear()
    return lights, reg, area


async def test_rm_b44_apply_while_off_reaches_a_light_that_joined_the_area(hass, no_frontend_registration):
    lights, reg, area = await _area_instance_switched_off(hass)
    reg.async_update_entity("light.b", area_id=area.id)
    await hass.async_block_till_done()
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH}, blocking=True)
    await hass.async_block_till_done()
    assert lights.for_light("light.b")
    # named explicitly it is accepted as well
    lights.calls.clear()
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "lights": ["light.b"]}, blocking=True)
    await hass.async_block_till_done()
    assert lights.for_light("light.b")


async def test_rm_b44_apply_while_off_skips_a_light_that_left_the_area(hass, no_frontend_registration):
    lights, reg, area = await _area_instance_switched_off(hass)
    reg.async_update_entity("light.b", area_id=area.id)
    reg.async_update_entity("light.a", area_id=None)
    await hass.async_block_till_done()
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH}, blocking=True)
    await hass.async_block_till_done()
    assert not lights.for_light("light.a")
    assert lights.for_light("light.b")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "set_manual_control", {"entity_id": SWITCH, "lights": ["light.a"]}, blocking=True
        )


async def test_rm_b44_apply_while_off_does_not_start_the_listeners(hass, no_frontend_registration):
    """An action while HCL is off resolves the lights without starting the
    runtime listeners of the regulator."""
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", **DIM)
    await setup_entry(hass, ["light.a"])  # HCL stays off
    sw = switch_entity(hass)
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH}, blocking=True)
    await hass.async_block_till_done()
    assert lights.for_light("light.a")
    assert sw._state_listener_remove_callback is None
