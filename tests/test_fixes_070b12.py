"""0.7.0b12: RM-B30, RM-T14 (light commands across reloads, fast mode),
RM-B31 (permissions of the lights an action controls), RM-B32 (diagnostics),
RM-H06 (translatable error messages)."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from datetime import timedelta

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.hcl_lighting.const import COMMAND_TIMEOUT_SECONDS, DOMAIN

from .helpers import CT_ATTRS, core, set_light, setup_entry, switch_entity
from .test_fixes_070b3 import SELECT, SENSOR, SWITCH, Lights, _hcl_on, _settle
from .test_fixes_070b8 import _select, _setup

LATE = timedelta(seconds=COMMAND_TIMEOUT_SECONDS + 1)


async def _hanging_focus(hass, freezer, lights, fail_late=False):
    """Focus: light.a does not answer, the update goes on without it (RM-B23)."""
    event = lights.hang["light.a"] = asyncio.Event()
    if fail_late:
        lights.fail_late.add("light.a")
    _select(hass, "focus")
    await _settle()
    freezer.tick(LATE)
    await _settle()
    return event


async def _reload(hass, entry, freezer):
    """Reload the entry (options or title saved) while light.a still hangs."""
    task = hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))
    await _settle()
    freezer.tick(LATE)  # older versions: a second command to light.a hangs too
    await hass.async_block_till_done()
    assert task.result() is True


# ---------------------------------------------------------------- RM-B30
async def test_rm_b30_busy_light_gets_no_second_command_after_reload(
    hass, no_frontend_registration, freezer
):
    lights, entry = await _setup(hass)
    om = core(hass, entry)["override_manager"]
    before = om.tracking_snapshot("light.a")
    await _hanging_focus(hass, freezer, lights, fail_late=True)
    lights.calls.clear()
    await _reload(hass, entry, freezer)
    assert lights.for_light("light.b")  # the new instance sends its values
    assert lights.for_light("light.a") == []  # the command of the old one is still running
    lights.release()
    await _settle()
    assert om.tracking_snapshot("light.a") == before  # late error: rollback as before (RM-B14)


async def test_rm_b30_late_error_keeps_the_tracking_of_a_newer_command(
    hass, no_frontend_registration, freezer
):
    lights, entry = await _setup(hass)
    om = core(hass, entry)["override_manager"]
    before = om.tracking_snapshot("light.a")
    event = await _hanging_focus(hass, freezer, lights, fail_late=True)
    await _reload(hass, entry, freezer)
    # light.a is switched off and on: the new instance sends its values at once
    del lights.hang["light.a"]
    lights.calls.clear()
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await _settle()
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await hass.async_block_till_done()
    assert lights.for_light("light.a")
    newer = om.tracking_snapshot("light.a")
    assert newer != before
    event.set()  # the old command fails now
    await _settle()
    assert om.tracking_snapshot("light.a") == newer


async def test_rm_b30_late_answer_after_reload_is_no_manual_control(
    hass, no_frontend_registration, freezer
):
    lights, entry = await _setup(hass)
    om = core(hass, entry)["override_manager"]
    event = await _hanging_focus(hass, freezer, lights)
    old_command = lights.for_light("light.a")[-1]
    await _reload(hass, entry, freezer)
    event.set()
    await _settle()
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
    lights, entry = await _setup(hass)
    controller = core(hass, entry)["controller"]
    lights.hang["light.a"] = asyncio.Event()
    result = await controller.apply_batch(["light.a"], 50, 3000, transition=0, fast_mode=True)
    assert result.updated == ["light.a"]
    await _settle()
    assert lights.for_light("light.a")
    # Home Assistant does not wait for it (start, stop, block_till_done)
    waiting = hass.async_create_task(hass.async_block_till_done())
    await _settle()
    assert waiting.done()
    lights.release()
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_rm_t14_fast_mode_command_with_context_of_a_reloaded_instance(
    hass, no_frontend_registration, freezer
):
    """Smooth return started before a reload: its state reports stay HCL's own."""
    lights, entry = await _setup(hass)
    controller = core(hass, entry)["controller"]
    om = core(hass, entry)["override_manager"]
    event = lights.hang["light.a"] = asyncio.Event()
    await controller.apply_batch(["light.a"], 50, 3000, transition=30, fast_mode=True)
    await _settle()
    command = lights.for_light("light.a")[-1]
    await _reload(hass, entry, freezer)
    assert core(hass, entry)["controller"] is not controller
    event.set()
    await _settle()
    hass.states.async_set(
        "light.a", "on", {"brightness": 64, "color_temp_kelvin": 2600, **CT_ATTRS},
        context=Context(parent_id=command.context.id),
    )
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")


# ---------------------------------------------------------------- RM-B31
ADAPT = "switch.hcl_adapt_brightness"
DIM = {"brightness": 3, "color_temp_kelvin": 2000, **CT_ATTRS}


async def _two_lights(hass, hcl_on=True):
    lights = Lights(hass)
    for eid in ("light.a", "light.b"):
        set_light(hass, eid, "on", **DIM)
    entry = await setup_entry(hass, ["light.a", "light.b"])
    if hcl_on:
        await _hcl_on(hass)
    lights.calls.clear()
    return lights, entry


def _user_without_light_b(user):
    """May use all HCL entities and light.a, not light.b."""
    user.mock_policy(
        {"entities": {"entity_ids": {SWITCH: True, SELECT: True, SENSOR: True, ADAPT: True, "light.a": True}}}
    )
    return Context(user_id=user.id)


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
    lights, _entry = await _two_lights(hass, hcl_on=False)
    await hass.services.async_call("switch", "turn_off", {"entity_id": ADAPT}, blocking=True)
    await _hcl_on(hass) if entity_id != SWITCH else None
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


# ---------------------------------------------------------------- RM-B32
async def test_rm_b32_diagnostics_without_names_ids_and_times(hass, no_frontend_registration, freezer):
    from homeassistant.helpers import area_registry as ar
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.hcl_lighting.diagnostics import async_get_config_entry_diagnostics

    Lights(hass)
    area = ar.async_get(hass).async_create("Schlafzimmer Tobias")
    for eid in ("light.schlafzimmer_decke", "light.bad_spiegel"):
        set_light(hass, eid, "on", **DIM)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Schlafzimmer Tobias",
        data={"name": "Schlafzimmer Tobias", "target": {"entity_id": ["light.bad_spiegel"]}},
        options={
            "target": {"entity_id": ["light.schlafzimmer_decke", "light.bad_spiegel"], "area_id": [area.id]},
            "wake_time": "06:15",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await switch_entity(hass).async_turn_on()
    await hass.async_block_till_done()
    core(hass, entry)["override_manager"].set_override("light.schlafzimmer_decke")
    freezer.tick(timedelta(minutes=7))

    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(diag, default=str)
    for private in ("Tobias", "schlafzimmer", "bad_spiegel", area.id):
        assert private not in text
    # one light, one pseudonym in every part
    lights = diag["targets"]
    assert lights == ["light.redacted_1", "light.redacted_2"]
    decke = next(p for p in lights if diag["lights"][p]["manual_control"])
    assert diag["manual_control_minutes"] == {decke: 7}
    spiegel = next(p for p in lights if p != decke)
    assert diag["options"]["target"]["entity_id"] == [decke, spiegel]
    assert diag["options"]["target"]["area_id"] == ["area_1"]
    assert diag["data"]["target"]["entity_id"] == [spiegel]
    assert diag["title"] == diag["data"]["name"] == "**REDACTED**"
    # what is needed to understand the behaviour stays
    assert diag["lights"][spiegel]["capability"] == "ct"
    assert diag["scenario"] == "auto" and diag["active_curve"]
    assert diag["options"]["wake_time"] == "06:15"


# ---------------------------------------------------------------- RM-H06
INTEGRATION = Path(__file__).parents[1] / "custom_components" / DOMAIN


def _exceptions(name):
    return json.loads((INTEGRATION / name).read_text(encoding="utf-8")).get("exceptions", {})


def test_rm_h06_every_error_message_is_translated():
    keys_in_code = set()
    for source in INTEGRATION.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        keys_in_code |= set(re.findall(r'translation_key="(\w+)"', text))
        # no error with a fixed text for the caller
        assert not re.search(r"raise (HomeAssistantError|ServiceValidationError)\(\s*f?[\"']", text), source.name
    keys_in_code |= {"lights_failed", "lights_no_answer", "lights_failed_and_no_answer"}  # chosen at runtime
    issues = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))["issues"]
    keys_in_code -= set(issues)  # repair issues use translation_key too
    strings, en, de = (_exceptions(n) for n in ("strings.json", "translations/en.json", "translations/de.json"))
    assert keys_in_code and keys_in_code == set(strings) == set(en) == set(de)
    for key in strings:
        placeholders = set(re.findall(r"{(\w+)}", strings[key]["message"]))
        assert set(re.findall(r"{(\w+)}", de[key]["message"])) == placeholders, key


async def test_rm_h06_errors_carry_their_translation(hass, no_frontend_registration):
    lights, _entry = await _two_lights(hass)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "apply", {"entity_id": SWITCH, "lights": ["light.other"]}, blocking=True
        )
    assert err.value.translation_key == "not_controlled"
    assert str(err.value) == "Not controlled by this HCL instance: light.other"
    lights.fail = {"light.b"}
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH}, blocking=True)
    assert err.value.translation_key == "lights_failed"
    assert err.value.translation_placeholders["failed"] == "light.b"
    assert str(err.value).startswith("Light update failed for light.b: ")


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
