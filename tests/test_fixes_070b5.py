"""0.7.0b5: fixes RM-B19 and RM-B20 of the roadmap (review of 0.7.0b4)."""
from __future__ import annotations

import asyncio

from homeassistant.util import dt as dt_util

from custom_components.hcl_lighting.logic import light_controller

from .helpers import CT_ATTRS, core, set_light, setup_entry, switch_entity
from .test_fixes_070b3 import SELECT, SWITCH, Lights, _hcl_on, _settle


# ---------------------------------------------------------------- RM-B19
class _OldServiceCall:
    """ServiceCall up to Home Assistant 2024.12 (no hass parameter)."""

    def __init__(self, domain, service, data=None, context=None, return_response=False):
        self.domain, self.service, self.data = domain, service, data or {}


class _NewServiceCall:
    """ServiceCall since Home Assistant 2025.1 (hass first)."""

    def __init__(self, hass, domain, service, data=None, context=None, return_response=False):
        self.hass, self.domain, self.service, self.data = hass, domain, service, data or {}


def test_rm_b19_service_call_keeps_the_target_with_both_signatures(monkeypatch):
    target = {"area_id": ["living"], "entity_id": ["light.a"]}
    for cls in (_OldServiceCall, _NewServiceCall):
        # imported at module level since 0.7.0b12 (RM-T16)
        monkeypatch.setattr(light_controller, "ServiceCall", cls)
        call = light_controller._service_call(object(), target)
        assert isinstance(call, cls)
        assert (call.domain, call.service, call.data) == ("light", "turn_on", target), cls.__name__


async def test_rm_b19_targets_are_resolved(hass, no_frontend_registration):
    """End to end on the installed Home Assistant (CI: 2024.7, 2025.7, 2025.8, current)."""
    set_light(hass, "light.a", "on", **CT_ATTRS)
    set_light(hass, "light.b", "on", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a", "light.b"])
    assert core(hass, entry)["controller"].resolve_targets({"entity_id": ["light.a", "light.b"]}) == {
        "light.a", "light.b"
    }
    await _hcl_on(hass)
    assert switch_entity(hass).resolved_targets == {"light.a", "light.b"}


# ---------------------------------------------------------------- RM-B20
async def _blocked_cycle(hass, lights):
    lights.calls.clear()
    lights.gate = asyncio.Event()
    gate = lights.gate
    cycle = hass.async_create_task(switch_entity(hass)._update_hcl())
    await lights.wait_for_calls(1)  # a cycle hangs on a slow light
    return gate, cycle


def _sent(lights):
    return [(c.data["brightness_pct"], c.data.get("color_temp_kelvin"), c.data["transition"]) for c in lights.calls]


async def test_rm_b20_scenario_after_a_waiting_long_apply_is_not_blocked(hass, no_frontend_registration):
    lights = Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"scenario_transition": 120})
    await _hcl_on(hass)
    gate, cycle = await _blocked_cycle(hass, lights)
    auto = core(hass, entry)["controller"].calculate_target_values(dt_util.now())
    apply = hass.async_create_task(
        hass.services.async_call("hcl_lighting", "apply", {"entity_id": SWITCH, "transition": 120}, blocking=True)
    )
    await _settle()
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "focus"}, blocking=True)
    await _settle()
    gate.set()
    await asyncio.gather(cycle, apply)
    await hass.async_block_till_done()
    sent = _sent(lights)
    assert sent[1] == (auto[0], auto[1], 120)  # the older apply with its values and transition
    assert sent[-1] == (100, 5500, 120)  # the newer scenario right after it, with its transition
    assert len(sent) == 3


async def test_rm_b20_scenario_after_a_running_long_scenario_update_is_not_blocked(hass, no_frontend_registration):
    lights = Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.a"], options={"scenario_transition": 120})
    await _hcl_on(hass)
    lights.calls.clear()
    lights.gate = asyncio.Event()
    gate = lights.gate
    # Relax is being sent with 120 s (slow light), Focus is chosen meanwhile
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "relax"}, blocking=True)
    await lights.wait_for_calls(1)
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "focus"}, blocking=True)
    await _settle()
    gate.set()
    await hass.async_block_till_done()
    assert _sent(lights) == [(40, 2700, 120), (100, 5500, 120)]
