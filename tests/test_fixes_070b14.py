"""0.7.0b14: RM-T17 (Fast-HCL command), RM-B34 (permission check with the lights
resolved now), RM-B35 (empty target), RM-B36 (capability cache), RM-B37 (setup
does not wait for light commands), RM-B38 (disabled main switch), RM-B39 (log of
failing lights), RM-B40 (update_curve keys), RM-D05 (services.yaml)."""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import pytest
import yaml
from homeassistant.core import Context, State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache

from custom_components.hcl_lighting.const import CONF_CURVE_CONFIG, DOMAIN

from .helpers import CT_ATTRS, core, set_light, setup_entry, switch_entity
from .test_fixes_070b3 import SELECT, SENSOR, SWITCH, _hcl_on, _settle
from .test_fixes_070b3 import Lights as RecordingLights
from .test_fixes_070b8 import SlowLights
from .test_fixes_070b12 import ADAPT, DIM
from .test_regressions import CUSTOM_POINTS


class Lights(SlowLights):
    """SlowLights that also accept a single entity_id (Fast-HCL sends a string)."""

    async def _handle(self, call):
        self.calls.append(call)
        ids = call.data["entity_id"]
        eid = ids if isinstance(ids, str) else ids[0]
        if eid in self.hang:
            await self.hang[eid].wait()
            if eid in self.fail_late:
                raise HomeAssistantError(f"late device error {eid}")

    def for_light(self, entity_id):
        return [c for c in self.calls if entity_id in c.data["entity_id"]]


async def _setup(hass, options=None):
    lights = Lights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options)
    await _hcl_on(hass)
    return lights, entry


async def _switch_on_hanging(hass, lights, fail_late=False):
    """light.a is switched on at the device; its Fast-HCL command does not answer."""
    event = lights.hang["light.a"] = asyncio.Event()
    if fail_late:
        lights.fail_late.add("light.a")
    lights.calls.clear()
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await _settle()
    assert lights.for_light("light.a"), "Fast-HCL must send the values"
    return event


# ---------------------------------------------------------------- RM-T17
async def test_rm_t17_hanging_fast_hcl_does_not_hold_home_assistant(hass, no_frontend_registration):
    lights, _entry = await _setup(hass)
    await _switch_on_hanging(hass, lights)
    # Home Assistant's waiting for tasks (start, stop) does not wait for it
    await asyncio.wait_for(hass.async_block_till_done(), timeout=2)
    lights.release()
    await _settle()


async def test_rm_t17_no_second_command_while_fast_hcl_runs(hass, no_frontend_registration):
    lights, entry = await _setup(hass)
    controller = core(hass, entry)["controller"]
    await _switch_on_hanging(hass, lights)
    lights.calls.clear()
    result = await controller.apply_batch(["light.a"], 50, 3000, transition=0, fast_mode=True)
    assert result.pending == ["light.a"]
    assert lights.for_light("light.a") == []
    lights.release()
    await _settle()


async def test_rm_t17_late_answer_frees_the_light(hass, no_frontend_registration):
    lights, entry = await _setup(hass)
    controller = core(hass, entry)["controller"]
    om = core(hass, entry)["override_manager"]
    await _switch_on_hanging(hass, lights)
    sent = om.tracking_snapshot("light.a")
    lights.release()
    await _settle()
    assert "light.a" not in controller.commands.in_flight
    assert om.tracking_snapshot("light.a") == sent  # success: tracking stays


async def test_rm_t17_late_failure_restores_tracking_and_ends_protection(hass, no_frontend_registration):
    lights, entry = await _setup(hass, {"turn_on_transition": 5})
    om = core(hass, entry)["override_manager"]
    before = om.tracking_snapshot("light.a")
    event = await _switch_on_hanging(hass, lights, fail_late=True)
    assert om.is_reengaging("light.a")  # turn-on transition protected
    event.set()
    await _settle()
    assert om.tracking_snapshot("light.a") == before
    assert not om.is_reengaging("light.a")


# ---------------------------------------------------------------- RM-B34
async def test_rm_b34_switching_on_checks_the_lights_of_the_area_now(
    hass, no_frontend_registration, hass_read_only_user
):
    """A light joined the area while HCL was off: switching HCL on needs control of it."""
    lights = RecordingLights(hass)
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
    await _hcl_on(hass)
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


# ---------------------------------------------------------------- RM-B35
ANCHORS = {"wake_time": "07:00:00", "midday_time": "12:30:00", "sleep_time": "22:00:00"}


async def test_rm_b35_empty_target_is_rejected_in_the_options(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {"target": {"entity_id": []}, **ANCHORS, "smart_transition": False, "min_brightness": 10, "max_brightness": 100},
    )
    assert result["type"] == "form"
    assert result["errors"] == {"target": "no_lights"}


async def test_rm_b35_empty_target_is_rejected_at_setup(hass, no_frontend_registration):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "HCL", "target": {}, **ANCHORS}
    )
    assert result["type"] == "form"
    assert result["errors"] == {"target": "no_lights"}


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
    await _hcl_on(hass)
    assert sw.resolved_targets == set()


async def test_rm_b35_options_without_target_use_the_setup(hass, no_frontend_registration):
    set_light(hass, "light.a", "on", **DIM)
    await setup_entry(hass, ["light.a"], options={"transition": 5})
    assert switch_entity(hass).controlled_lights() == {"light.a"}


# ---------------------------------------------------------------- RM-B36
async def test_rm_b36_capability_is_evaluated_again_when_the_light_reports_more(
    hass, no_frontend_registration
):
    set_light(hass, "light.a", "on", brightness=128, supported_color_modes=["onoff"], color_mode="onoff")
    entry = await setup_entry(hass, ["light.a"])
    controller = core(hass, entry)["controller"]
    assert controller.capability_for("light.a", 3000) == "onoff"
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=2700, **CT_ATTRS)
    await hass.async_block_till_done()
    assert controller.capability_for("light.a", 3000) == "ct"
    # a light that is off keeps what it reported when it was on
    set_light(hass, "light.a", "off")
    assert controller.capability_for("light.a", 3000) == "ct"


# ---------------------------------------------------------------- RM-B37
async def test_rm_b37_setup_does_not_wait_for_light_commands(hass, no_frontend_registration):
    mock_restore_cache(hass, [State(SWITCH, "on")])
    lights = Lights(hass)
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
        await _settle()
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


# ---------------------------------------------------------------- RM-B39
async def test_rm_b39_failing_light_is_logged_once(hass, no_frontend_registration, caplog):
    lights = RecordingLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    lights.fail = {"light.a"}
    caplog.clear()
    await _hcl_on(hass)
    sw = switch_entity(hass)
    for _ in range(3):
        await sw._update_hcl()
        await hass.async_block_till_done()
    assert len(lights.for_light("light.a")) == 4  # tried again in every update
    reports = [
        r for r in caplog.records
        if r.levelno >= logging.WARNING and "Light update for light.a failed" in r.getMessage()
    ]
    assert len(reports) == 1 and reports[0].levelno == logging.WARNING
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING and r.exc_info]
    # the light answers again: one info, a later failure is reported again
    lights.fail = set()
    caplog.clear()
    await sw._update_hcl()
    await hass.async_block_till_done()
    assert "Light light.a accepts HCL commands again" in caplog.text


# ---------------------------------------------------------------- RM-B40
async def test_rm_b40_update_curve_stores_only_t_b_k(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    points = [dict(p) for p in CUSTOM_POINTS]
    points[0]["note"] = "x" * 50
    await hass.services.async_call(
        DOMAIN, "update_curve", {"entity_id": "sensor.hcl_curve_data", "mode": "save", "points": points},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_CURVE_CONFIG]["points"] == CUSTOM_POINTS


# ---------------------------------------------------------------- RM-D05
def test_rm_d05_services_yaml_matches_the_schema():
    path = Path(__file__).parent.parent / "custom_components" / "hcl_lighting" / "services.yaml"
    update_curve = yaml.safe_load(path.read_text(encoding="utf-8"))["update_curve"]
    assert "name" not in update_curve and "description" not in update_curve  # texts in strings.json
    mode = update_curve["fields"]["mode"]
    assert mode["required"] is False and mode["default"] == "preview"
