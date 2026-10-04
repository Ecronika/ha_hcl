"""0.7.0b3: fixes RM-B01 … RM-B11 of the roadmap (docs: ROADMAP.md, phase 1)."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.const import EntityCategory
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hcl_lighting.const import DOMAIN

from .helpers import CT_ATTRS, core, set_light, setup_entry, switch_entity

SWITCH = "switch.hcl_hcl_active"
SELECT = "select.hcl_scenario"
SENSOR = "sensor.hcl_curve_data"
COLOR_ATTRS = {"supported_color_modes": ["xy"], "color_mode": "xy"}
WARM_CT = {**CT_ATTRS, "min_color_temp_kelvin": 2200, "max_color_temp_kelvin": 4000}


class Lights:
    """light.turn_on handler: records calls, can block or fail."""

    def __init__(self, hass):
        self.calls: list = []
        self.events: list[tuple[str, dict]] = []
        self.gate: asyncio.Event | None = None
        self.fail: set[str] = set()
        hass.services.async_register("light", "turn_on", self._handle)

    async def _handle(self, call):
        self.calls.append(call)
        data = dict(call.data)
        self.events.append(("start", data))
        if self.gate is not None:
            gate, self.gate = self.gate, None  # only the first call waits
            await gate.wait()
        entities = call.data.get("entity_id") or []
        entities = [entities] if isinstance(entities, str) else entities
        if self.fail & set(entities):
            self.events.append(("error", data))
            raise HomeAssistantError(f"device error {sorted(self.fail & set(entities))}")
        self.events.append(("end", data))

    def for_light(self, entity_id):
        out = []
        for c in self.calls:
            ents = c.data.get("entity_id")
            ents = [ents] if isinstance(ents, str) else ents
            if entity_id in ents:
                out.append(c)
        return out

    async def wait_for_calls(self, n):
        for _ in range(1000):
            if len(self.calls) >= n:
                return
            await asyncio.sleep(0)  # independent of the (possibly frozen) clock
        raise AssertionError(f"expected {n} light calls, got {len(self.calls)}")


async def _settle(rounds: int = 100) -> None:
    """Let waiting tasks run (asyncio.sleep(0) works with a frozen clock)."""
    for _ in range(rounds):
        await asyncio.sleep(0)


async def _hcl_on(hass):
    await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    await hass.async_block_till_done()


async def _select(hass, option):
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": option}, blocking=True)
    await hass.async_block_till_done()


# ---------------------------------------------------------------- RM-B01
async def test_rm_b01_scenario_change_during_a_running_update_is_not_lost(hass, no_frontend_registration):
    lights = Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    lights.gate = asyncio.Event()
    gate = lights.gate
    turn_on = hass.async_create_task(
        hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    )
    await lights.wait_for_calls(1)  # the first update hangs (slow light)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": SELECT, "option": "focus"}, blocking=True
    )
    await _settle()
    gate.set()
    await turn_on
    await hass.async_block_till_done()
    last = lights.for_light("light.a")[-1].data
    assert (last["brightness_pct"], last["color_temp_kelvin"]) == (100, 5500)


async def test_rm_b01_requests_are_combined(hass, no_frontend_registration):
    lights = Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
    signal = f"{DOMAIN}_{entry.entry_id}_update"
    lights.calls.clear()
    lights.gate = asyncio.Event()
    gate = lights.gate
    async_dispatcher_send(hass, signal)
    await lights.wait_for_calls(1)
    for _ in range(5):  # e.g. curve preview while dragging
        async_dispatcher_send(hass, signal)
    await _settle()
    gate.set()
    await hass.async_block_till_done()
    assert len(lights.calls) == 2  # the running update and one combined update


async def test_rm_b01_periodic_update_is_skipped_while_busy(hass, no_frontend_registration):
    lights = Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
    sw = switch_entity(hass)
    lights.calls.clear()
    lights.gate = asyncio.Event()
    gate = lights.gate
    first = hass.async_create_task(sw._update_hcl())
    await lights.wait_for_calls(1)
    await sw._update_hcl()  # timer tick while busy: skipped, returns at once
    gate.set()
    await first
    await hass.async_block_till_done()
    assert len(lights.calls) == 1


# ---------------------------------------------------------------- RM-B02
async def test_rm_b02_apply_waits_for_a_running_update(hass, no_frontend_registration):
    lights = Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
    sw = switch_entity(hass)
    lights.calls.clear()
    lights.events.clear()
    lights.gate = asyncio.Event()
    gate = lights.gate
    cycle = hass.async_create_task(sw._update_hcl())
    await lights.wait_for_calls(1)
    apply = hass.async_create_task(
        hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 7}, blocking=True)
    )
    await _settle()
    assert [e for e in lights.events if e[1].get("transition") == 7] == []  # not sent in parallel
    gate.set()
    await asyncio.gather(cycle, apply)
    await hass.async_block_till_done()
    kinds = [(kind, data.get("transition")) for kind, data in lights.events]
    assert kinds == [("start", 20), ("end", 20), ("start", 7), ("end", 7)]


# ---------------------------------------------------------------- RM-B03
async def test_rm_b03_ct_light_gets_the_kelvin_it_can_reach(hass, no_frontend_registration):
    lights = Lights(hass)
    set_light(hass, "light.warm", "on", brightness=3, color_temp_kelvin=2200, **WARM_CT)
    set_light(hass, "light.wide", "on", brightness=3, color_temp_kelvin=2200, **CT_ATTRS)
    await setup_entry(hass, ["light.warm", "light.wide"], options={"focus_kelvin": 6500})
    await _hcl_on(hass)
    lights.calls.clear()
    await _select(hass, "focus")
    assert lights.for_light("light.warm")[-1].data["color_temp_kelvin"] == 4000
    assert lights.for_light("light.wide")[-1].data["color_temp_kelvin"] == 6500
    assert all(len(c.data["entity_id"]) == 1 for c in lights.calls)  # 0.7.0b4: one command per light


async def test_rm_b03_turn_on_and_smart_transition_are_limited_too(hass, no_frontend_registration):
    lights = Lights(hass)
    set_light(hass, "light.warm", "off", **WARM_CT)
    await setup_entry(hass, ["light.warm"], options={"focus_kelvin": 6500, "smart_transition": True})
    await _hcl_on(hass)
    await _select(hass, "focus")
    lights.calls.clear()
    set_light(hass, "light.warm", "on", brightness=3, color_temp_kelvin=2200, **WARM_CT)  # switched on
    await hass.async_block_till_done()
    assert lights.for_light("light.warm")[-1].data["color_temp_kelvin"] == 4000
    lights.calls.clear()
    set_light(hass, "light.warm", "on", brightness=3, color_temp_kelvin=2200, **WARM_CT)
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 5, "release_manual_control": True}, blocking=True)
    kelvins = {c.data["color_temp_kelvin"] for c in lights.for_light("light.warm") if "color_temp_kelvin" in c.data}
    assert kelvins == {4000}


# ---------------------------------------------------------------- RM-B04
async def test_rm_b04_failed_command_is_not_reported_as_updated(hass, no_frontend_registration):
    lights = Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    set_light(hass, "light.b", "on", brightness=3, xy_color=(0.6, 0.35), **COLOR_ATTRS)
    entry = await setup_entry(hass, ["light.a", "light.b"])
    await _hcl_on(hass)
    om = core(hass, entry)["override_manager"]
    before = om._override_state.get("light.b", {}).get("last_set")
    lights.fail = {"light.b"}
    set_light(hass, "light.b", "on", brightness=200, xy_color=(0.2, 0.2), **COLOR_ATTRS)
    om.reset_override("light.b")
    with pytest.raises(HomeAssistantError):  # 0.7.0b4: apply reports failed lights
        await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 120}, blocking=True)
    assert om.is_reengaging("light.a")
    assert not om.is_reengaging("light.b")  # its command failed
    assert om._override_state.get("light.b", {}).get("last_set") == before  # tracking restored


async def test_rm_b04_failed_smooth_return_hands_the_light_back(hass, no_frontend_registration, freezer):
    lights = Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"override_timeout": 1})
    await _hcl_on(hass)
    om = core(hass, entry)["override_manager"]
    om.set_override("light.a")
    freezer.tick(timedelta(minutes=2))
    lights.fail = {"light.a"}
    await switch_entity(hass)._update_hcl()
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")
    assert not om.is_reengaging("light.a")  # the 3-minute protection ends with the failure


# ---------------------------------------------------------------- RM-B05
async def test_rm_b05_final_smart_transition_failure_is_reported(hass, no_frontend_registration, caplog):
    lights = Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"smart_transition": True})
    await _hcl_on(hass)
    om = core(hass, entry)["override_manager"]
    lights.fail = {"light.a"}
    set_light(hass, "light.a", "on", brightness=200, color_temp_kelvin=6000, **CT_ATTRS)
    om.reset_override("light.a")
    caplog.clear()
    with pytest.raises(HomeAssistantError):  # 0.7.0b4: apply reports failed lights
        await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 120}, blocking=True)
    assert not om.is_reengaging("light.a")
    assert "Smart transition for light.a failed" in caplog.text  # primary: warning
    assert any(r.levelname == "ERROR" and "light.a" in r.getMessage() for r in caplog.records)  # final


async def test_rm_b05_fallback_success_counts(hass, no_frontend_registration):
    lights = Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"smart_transition": True})
    await _hcl_on(hass)
    om = core(hass, entry)["override_manager"]
    original = lights._handle

    async def fail_with_transition(call):
        if "transition" in call.data and call.data["transition"]:
            raise HomeAssistantError("no transition support")
        await original(call)

    hass.services.async_register("light", "turn_on", fail_with_transition)
    set_light(hass, "light.a", "on", brightness=200, color_temp_kelvin=6000, **CT_ATTRS)
    om.reset_override("light.a")  # the change above is no manual control here
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 120}, blocking=True)
    assert om.is_reengaging("light.a")  # sent without transition by the fallback


# ---------------------------------------------------------------- RM-B06
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


async def test_rm_b06_area_follows_home_assistant(hass, no_frontend_registration):
    set_light(hass, "light.x", "on", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.x"])
    living, kitchen, device, ids = await _registry_setup(hass)
    controller = core(hass, entry)["controller"]
    # an entity with its own area belongs to that area, not to the device's
    assert controller.resolve_targets({"area_id": [living.id]}) == {ids["plain"]}
    assert controller.resolve_targets({"area_id": kitchen.id}) == {ids["own_area"]}


async def test_rm_b06_device_skips_hidden_and_config_entities(hass, no_frontend_registration):
    set_light(hass, "light.x", "on", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.x"])
    _living, _kitchen, device, ids = await _registry_setup(hass)
    controller = core(hass, entry)["controller"]
    assert controller.resolve_targets({"device_id": [device.id]}) == {ids["plain"], ids["own_area"]}
    # given directly, they are used
    assert controller.resolve_targets({"entity_id": [ids["hidden"], ids["config"]]}) == {ids["hidden"], ids["config"]}


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
    Lights(hass)  # light commands succeed (apply reports failed ones)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN, service, data, blocking=True, context=Context(user_id=hass_read_only_user.id)
        )
    # admins and calls without a user (automations) are allowed
    await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_rm_b07_explicit_lights_need_control_permission(hass, no_frontend_registration, hass_read_only_user):
    Lights(hass)  # light commands succeed (apply reports failed ones)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    set_light(hass, "light.b", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.a", "light.b"])
    await _hcl_on(hass)
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
    lights = Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
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


# ---------------------------------------------------------------- RM-B09
async def test_rm_b09_group_listener_is_released_when_hcl_is_off(hass, no_frontend_registration):
    set_light(hass, "light.a", "on", **CT_ATTRS)
    hass.states.async_set("light.group", "on", {"entity_id": ["light.a"]})
    await setup_entry(hass, ["light.group"])
    await _hcl_on(hass)
    sw = switch_entity(hass)
    assert sw._group_listener_remove_callback is not None
    await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    assert sw._group_listener_remove_callback is None
    await _hcl_on(hass)
    assert sw._group_listener_remove_callback is not None
    set_light(hass, "light.b", "on", **CT_ATTRS)
    hass.states.async_set("light.group", "on", {"entity_id": ["light.a", "light.b"]})
    await hass.async_block_till_done()
    assert sw._cancel_reresolve is not None  # still watched while on


# ---------------------------------------------------------------- RM-B11
async def test_rm_b11_options_form_errors_are_not_hidden(hass, no_frontend_registration):
    set_light(hass, "light.a", "on", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    from custom_components.hcl_lighting.config_flow import OptionsFlowHandler

    with patch.object(OptionsFlowHandler, "add_suggested_values_to_schema", side_effect=KeyError("bug")):
        with pytest.raises(KeyError):
            await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] == "form"
