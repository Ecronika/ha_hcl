"""Setup, reload, restart, unload and removal of an instance."""
from __future__ import annotations

import asyncio
import pytest
import time

from datetime import timedelta
from homeassistant.core import Context, HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service, mock_restore_cache

from custom_components.hcl_lighting import DATA_OVERRIDE_MANAGERS
from custom_components.hcl_lighting.const import COMMAND_TIMEOUT_SECONDS, CONF_MAX_BRIGHTNESS, DOMAIN

from .support.entries import CT_ATTRS, DIM, SELECT, SWITCH, calls_for, core, hcl_on, select_scenario, set_light, settle, setup_entry, setup_two_dim_lights, start_select, switch_entity
from .support.lights import FakeLights


async def _reload_in(hass, option):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    await select_scenario(hass, option)
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    calls.clear()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    return calls, entry


ADAPT_B = "switch.hcl_adapt_brightness"


ADAPT_K = "switch.hcl_adapt_colour_temperature"


LATE = timedelta(seconds=COMMAND_TIMEOUT_SECONDS + 1)


async def _hanging_focus(hass, freezer, lights, fail_late=False):
    """Focus: light.a does not answer, the update goes on without it (RM-B23)."""
    event = lights.hang["light.a"] = asyncio.Event()
    if fail_late:
        lights.fail_late.add("light.a")
    start_select(hass, "focus")
    await settle()
    freezer.tick(LATE)
    await settle()
    return event


async def _reload(hass, entry, freezer):
    """Reload the entry (options or title saved) while light.a still hangs."""
    task = hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))
    await settle()
    freezer.tick(LATE)  # older versions: a second command to light.a hangs too
    await hass.async_block_till_done()
    assert task.result() is True


async def _long_apply(hass, entry):
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 120}, blocking=True)
    assert core(hass, entry).override_manager.is_reengaging("light.a")


# ---------------------------------------------------------------- B-31
@pytest.mark.usefixtures("evening")
async def test_b31_reload_in_guest_mode_sends_nothing(hass, no_frontend_registration):
    calls, _entry = await _reload_in(hass, "guest")
    assert hass.states.get(SELECT).state == "guest"
    assert calls_for(calls, "light.a") == []


@pytest.mark.usefixtures("evening")
async def test_b31_reload_in_focus_mode_applies_focus_first(hass, no_frontend_registration):
    calls, _entry = await _reload_in(hass, "focus")
    sent = calls_for(calls, "light.a")
    assert sent
    assert sent[0].data.get("brightness_pct") == 100
    assert sent[0].data.get("color_temp_kelvin") == 5500


@pytest.mark.usefixtures("evening")
async def test_b31_expired_timed_scenario_restores_as_auto(hass, no_frontend_registration, freezer):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"scenario_duration": 30})
    await hcl_on(hass)
    await select_scenario(hass, "focus")
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=45))
    calls.clear()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "auto"
    assert all(c.data.get("color_temp_kelvin") != 5500 for c in calls_for(calls, "light.a"))


# ------------------------------------------------------------------ Ä-02
async def test_a02_flags_survive_reload_and_restart(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    # Restart: the entity is registered and its last state was stored
    entry = MockConfigEntry(domain=DOMAIN, title="HCL", data={"name": "HCL", "target": {"entity_id": ["light.a"]}})
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "switch", DOMAIN, f"{entry.entry_id}_adapt_color",
        suggested_object_id="hcl_adapt_colour_temperature", config_entry=entry,
    )
    mock_restore_cache(hass, [State(ADAPT_K, "off")])
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert core(hass, entry).controller.adapt_color is False  # restart
    assert hass.states.get(ADAPT_K).state == "off"
    await hass.services.async_call("switch", "turn_off", {"entity_id": ADAPT_B}, blocking=True)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "max_brightness": 90})
    await hass.async_block_till_done()
    ctl = core(hass, entry).controller
    assert ctl.adapt_brightness is False and ctl.adapt_color is False  # reload


# ------------------------------------------------------------------ Ä-06
async def test_a06_persist_across_restart(hass, hass_storage, no_frontend_registration):
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"persist_overrides": True})
    core(hass, entry).override_manager.set_override("light.a")
    await hass.config_entries.async_unload(entry.entry_id)
    hass.bus.async_fire("homeassistant_final_write")
    await hass.async_block_till_done()
    assert f"{DOMAIN}.overrides.{entry.entry_id}" in hass_storage
    hass.data[DATA_OVERRIDE_MANAGERS].pop(entry.entry_id)  # restart: in-memory state gone
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert core(hass, entry).override_manager.is_overridden("light.a")


async def test_a06_no_persistence_by_default(hass, hass_storage, no_frontend_registration):
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    core(hass, entry).override_manager.set_override("light.a")
    await hass.config_entries.async_unload(entry.entry_id)
    hass.data[DATA_OVERRIDE_MANAGERS].pop(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert not core(hass, entry).override_manager.is_overridden("light.a")


# ---------------------------------------------------------------- RM-B30
async def test_rm_b30_busy_light_gets_no_second_command_after_reload(
    hass, no_frontend_registration, freezer
):
    lights, entry = await setup_two_dim_lights(hass)
    om = core(hass, entry).override_manager
    before = om.tracking_snapshot("light.a")
    await _hanging_focus(hass, freezer, lights, fail_late=True)
    lights.calls.clear()
    await _reload(hass, entry, freezer)
    assert lights.for_light("light.b")  # the new instance sends its values
    assert lights.for_light("light.a") == []  # the command of the old one is still running
    lights.release()
    await settle()
    assert om.tracking_snapshot("light.a") == before  # late error: rollback as before (RM-B14)


async def test_rm_b30_switched_on_while_the_old_command_runs(
    hass, no_frontend_registration, freezer
):
    """light.a is switched off and on while the command of the old instance
    still runs: no second command (since 0.7.0b14 also for Fast-HCL, RM-T17;
    until 0.7.0b13 the new instance sent its values at once). The late error
    of the old command rolls back its own tracking."""
    lights, entry = await setup_two_dim_lights(hass)
    om = core(hass, entry).override_manager
    before = om.tracking_snapshot("light.a")
    event = await _hanging_focus(hass, freezer, lights, fail_late=True)
    await _reload(hass, entry, freezer)
    del lights.hang["light.a"]
    lights.calls.clear()
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await settle()
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await hass.async_block_till_done()
    assert lights.for_light("light.a") == []
    event.set()  # the old command fails now
    await settle()
    assert om.tracking_snapshot("light.a") == before


async def test_rm_b30_late_answer_after_reload_is_no_manual_control(
    hass, no_frontend_registration, freezer
):
    lights, entry = await setup_two_dim_lights(hass)
    om = core(hass, entry).override_manager
    event = await _hanging_focus(hass, freezer, lights)
    old_command = lights.for_light("light.a")[-1]
    await _reload(hass, entry, freezer)
    event.set()
    await settle()
    freezer.tick(timedelta(seconds=30))  # after the ignore window
    # the light reports the result of the old command late (an intermediate
    # value of the transition), with the context of that command
    hass.states.async_set(
        "light.a", "on", {"brightness": 26, "color_temp_kelvin": 2500, **CT_ATTRS},
        context=old_command.context,
    )
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")


# ---------------------------------------------------------------- RM-T14
async def test_rm_t14_hanging_fast_mode_command_is_a_background_task(
    hass, no_frontend_registration, freezer
):
    lights, entry = await setup_two_dim_lights(hass)
    controller = core(hass, entry).controller
    lights.hang["light.a"] = asyncio.Event()
    result = await controller.apply_batch(["light.a"], 50, 3000, transition=0, fast_mode=True)
    assert result.updated == ["light.a"]
    await settle()
    assert lights.for_light("light.a")
    # Home Assistant does not wait for it (start, stop, block_till_done)
    waiting = hass.async_create_task(hass.async_block_till_done())
    await settle()
    assert waiting.done()
    lights.release()
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_rm_t14_fast_mode_command_with_context_of_a_reloaded_instance(
    hass, no_frontend_registration, freezer
):
    """Smooth return started before a reload: its state reports stay HCL's own."""
    lights, entry = await setup_two_dim_lights(hass)
    controller = core(hass, entry).controller
    om = core(hass, entry).override_manager
    event = lights.hang["light.a"] = asyncio.Event()
    await controller.apply_batch(["light.a"], 50, 3000, transition=30, fast_mode=True)
    await settle()
    command = lights.for_light("light.a")[-1]
    await _reload(hass, entry, freezer)
    assert core(hass, entry).controller is not controller
    event.set()
    await settle()
    hass.states.async_set(
        "light.a", "on", {"brightness": 64, "color_temp_kelvin": 2600, **CT_ATTRS},
        context=Context(parent_id=command.context.id),
    )
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")


# ---------------------------------------------------------------- RM-B37
async def test_rm_b37_setup_does_not_wait_for_light_commands(hass, no_frontend_registration):
    mock_restore_cache(hass, [State(SWITCH, "on")])
    lights = FakeLights(hass)
    lights.hang["light.a"] = asyncio.Event()
    # far from the HCL values at any time of day: the first update sends a command
    set_light(hass, "light.a", "on", brightness=200, color_temp_kelvin=6400, **CT_ATTRS)
    entry = MockConfigEntry(domain=DOMAIN, title="HCL", data={"name": "HCL", "target": {"entity_id": ["light.a"]}})
    entry.add_to_hass(hass)
    task = hass.async_create_task(hass.config_entries.async_setup(entry.entry_id))
    # up to about 8 s of real time for the setup (platform imports run in the
    # executor; slow under load), independent of the event loop clock (the
    # tests may freeze it). Until 0.7.0b13 the setup waited for the hanging
    # command up to COMMAND_TIMEOUT_SECONDS (10 s).
    for _ in range(800):
        if task.done():
            break
        await hass.async_add_executor_job(time.sleep, 0.01)
    done = task.done()
    # the first update runs in the background and sends at once (RM-B22);
    # its command still hangs
    for _ in range(20):
        if lights.for_light("light.a"):
            break
        await settle()
    sent = bool(lights.for_light("light.a"))
    lights.release()
    assert await task
    assert done, "setup waited for the light command"
    assert sent
    assert hass.states.get(SWITCH).state == "on"
    await hass.async_block_till_done(wait_background_tasks=True)


# ---------------------------------------------------------------- RM-B38
@pytest.mark.parametrize(
    "service,data",
    [
        ("apply", {"entity_id": SELECT}),
        ("set_manual_control", {"entity_id": SELECT, "manual_control": False}),
        ("set_scenario", {"entity_id": SELECT, "scenario": "focus"}),
    ],
)
async def test_rm_b38_disabled_main_switch_gives_a_clear_error(
    hass, no_frontend_registration, service, data
):
    set_light(hass, "light.a", "on", **DIM)
    entry = MockConfigEntry(domain=DOMAIN, title="HCL", data={"name": "HCL", "target": {"entity_id": ["light.a"]}})
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "switch", DOMAIN, entry.entry_id, config_entry=entry, suggested_object_id="hcl_hcl_active",
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH) is None
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, service, data, blocking=True)
    assert err.value.translation_key == "main_switch_disabled"


# ---------------------------------------------------------------- RM-B22
async def test_rm_b22_hcl_off_and_on_takes_the_light_back_at_once(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    await _long_apply(hass, entry)
    await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    lights.calls.clear()
    await hcl_on(hass)
    assert lights.for_light("light.a")  # sent right away, not after 120 s
    assert not core(hass, entry).override_manager.is_reengaging("light.a")


async def test_rm_b22_reload_takes_the_light_back_at_once(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    await _long_apply(hass, entry)
    lights.calls.clear()
    assert await hass.config_entries.async_reload(entry.entry_id)  # e.g. options saved
    await hass.async_block_till_done()
    assert lights.for_light("light.a")
    assert not core(hass, entry).override_manager.is_reengaging("light.a")


async def test_rm_b22_turn_on_while_on_keeps_a_running_transition(hass, no_frontend_registration):
    FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    await _long_apply(hass, entry)
    await hcl_on(hass)  # already on (e.g. an automation): nothing is restarted
    assert core(hass, entry).override_manager.is_reengaging("light.a")


# ---------------------------------------------------------------- B-06
async def test_b06_override_survives_entry_reload(hass, no_frontend_registration):
    async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    om = core(hass, entry).override_manager
    om.set_last_set_values("light.a", 50, 4000)
    om.check_override("light.a", State("light.a", "on", {"brightness": 255, "color_temp_kelvin": 4000}), None)
    assert om.is_overridden("light.a")

    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_MAX_BRIGHTNESS: 90})
    await hass.async_block_till_done()
    assert core(hass, entry).override_manager.is_overridden("light.a")


async def test_b06_override_state_dropped_when_entry_removed(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id not in hass.data.get(f"{DOMAIN}_override_managers", {})


async def test_setup_and_turn_on(hass: HomeAssistant, no_frontend_registration) -> None:
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=10, color_temp_kelvin=2700, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    for entity_id in ("switch.hcl_hcl_active", "sensor.hcl_curve_data", "select.hcl_scenario"):
        assert hass.states.get(entity_id) is not None, entity_id
    await switch_entity(hass).async_turn_on()
    await hass.async_block_till_done()
    assert calls, "HCL should have sent an update"
