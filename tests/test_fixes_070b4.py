"""0.7.0b4: fixes RM-B13 … RM-B18 of the roadmap (review of 0.7.0b3, there RM-B12 … RM-B17)."""
from __future__ import annotations

import asyncio

import pytest
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hcl_lighting.const import DOMAIN

from .helpers import CT_ATTRS, core, set_light, setup_entry, switch_entity
from .test_fixes_070b3 import SELECT, SWITCH, Lights, _hcl_on, _settle

try:  # Home Assistant 2026.1+ (TargetSelection; label rules of 2026)
    from homeassistant.helpers import target as _ha_target

    NEW_TARGETS = hasattr(_ha_target, "TargetSelection")
except ImportError:
    NEW_TARGETS = False


class HaLikeLights(Lights):
    """Like Home Assistant: a command for several lights runs for all of them
    and raises the first error afterwards (the others have been set)."""

    def __init__(self, hass):
        super().__init__(hass)
        self.applied: list[str] = []

    async def _handle(self, call):
        entities = call.data.get("entity_id") or []
        entities = [entities] if isinstance(entities, str) else list(entities)
        self.applied.extend(e for e in entities if e not in self.fail)
        await super()._handle(call)


def _tracking(om, entity_id):
    data = om._override_state.get(entity_id) or {}
    return data.get("last_set"), data.get("ignore_events_until")


async def _apply(hass, **data):
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, **data}, blocking=True)


# ---------------------------------------------------------------- RM-B13 (review RM-B12)
async def test_rm_b13_partial_failure_keeps_the_successful_light(hass, no_frontend_registration):
    lights = HaLikeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    set_light(hass, "light.b", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a", "light.b"])
    await _hcl_on(hass)
    om = core(hass, entry)["override_manager"]
    before_b = _tracking(om, "light.b")[0]
    lights.fail = {"light.b"}
    try:
        await _apply(hass, transition=120)
    except HomeAssistantError:
        pass  # reported since RM-B16
    target = core(hass, entry)["controller"].calculate_target_values(dt_util.now())
    assert _tracking(om, "light.a")[0][0] == target[0]  # light.a got the values
    assert _tracking(om, "light.b")[0] == before_b
    assert om.is_reengaging("light.a") and not om.is_reengaging("light.b")
    assert all(len(c.data["entity_id"]) == 1 for c in lights.calls)  # one command per light


# ---------------------------------------------------------------- RM-B14 (review RM-B13)
async def test_rm_b14_failed_command_restores_the_ignore_window(hass, no_frontend_registration):
    lights = Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
    om = core(hass, entry)["override_manager"]
    before = _tracking(om, "light.a")
    lights.fail = {"light.a"}
    try:
        await _apply(hass, transition=120)
    except HomeAssistantError:
        pass  # reported since RM-B16
    assert _tracking(om, "light.a") == before  # values and ignore window as before


# ---------------------------------------------------------------- RM-B15 (review RM-B14)
async def test_rm_b15_failed_turn_on_update_restores_the_tracking(hass, no_frontend_registration):
    lights = Lights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
    om = core(hass, entry)["override_manager"]
    before = _tracking(om, "light.a")
    lights.fail = {"light.a"}
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)  # switched on
    await hass.async_block_till_done()
    assert lights.for_light("light.a")  # HCL tried
    assert _tracking(om, "light.a") == before


async def test_rm_b15_successful_turn_on_update_keeps_the_tracking(hass, no_frontend_registration):
    Lights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
    om = core(hass, entry)["override_manager"]
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await hass.async_block_till_done()
    last_set, ignore_until = _tracking(om, "light.a")
    assert last_set is not None and ignore_until is not None


# ---------------------------------------------------------------- RM-B16 (review RM-B15)
async def test_rm_b16_apply_reports_failed_lights(hass, no_frontend_registration):
    lights = HaLikeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    set_light(hass, "light.b", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.a", "light.b"])
    await _hcl_on(hass)
    lights.fail = {"light.a", "light.b"}
    with pytest.raises(HomeAssistantError, match="light.a, light.b"):
        await _apply(hass)
    lights.fail = {"light.b"}  # partial failure is reported too
    with pytest.raises(HomeAssistantError, match="failed for light.b:"):
        await _apply(hass)
    assert "light.a" in lights.applied
    lights.fail = set()
    await _apply(hass)  # success: no error


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
    controller = core(hass, entry)["controller"]
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
    result = core(hass, entry)["controller"].resolve_targets({"label_id": [label.label_id]})
    # a labelled configuration light: 2024.7 skips it, 2026.x includes it
    assert (config_light.entity_id in result) is NEW_TARGETS


# ---------------------------------------------------------------- RM-B18 (review RM-B17)
async def test_rm_b18_older_apply_does_not_send_a_later_scenario(hass, no_frontend_registration):
    lights = Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"scenario_transition": 120})
    await _hcl_on(hass)
    sw = switch_entity(hass)
    lights.calls.clear()
    lights.gate = asyncio.Event()
    gate = lights.gate
    cycle = hass.async_create_task(sw._update_hcl())
    await lights.wait_for_calls(1)  # a cycle hangs on a slow light
    auto = core(hass, entry)["controller"].calculate_target_values(dt_util.now())
    apply = hass.async_create_task(_apply(hass, transition=0))
    await _settle()
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "focus"}, blocking=True)
    await _settle()
    gate.set()
    await asyncio.gather(cycle, apply)
    await hass.async_block_till_done()
    sent = [(c.data["brightness_pct"], c.data.get("color_temp_kelvin"), c.data["transition"]) for c in lights.calls]
    assert sent[1] == (auto[0], auto[1], 0)  # the apply with the values of its time
    assert sent[-1] == (100, 5500, 120)  # the later scenario change last, with its transition
