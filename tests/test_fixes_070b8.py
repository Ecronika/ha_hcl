"""0.7.0b8: fix RM-B23 of the roadmap (a light that does not answer blocks the update)."""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.hcl_lighting.const import COMMAND_TIMEOUT_SECONDS, DOMAIN

from .helpers import CT_ATTRS, core, set_light, setup_entry, switch_entity
from .test_fixes_070b3 import SELECT, SWITCH, _hcl_on, _settle


class SlowLights:
    """light.turn_on handler: lights in `hang` do not answer until released."""

    def __init__(self, hass):
        self.calls: list = []
        self.hang: dict[str, asyncio.Event] = {}
        self.fail_late: set[str] = set()
        hass.services.async_register("light", "turn_on", self._handle)

    async def _handle(self, call):
        self.calls.append(call)
        eid = call.data["entity_id"][0]
        if eid in self.hang:
            await self.hang[eid].wait()
            if eid in self.fail_late:
                raise HomeAssistantError(f"late device error {eid}")

    def for_light(self, entity_id):
        return [c for c in self.calls if entity_id in c.data["entity_id"]]

    def release(self):
        for event in self.hang.values():
            event.set()


async def _setup(hass):
    lights = SlowLights(hass)
    for eid in ("light.a", "light.b"):
        set_light(hass, eid, "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a", "light.b"])
    await _hcl_on(hass)
    lights.calls.clear()
    return lights, entry


def _select(hass, option):
    return hass.async_create_task(
        hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": option}, blocking=True)
    )


# ---------------------------------------------------------------- RM-B23
async def test_rm_b23_hanging_light_does_not_hold_the_update(hass, no_frontend_registration, freezer):
    lights, entry = await _setup(hass)
    sw = switch_entity(hass)
    lights.hang["light.a"] = asyncio.Event()
    _select(hass, "focus")
    await _settle()
    # both commands were sent at once; light.b has its values, light.a hangs
    assert lights.for_light("light.a") and lights.for_light("light.b")
    assert sw._update_lock.locked()  # waiting for light.a
    freezer.tick(timedelta(seconds=COMMAND_TIMEOUT_SECONDS + 1))
    await _settle()
    assert not sw._update_lock.locked()  # goes on without light.a
    # the next scenario reaches light.b at once; light.a gets no second command
    lights.calls.clear()
    _select(hass, "relax")
    await _settle()
    assert not sw._update_lock.locked()
    assert lights.for_light("light.b")
    assert lights.for_light("light.a") == []
    lights.release()
    await hass.async_block_till_done()


async def test_rm_b23_light_gets_commands_again_after_its_late_answer(hass, no_frontend_registration, freezer):
    lights, entry = await _setup(hass)
    om = core(hass, entry)["override_manager"]
    lights.hang["light.a"] = asyncio.Event()
    _select(hass, "focus")
    await _settle()
    freezer.tick(timedelta(seconds=COMMAND_TIMEOUT_SECONDS + 1))
    await _settle()
    assert not switch_entity(hass)._update_lock.locked()
    focus = om.tracking_snapshot("light.a")[0]
    # late success: the values arrived, the tracking stays
    lights.hang["light.a"].set()
    await _settle()
    assert om.tracking_snapshot("light.a")[0] == focus
    lights.calls.clear()
    del lights.hang["light.a"]
    _select(hass, "relax")
    await _settle()
    assert lights.for_light("light.a")  # no longer busy


async def test_rm_b23_late_error_restores_the_tracking(hass, no_frontend_registration, freezer):
    lights, entry = await _setup(hass)
    om = core(hass, entry)["override_manager"]
    before = om.tracking_snapshot("light.a")
    lights.hang["light.a"] = asyncio.Event()
    lights.fail_late.add("light.a")
    _select(hass, "focus")
    await _settle()
    assert om.tracking_snapshot("light.a") != before  # set before sending
    freezer.tick(timedelta(seconds=COMMAND_TIMEOUT_SECONDS + 1))
    await _settle()
    assert not switch_entity(hass)._update_lock.locked()
    lights.release()
    await _settle()
    assert om.tracking_snapshot("light.a") == before  # like a failed command (RM-B14)


async def test_rm_b23_apply_reports_a_light_without_answer(hass, no_frontend_registration, freezer):
    lights, entry = await _setup(hass)
    lights.hang["light.a"] = asyncio.Event()
    # the lights still report other values (the mock does not change them)
    call = hass.async_create_task(
        hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 0}, blocking=True)
    )
    await _settle()
    assert lights.for_light("light.a")
    assert not call.done()
    freezer.tick(timedelta(seconds=COMMAND_TIMEOUT_SECONDS + 1))
    await _settle()
    assert call.done()
    with pytest.raises(HomeAssistantError, match="No answer from light.a"):
        call.result()
    # still busy: a second apply sends nothing to it and reports it at once
    lights.calls.clear()
    with pytest.raises(HomeAssistantError, match="No answer from light.a"):
        await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 0}, blocking=True)
    assert lights.for_light("light.a") == []
    lights.release()
    await hass.async_block_till_done()


async def test_rm_b23_update_cancelled_while_waiting_handles_results(hass, no_frontend_registration, freezer):
    """Unload/shutdown during a hanging command: no unhandled task errors."""
    lights, entry = await _setup(hass)
    om = core(hass, entry)["override_manager"]
    before = om.tracking_snapshot("light.a")
    lights.hang["light.a"] = asyncio.Event()
    lights.fail_late.add("light.a")
    update = hass.async_create_task(switch_entity(hass).async_request_update())
    await _settle()
    assert lights.for_light("light.a")
    update.cancel()
    await _settle()
    lights.release()
    await _settle()
    assert om.tracking_snapshot("light.a") == before
