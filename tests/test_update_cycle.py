"""Serialisation of the update cycle, requests and long transitions."""
from __future__ import annotations

import asyncio

from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from custom_components.hcl_lighting.const import DOMAIN

from .support.entries import CT_ATTRS, SELECT, SWITCH, core, hcl_on, set_light, settle, setup_entry, timer_cycle
from .support.lights import FakeLights


async def _apply(hass, **data):
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, **data}, blocking=True)


async def _blocked_cycle(hass, lights):
    lights.calls.clear()
    lights.gate = asyncio.Event()
    gate = lights.gate
    cycle = hass.async_create_task(timer_cycle(hass))
    await lights.wait_for_calls(1)  # a cycle hangs on a slow light
    return gate, cycle


def _sent(lights):
    return [(c.data["brightness_pct"], c.data.get("color_temp_kelvin"), c.data["transition"]) for c in lights.calls]


# ---------------------------------------------------------------- RM-B01
async def test_rm_b01_scenario_change_during_a_running_update_is_not_lost(hass, no_frontend_registration):
    lights = FakeLights(hass)
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
    await settle()
    gate.set()
    await turn_on
    await hass.async_block_till_done()
    last = lights.for_light("light.a")[-1].data
    assert (last["brightness_pct"], last["color_temp_kelvin"]) == (100, 5500)


async def test_rm_b01_requests_are_combined(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    signal = f"{DOMAIN}_{entry.entry_id}_update"
    lights.calls.clear()
    lights.gate = asyncio.Event()
    gate = lights.gate
    async_dispatcher_send(hass, signal)
    await lights.wait_for_calls(1)
    for _ in range(5):  # e.g. curve preview while dragging
        async_dispatcher_send(hass, signal)
    await settle()
    gate.set()
    await hass.async_block_till_done()
    assert len(lights.calls) == 2  # the running update and one combined update


async def test_rm_b01_periodic_update_is_skipped_while_busy(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    lights.calls.clear()
    lights.gate = asyncio.Event()
    gate = lights.gate
    first = hass.async_create_task(timer_cycle(hass))
    await lights.wait_for_calls(1)
    await timer_cycle(hass)  # timer tick while busy: skipped, returns at once
    gate.set()
    await first
    await hass.async_block_till_done()
    assert len(lights.calls) == 1


# ---------------------------------------------------------------- RM-B02
async def test_rm_b02_apply_waits_for_a_running_update(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    lights.calls.clear()
    lights.events.clear()
    lights.gate = asyncio.Event()
    gate = lights.gate
    cycle = hass.async_create_task(timer_cycle(hass))
    await lights.wait_for_calls(1)
    apply = hass.async_create_task(
        hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 7}, blocking=True)
    )
    await settle()
    assert [e for e in lights.events if e[1].get("transition") == 7] == []  # not sent in parallel
    gate.set()
    await asyncio.gather(cycle, apply)
    await hass.async_block_till_done()
    kinds = [(kind, data.get("transition")) for kind, data in lights.events]
    assert kinds == [("start", 20), ("end", 20), ("start", 7), ("end", 7)]


# ---------------------------------------------------------------- RM-B18 (review RM-B17)
async def test_rm_b18_older_apply_does_not_send_a_later_scenario(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"scenario_transition": 120})
    await hcl_on(hass)
    lights.calls.clear()
    lights.gate = asyncio.Event()
    gate = lights.gate
    cycle = hass.async_create_task(timer_cycle(hass))
    await lights.wait_for_calls(1)  # a cycle hangs on a slow light
    auto = core(hass, entry).controller.calculate_target_values(dt_util.now())
    apply = hass.async_create_task(_apply(hass, transition=0))
    await settle()
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "focus"}, blocking=True)
    await settle()
    gate.set()
    await asyncio.gather(cycle, apply)
    await hass.async_block_till_done()
    sent = [(c.data["brightness_pct"], c.data.get("color_temp_kelvin"), c.data["transition"]) for c in lights.calls]
    assert sent[1] == (auto[0], auto[1], 0)  # the apply with the values of its time
    assert sent[-1] == (100, 5500, 120)  # the later scenario change last, with its transition


# ---------------------------------------------------------------- RM-B20
async def test_rm_b20_scenario_after_a_waiting_long_apply_is_not_blocked(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"scenario_transition": 120})
    await hcl_on(hass)
    gate, cycle = await _blocked_cycle(hass, lights)
    auto = core(hass, entry).controller.calculate_target_values(dt_util.now())
    apply = hass.async_create_task(
        hass.services.async_call("hcl_lighting", "apply", {"entity_id": SWITCH, "transition": 120}, blocking=True)
    )
    await settle()
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "focus"}, blocking=True)
    await settle()
    gate.set()
    await asyncio.gather(cycle, apply)
    await hass.async_block_till_done()
    sent = _sent(lights)
    assert sent[1] == (auto[0], auto[1], 120)  # the older apply with its values and transition
    assert sent[-1] == (100, 5500, 120)  # the newer scenario right after it, with its transition
    assert len(sent) == 3


async def test_rm_b20_scenario_after_a_running_long_scenario_update_is_not_blocked(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.a"], options={"scenario_transition": 120})
    await hcl_on(hass)
    lights.calls.clear()
    lights.gate = asyncio.Event()
    gate = lights.gate
    # Relax is being sent with 120 s (slow light), Focus is chosen meanwhile
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "relax"}, blocking=True)
    await lights.wait_for_calls(1)
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": "focus"}, blocking=True)
    await settle()
    gate.set()
    await hass.async_block_till_done()
    assert _sent(lights) == [(40, 2700, 120), (100, 5500, 120)]
