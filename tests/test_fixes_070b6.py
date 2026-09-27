"""0.7.0b6: fixes RM-B21 and RM-B22 of the roadmap."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.util import dt as dt_util

from custom_components.hcl_lighting.const import DOMAIN

from .helpers import CT_ATTRS, core, set_light, setup_entry, switch_entity
from .test_fixes_070b3 import SWITCH, Lights, _hcl_on


# ---------------------------------------------------------------- RM-B21
async def test_rm_b21_turn_on_transition_is_not_cut_short(hass, no_frontend_registration, freezer):
    lights = Lights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(
        hass, ["light.a"], options={"update_interval": 10, "transition": 5, "turn_on_transition": 30}
    )
    await _hcl_on(hass)
    om = core(hass, entry)["override_manager"]
    target_b, target_k = core(hass, entry)["controller"].calculate_target_values(dt_util.now())
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)  # switched on
    await hass.async_block_till_done()
    assert lights.for_light("light.a")[-1].data["transition"] == 30
    lights.calls.clear()
    sw = switch_entity(hass)
    # the next update cycles run while the light reports values on its way
    for seconds in (10, 20):
        freezer.tick(timedelta(seconds=10))
        progress = seconds / 30
        set_light(
            hass, "light.a", "on",
            brightness=round((3 + (target_b - 3) * progress) * 255 / 100),
            color_temp_kelvin=round(2000 + (target_k - 2000) * progress), **CT_ATTRS,
        )
        await hass.async_block_till_done()
        await sw._update_hcl()
        await hass.async_block_till_done()
        assert lights.for_light("light.a") == [], seconds
    assert not om.is_overridden("light.a")
    # after the turn-on transition the normal adaptation resumes
    freezer.tick(timedelta(seconds=15))
    await sw._update_hcl()
    await hass.async_block_till_done()
    assert lights.for_light("light.a")[-1].data["transition"] == 5


async def test_rm_b21_failed_turn_on_command_sets_no_protection(hass, no_frontend_registration):
    lights = Lights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"turn_on_transition": 30})
    await _hcl_on(hass)
    lights.fail = {"light.a"}
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await hass.async_block_till_done()
    assert lights.for_light("light.a")
    assert not core(hass, entry)["override_manager"].is_reengaging("light.a")


# ---------------------------------------------------------------- RM-B22
async def _long_apply(hass, entry):
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 120}, blocking=True)
    assert core(hass, entry)["override_manager"].is_reengaging("light.a")


async def test_rm_b22_hcl_off_and_on_takes_the_light_back_at_once(hass, no_frontend_registration):
    lights = Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
    await _long_apply(hass, entry)
    await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    lights.calls.clear()
    await _hcl_on(hass)
    assert lights.for_light("light.a")  # sent right away, not after 120 s
    assert not core(hass, entry)["override_manager"].is_reengaging("light.a")


async def test_rm_b22_reload_takes_the_light_back_at_once(hass, no_frontend_registration):
    lights = Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
    await _long_apply(hass, entry)
    lights.calls.clear()
    assert await hass.config_entries.async_reload(entry.entry_id)  # e.g. options saved
    await hass.async_block_till_done()
    assert lights.for_light("light.a")
    assert not core(hass, entry)["override_manager"].is_reengaging("light.a")


async def test_rm_b22_turn_on_while_on_keeps_a_running_transition(hass, no_frontend_registration):
    Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
    await _long_apply(hass, entry)
    await _hcl_on(hass)  # already on (e.g. an automation): nothing is restarted
    assert core(hass, entry)["override_manager"].is_reengaging("light.a")
