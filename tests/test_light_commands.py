"""Light commands: values, transitions, compatibility mode, failures, slow lights."""
from __future__ import annotations

import asyncio
import logging
import pytest

from datetime import timedelta
from homeassistant.components.light import ColorMode, LightEntity, LightEntityFeature
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockModule, MockPlatform, async_fire_time_changed, async_mock_service, mock_integration, mock_platform
from types import SimpleNamespace

from custom_components.hcl_lighting.const import COMMAND_TIMEOUT_SECONDS, DOMAIN, OWN_CONTEXT_SECONDS
from custom_components.hcl_lighting.logic import light_controller as lc
from custom_components.hcl_lighting.logic.units import kelvin_to_xy

from .support.entries import COLOR_ATTRS, CT_ATTRS, SWITCH, WARM_CT, calls_for, core, cycle_running, hcl_on, select_scenario, set_light, settle, setup_entry, setup_two_dim_lights, start_select, switch_entity, timer_cycle
from .support.lights import FakeLights


XY_CT_ATTRS = {
    "supported_color_modes": ["color_temp", "xy"],
    "color_mode": "color_temp",
    "min_color_temp_kelvin": 2700,
    "max_color_temp_kelvin": 6500,
}


ADAPT_B = "switch.hcl_adapt_brightness"


ADAPT_K = "switch.hcl_adapt_colour_temperature"


@pytest.fixture
async def noon(hass: HomeAssistant, freezer):
    """12:00 Europe/Berlin (default curve: 100 % / 6000 K)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-01-15 11:00:00+00:00")
    return freezer


async def _setup(hass, options=None):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options)
    await hcl_on(hass)
    return lights, entry


async def _switch_on_hanging(hass, lights, fail_late=False):
    """light.a is switched on at the device; its Fast-HCL command does not answer."""
    event = lights.hang["light.a"] = asyncio.Event()
    if fail_late:
        lights.fail_late.add("light.a")
    lights.calls.clear()
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await settle()
    assert lights.for_light("light.a"), "Fast-HCL must send the values"
    return event


def _tracking(om, entity_id):
    tracking = om.tracking_snapshot(entity_id)
    return tracking.last_set, tracking.ignore_until


async def _apply(hass, **data):
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, **data}, blocking=True)


class _CountingDict(dict):
    """Counts full scans of the remembered contexts."""

    scans = 0

    def items(self):
        type(self).scans += 1
        return super().items()

    def __iter__(self):
        type(self).scans += 1
        return super().__iter__()

    def keys(self):
        type(self).scans += 1
        return super().keys()

    def values(self):
        type(self).scans += 1
        return super().values()


def _byte(pct: int) -> int:
    return round(pct * 255 / 100)


async def _setup_light(hass, options=None):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options)
    await hcl_on(hass)
    return lights, core(hass, entry).override_manager, core(hass, entry).controller


async def _smart_update(hass, lights, brightness_pct, kelvin):
    """Light at the given values; one update cycle in the compatibility mode."""
    set_light(hass, "light.a", "on", brightness=_byte(brightness_pct), color_temp_kelvin=kelvin, **CT_ATTRS)
    await hass.async_block_till_done()
    lights.calls.clear()
    await timer_cycle(hass)
    await hass.async_block_till_done()
    await settle()
    return [dict(c.data) for c in lights.for_light("light.a")]


SMART = {"smart_transition": True, "transition": 20, "update_interval": 27}


class _ProbeLight(LightEntity):
    """Real light entity: records what Home Assistant passes to it."""

    _attr_supported_color_modes = {ColorMode.COLOR_TEMP}
    _attr_color_mode = ColorMode.COLOR_TEMP
    _attr_supported_features = LightEntityFeature.TRANSITION
    _attr_min_color_temp_kelvin = 2200
    _attr_max_color_temp_kelvin = 6500
    _attr_name = "probe"
    _attr_unique_id = "probe"

    def __init__(self, calls):
        self._calls = calls
        self._attr_is_on = True
        self._attr_brightness = 255
        self._attr_color_temp_kelvin = 6500

    async def async_turn_on(self, **kwargs):
        self._calls.append(dict(kwargs))
        if "brightness" in kwargs:
            self._attr_brightness = kwargs["brightness"]
        if "color_temp_kelvin" in kwargs:
            self._attr_color_temp_kelvin = kwargs["color_temp_kelvin"]
        self.async_write_ha_state()


@pytest.fixture
async def berlin(hass: HomeAssistant, freezer):
    """Fixed local time 12:00 Europe/Berlin (default curve: 100 % / 6000 K)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-01-15 11:00:00+00:00")
    return freezer


# ---------------------------------------------------------------- B-34
@pytest.mark.usefixtures("evening")
@pytest.mark.parametrize("kelvin", [2200, 2600, 4000, 6800])
async def test_rm_r09_light_with_colour_temperature_stays_in_ct_mode(hass, no_frontend_registration, kelvin):
    """RM-R09 (replaces the range check of B-34): a light with colour temperature
    gets it within its range, also for targets outside (no XY simulation)."""
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=4000, **XY_CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    ctl = core(hass, entry).controller
    assert ctl.capability_for("light.a") == "ct"
    calls.clear()
    await ctl.apply_batch(["light.a"], 50, kelvin)
    await hass.async_block_till_done()
    sent = [c.data for c in calls]
    assert sent and "xy_color" not in sent[-1]
    assert sent[-1]["color_temp_kelvin"] == min(6500, max(2700, kelvin))


# ---------------------------------------------------------------- RM-B43
def _xy(kelvin):
    return kelvin_to_xy(kelvin)


@pytest.mark.usefixtures("evening")
@pytest.mark.parametrize("kelvin", [2200, 4000])
async def test_rm_b43_light_in_xy_mode_goes_back_to_colour_temperature(hass, no_frontend_registration, kelvin):
    """A light with colour temperature in XY mode with about the XY of the
    target (e.g. left there by the XY simulation of 0.7) gets colour temperature."""
    calls = async_mock_service(hass, "light", "turn_on")
    attrs = {**XY_CT_ATTRS, "color_mode": "xy"}
    set_light(hass, "light.a", "on", brightness=128, xy_color=_xy(kelvin), **attrs)
    entry = await setup_entry(hass, ["light.a"])
    ctl = core(hass, entry).controller
    calls.clear()
    await ctl.apply_batch(["light.a"], 50, kelvin)
    await hass.async_block_till_done()
    sent = [c.data for c in calls]
    assert sent, "no command: the light stays in XY mode"
    assert "xy_color" not in sent[-1]
    assert sent[-1]["color_temp_kelvin"] == max(2700, kelvin)


@pytest.mark.usefixtures("evening")
async def test_rm_b43_light_that_keeps_reporting_xy_gets_no_repeated_command(hass, no_frontend_registration):
    """A light that reports XY after a colour temperature command is not sent the
    same values again in every cycle."""
    calls = async_mock_service(hass, "light", "turn_on")
    attrs = {**XY_CT_ATTRS, "color_mode": "xy"}
    set_light(hass, "light.a", "on", brightness=128, xy_color=_xy(2200), **attrs)
    entry = await setup_entry(hass, ["light.a"])
    ctl = core(hass, entry).controller
    calls.clear()
    await ctl.apply_batch(["light.a"], 50, 2200)
    await hass.async_block_till_done()
    assert len(calls) == 1
    # the light reports the values, but still in XY mode
    set_light(hass, "light.a", "on", brightness=128, xy_color=_xy(2700), **attrs)
    await hass.async_block_till_done()
    await ctl.apply_batch(["light.a"], 50, 2200)
    await hass.async_block_till_done()
    assert len(calls) == 1


# ---------------------------------------------------------------- B-35
@pytest.mark.usefixtures("evening")
@pytest.mark.parametrize("mode", ["rgbw", "rgbww"])
async def test_b35_rgbw_and_rgbww_lights_get_colour(hass, no_frontend_registration, mode):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(
        hass, "light.a", "on", brightness=255, supported_color_modes=[mode], color_mode=mode,
        xy_color=(0.31, 0.32),
    )
    await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    sent = calls_for(calls, "light.a")
    assert sent and "xy_color" in sent[-1].data


# ------------------------------------------------------------------ Ä-02
async def test_a02_adapt_switches_filter_commands(hass, noon, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    assert hass.states.get(ADAPT_B).state == "on" and hass.states.get(ADAPT_K).state == "on"
    sw = switch_entity(hass)

    await hass.services.async_call("switch", "turn_off", {"entity_id": ADAPT_B}, blocking=True)
    await sw.async_turn_on()
    await hass.async_block_till_done()
    sent = calls_for(calls, "light.a")
    assert sent and all("brightness_pct" not in c.data for c in sent)
    assert sent[-1].data["color_temp_kelvin"] == 6000

    calls.clear()
    await hass.services.async_call("switch", "turn_on", {"entity_id": ADAPT_B}, blocking=True)
    await hass.services.async_call("switch", "turn_off", {"entity_id": ADAPT_K}, blocking=True)
    await hass.async_block_till_done()
    sent = calls_for(calls, "light.a")
    assert sent and all("color_temp_kelvin" not in c.data for c in sent)
    assert sent[-1].data["brightness_pct"] == 100

    calls.clear()
    await hass.services.async_call("switch", "turn_off", {"entity_id": ADAPT_B}, blocking=True)
    await timer_cycle(hass)
    await hass.async_block_till_done()
    assert calls_for(calls, "light.a") == []


# ------------------------------------------------------------------ Ä-11
async def test_a11_interval_and_transitions(hass, noon, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    await setup_entry(
        hass, ["light.a"], options={"update_interval": 60, "transition": 5}
    )
    await switch_entity(hass).async_turn_on()
    await hass.async_block_till_done()
    assert calls_for(calls, "light.a")[-1].data["transition"] == 5
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)  # drift away
    calls.clear()
    noon.tick(timedelta(seconds=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls_for(calls, "light.a") == []
    noon.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    # the periodic update runs as a background task: let it finish (its
    # command is done), a light with a command still running gets no
    # Fast-HCL command (0.7.0b14, RM-T17)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert calls_for(calls, "light.a")
    calls.clear()
    set_light(hass, "light.a", "off", **CT_ATTRS)
    set_light(hass, "light.a", "on", brightness=13, color_temp_kelvin=2200, **CT_ATTRS)
    await hass.async_block_till_done()
    # switched on: the values at once, without transition (RM-R10)
    assert calls_for(calls, "light.a")[-1].data["transition"] == 0


# ---------------------------------------------------------------- RM-T17
async def test_rm_t17_hanging_fast_hcl_does_not_hold_home_assistant(hass, no_frontend_registration):
    lights, _entry = await _setup(hass)
    await _switch_on_hanging(hass, lights)
    # Home Assistant's waiting for tasks (start, stop) does not wait for it
    await asyncio.wait_for(hass.async_block_till_done(), timeout=2)
    lights.release()
    await settle()


async def test_rm_t17_no_second_command_while_fast_hcl_runs(hass, no_frontend_registration):
    lights, entry = await _setup(hass)
    controller = core(hass, entry).controller
    await _switch_on_hanging(hass, lights)
    lights.calls.clear()
    result = await controller.apply_batch(["light.a"], 50, 3000, transition=0, fast_mode=True)
    assert result.pending == ["light.a"]
    assert lights.for_light("light.a") == []
    lights.release()
    await settle()


async def test_rm_t17_late_answer_frees_the_light(hass, no_frontend_registration):
    lights, entry = await _setup(hass)
    controller = core(hass, entry).controller
    om = core(hass, entry).override_manager
    await _switch_on_hanging(hass, lights)
    sent = om.tracking_snapshot("light.a")
    lights.release()
    await settle()
    assert "light.a" not in controller.commands.in_flight
    assert om.tracking_snapshot("light.a") == sent  # success: tracking stays


async def test_rm_t17_late_failure_restores_tracking(hass, no_frontend_registration):
    lights, entry = await _setup(hass)
    om = core(hass, entry).override_manager
    before = om.tracking_snapshot("light.a")
    event = await _switch_on_hanging(hass, lights, fail_late=True)
    # without transition when switched on (RM-R10): no protection
    assert not om.is_reengaging("light.a")
    event.set()
    await settle()
    assert om.tracking_snapshot("light.a") == before


# ---------------------------------------------------------------- RM-B36
async def test_rm_b36_capability_is_evaluated_again_when_the_light_reports_more(
    hass, no_frontend_registration
):
    set_light(hass, "light.a", "on", brightness=128, supported_color_modes=["onoff"], color_mode="onoff")
    entry = await setup_entry(hass, ["light.a"])
    controller = core(hass, entry).controller
    assert controller.capability_for("light.a") == "onoff"
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=2700, **CT_ATTRS)
    await hass.async_block_till_done()
    assert controller.capability_for("light.a") == "ct"
    # a light that is off keeps what it reported when it was on
    set_light(hass, "light.a", "off")
    assert controller.capability_for("light.a") == "ct"


# ---------------------------------------------------------------- RM-B39
async def test_rm_b39_failing_light_is_logged_once(hass, no_frontend_registration, caplog):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    lights.fail = {"light.a"}
    caplog.clear()
    await hcl_on(hass)
    for _ in range(3):
        await timer_cycle(hass)
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
    await timer_cycle(hass)
    await hass.async_block_till_done()
    assert "Light light.a accepts HCL commands again" in caplog.text


# ---------------------------------------------------------------- RM-B03
async def test_rm_b03_ct_light_gets_the_kelvin_it_can_reach(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.warm", "on", brightness=3, color_temp_kelvin=2200, **WARM_CT)
    set_light(hass, "light.wide", "on", brightness=3, color_temp_kelvin=2200, **CT_ATTRS)
    await setup_entry(hass, ["light.warm", "light.wide"], options={"focus_kelvin": 6500})
    await hcl_on(hass)
    lights.calls.clear()
    await select_scenario(hass, "focus")
    assert lights.for_light("light.warm")[-1].data["color_temp_kelvin"] == 4000
    assert lights.for_light("light.wide")[-1].data["color_temp_kelvin"] == 6500
    assert all(len(c.data["entity_id"]) == 1 for c in lights.calls)  # 0.7.0b4: one command per light


async def test_rm_b03_turn_on_and_smart_transition_are_limited_too(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.warm", "off", **WARM_CT)
    await setup_entry(hass, ["light.warm"], options={"focus_kelvin": 6500, "smart_transition": True})
    await hcl_on(hass)
    await select_scenario(hass, "focus")
    lights.calls.clear()
    set_light(hass, "light.warm", "on", brightness=3, color_temp_kelvin=2200, **WARM_CT)  # switched on
    # Fast-HCL runs in the background since 0.7.0b14 (RM-T17)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert lights.for_light("light.warm")[-1].data["color_temp_kelvin"] == 4000
    lights.calls.clear()
    set_light(hass, "light.warm", "on", brightness=3, color_temp_kelvin=2200, **WARM_CT)
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 5, "release_manual_control": True}, blocking=True)
    kelvins = {c.data["color_temp_kelvin"] for c in lights.for_light("light.warm") if "color_temp_kelvin" in c.data}
    assert kelvins == {4000}


# ---------------------------------------------------------------- RM-B04
async def test_rm_b04_failed_command_is_not_reported_as_updated(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    set_light(hass, "light.b", "on", brightness=3, xy_color=(0.6, 0.35), **COLOR_ATTRS)
    entry = await setup_entry(hass, ["light.a", "light.b"])
    await hcl_on(hass)
    om = core(hass, entry).override_manager
    before = om.last_set("light.b")
    lights.fail = {"light.b"}
    set_light(hass, "light.b", "on", brightness=200, xy_color=(0.2, 0.2), **COLOR_ATTRS)
    om.reset_override("light.b")
    with pytest.raises(HomeAssistantError):  # 0.7.0b4: apply reports failed lights
        await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 120}, blocking=True)
    assert om.is_reengaging("light.a")
    assert not om.is_reengaging("light.b")  # its command failed
    assert om.last_set("light.b") == before  # tracking restored


# ---------------------------------------------------------------- RM-B05
async def test_rm_b05_final_smart_transition_failure_is_reported(hass, no_frontend_registration, caplog):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"smart_transition": True})
    await hcl_on(hass)
    om = core(hass, entry).override_manager
    lights.fail = {"light.a"}
    set_light(hass, "light.a", "on", brightness=200, color_temp_kelvin=6000, **CT_ATTRS)
    om.reset_override("light.a")
    caplog.clear()
    with pytest.raises(HomeAssistantError):  # 0.7.0b4: apply reports failed lights
        await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 120}, blocking=True)
    assert not om.is_reengaging("light.a")
    assert "Smart transition for light.a failed" in caplog.text  # primary: warning
    # final failure: logged (since 0.7.0b14 a warning, once per failure streak, RM-B39)
    assert any(
        r.levelname in ("WARNING", "ERROR") and "Light update for light.a failed" in r.getMessage()
        for r in caplog.records
    )


async def test_rm_b05_fallback_success_counts(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"smart_transition": True})
    await hcl_on(hass)
    om = core(hass, entry).override_manager
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


# ---------------------------------------------------------------- RM-B13 (review RM-B12)
async def test_rm_b13_partial_failure_keeps_the_successful_light(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    set_light(hass, "light.b", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a", "light.b"])
    await hcl_on(hass)
    om = core(hass, entry).override_manager
    before_b = _tracking(om, "light.b")[0]
    lights.fail = {"light.b"}
    try:
        await _apply(hass, transition=120)
    except HomeAssistantError:
        pass  # reported since RM-B16
    target = core(hass, entry).controller.calculate_target_values(dt_util.now())
    assert _tracking(om, "light.a")[0][0] == target[0]  # light.a got the values
    assert _tracking(om, "light.b")[0] == before_b
    assert om.is_reengaging("light.a") and not om.is_reengaging("light.b")
    assert all(len(c.data["entity_id"]) == 1 for c in lights.calls)  # one command per light


# ---------------------------------------------------------------- RM-B14 (review RM-B13)
async def test_rm_b14_failed_command_restores_the_ignore_window(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    om = core(hass, entry).override_manager
    before = _tracking(om, "light.a")
    lights.fail = {"light.a"}
    try:
        await _apply(hass, transition=120)
    except HomeAssistantError:
        pass  # reported since RM-B16
    assert _tracking(om, "light.a") == before  # values and ignore window as before


# ---------------------------------------------------------------- RM-B15 (review RM-B14)
async def test_rm_b15_failed_turn_on_update_restores_the_tracking(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    om = core(hass, entry).override_manager
    before = _tracking(om, "light.a")
    lights.fail = {"light.a"}
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)  # switched on
    # Fast-HCL runs in the background since 0.7.0b14 (RM-T17)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert lights.for_light("light.a")  # HCL tried
    assert _tracking(om, "light.a") == before


async def test_rm_b15_successful_turn_on_update_keeps_the_tracking(hass, no_frontend_registration):
    FakeLights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    om = core(hass, entry).override_manager
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await hass.async_block_till_done()
    last_set, ignore_until = _tracking(om, "light.a")
    assert last_set is not None and ignore_until is not None


# ---------------------------------------------------------------- RM-R10 (replaces RM-B21)
async def test_rm_r10_switched_on_without_transition_and_without_protection(
    hass, no_frontend_registration, freezer
):
    """The turn-on transition of 0.6/0.7 is gone: a light switched on gets the
    values at once, the update cycles are not held back."""
    lights = FakeLights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(
        hass, ["light.a"], options={"update_interval": 10, "transition": 5, "turn_on_transition": 30}
    )
    assert "turn_on_transition" not in entry.options  # removed by the migration
    await hcl_on(hass)
    om = core(hass, entry).override_manager
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)  # switched on
    await hass.async_block_till_done(wait_background_tasks=True)
    assert lights.for_light("light.a")[-1].data["transition"] == 0
    assert not om.is_reengaging("light.a")
    # the light did not take the values (e.g. no answer): the next cycle sends again
    lights.calls.clear()
    freezer.tick(timedelta(seconds=10))
    await timer_cycle(hass)
    await hass.async_block_till_done()
    assert lights.for_light("light.a")[-1].data["transition"] == 5


async def test_rm_b21_failed_turn_on_command_sets_no_protection(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"turn_on_transition": 30})
    await hcl_on(hass)
    lights.fail = {"light.a"}
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    # Fast-HCL runs in the background since 0.7.0b14 (RM-T17)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert lights.for_light("light.a")
    assert not core(hass, entry).override_manager.is_reengaging("light.a")


# ---------------------------------------------------------------- RM-T11
async def test_rm_t11_expired_contexts_are_removed_without_full_scans(hass, no_frontend_registration, monkeypatch):
    FakeLights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    controller = core(hass, entry).controller
    clock = [1000.0]
    # only the controller's clock (the event loop keeps the real one)
    monkeypatch.setattr(lc, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    controller._own_contexts = _CountingDict(controller._own_contexts)
    _CountingDict.scans = 0

    parent = Context()
    old = [controller._new_context(parent) for _ in range(500)]
    clock[0] += OWN_CONTEXT_SECONDS / 2
    young = [controller._new_context() for _ in range(500)]
    assert all(controller.is_own_context(c) for c in old + young)
    # a state change caused by an HCL command (context = child of the command)
    assert controller.is_own_context(Context(parent_id=old[0].id))

    clock[0] += OWN_CONTEXT_SECONDS / 2 + 1  # the first 500 are expired
    newest = controller._new_context()
    assert not any(controller.is_own_context(c) for c in old)
    assert not controller.is_own_context(Context(parent_id=old[0].id))
    assert all(controller.is_own_context(c) for c in young + [newest])
    assert len(controller._own_contexts) == 501
    # 1001 commands, none of them searched all remembered contexts
    assert _CountingDict.scans == 0


# ---------------------------------------------------------------- RM-B23
async def test_rm_b23_hanging_light_does_not_hold_the_update(hass, no_frontend_registration, freezer):
    lights, entry = await setup_two_dim_lights(hass)
    lights.hang["light.a"] = asyncio.Event()
    start_select(hass, "focus")
    await settle()
    # both commands were sent at once; light.b has its values, light.a hangs
    assert lights.for_light("light.a") and lights.for_light("light.b")
    assert cycle_running(hass)  # waiting for light.a
    freezer.tick(timedelta(seconds=COMMAND_TIMEOUT_SECONDS + 1))
    await settle()
    assert not cycle_running(hass)  # goes on without light.a
    # the next scenario reaches light.b at once; light.a gets no second command
    lights.calls.clear()
    start_select(hass, "relax")
    await settle()
    assert not cycle_running(hass)
    assert lights.for_light("light.b")
    assert lights.for_light("light.a") == []
    lights.release()
    await hass.async_block_till_done()


async def test_rm_b23_light_gets_commands_again_after_its_late_answer(hass, no_frontend_registration, freezer):
    lights, entry = await setup_two_dim_lights(hass)
    om = core(hass, entry).override_manager
    lights.hang["light.a"] = asyncio.Event()
    start_select(hass, "focus")
    await settle()
    freezer.tick(timedelta(seconds=COMMAND_TIMEOUT_SECONDS + 1))
    await settle()
    assert not cycle_running(hass)
    focus = om.tracking_snapshot("light.a")[0]
    # late success: the values arrived, the tracking stays
    lights.hang["light.a"].set()
    await settle()
    assert om.tracking_snapshot("light.a")[0] == focus
    lights.calls.clear()
    del lights.hang["light.a"]
    start_select(hass, "relax")
    await settle()
    assert lights.for_light("light.a")  # no longer busy


async def test_rm_b23_late_error_restores_the_tracking(hass, no_frontend_registration, freezer):
    lights, entry = await setup_two_dim_lights(hass)
    om = core(hass, entry).override_manager
    before = om.tracking_snapshot("light.a")
    lights.hang["light.a"] = asyncio.Event()
    lights.fail_late.add("light.a")
    start_select(hass, "focus")
    await settle()
    assert om.tracking_snapshot("light.a") != before  # set before sending
    freezer.tick(timedelta(seconds=COMMAND_TIMEOUT_SECONDS + 1))
    await settle()
    assert not cycle_running(hass)
    lights.release()
    await settle()
    assert om.tracking_snapshot("light.a") == before  # like a failed command (RM-B14)


async def test_rm_b23_update_cancelled_while_waiting_handles_results(hass, no_frontend_registration, freezer):
    """Unload/shutdown during a hanging command: no unhandled task errors."""
    lights, entry = await setup_two_dim_lights(hass)
    om = core(hass, entry).override_manager
    before = om.tracking_snapshot("light.a")
    lights.hang["light.a"] = asyncio.Event()
    lights.fail_late.add("light.a")
    update = hass.async_create_task(switch_entity(hass).async_request_update())
    await settle()
    assert lights.for_light("light.a")
    update.cancel()
    await settle()
    lights.release()
    await settle()
    assert om.tracking_snapshot("light.a") == before


# ---------------------------------------------------------------- RM-B42
async def test_rm_b42_colour_temperature_is_sent_with_transition_0(hass, no_frontend_registration, freezer):
    lights, om, controller = await _setup_light(hass, SMART)
    target_b, target_k = controller.calculate_target_values(dt_util.now())
    freezer.tick(timedelta(seconds=60))
    # brightness changes more than the colour temperature: colour snaps, brightness fades
    far_b = 100 if target_b < 50 else 1
    near_k = target_k + 200 if target_k < 6000 else target_k - 200
    sent = await _smart_update(hass, lights, far_b, near_k)
    colour = [d for d in sent if "color_temp_kelvin" in d]
    assert colour and all(d.get("transition") == 0 for d in colour), sent
    assert any(d.get("transition") == 20 for d in sent if "brightness_pct" in d), sent


async def test_rm_b42_large_colour_change_is_sent_with_transition_0(hass, no_frontend_registration, freezer):
    lights, om, controller = await _setup_light(hass, SMART)
    target_b, target_k = controller.calculate_target_values(dt_util.now())
    freezer.tick(timedelta(seconds=60))
    # colour temperature changes more than the brightness: both snap
    far_k = 2000 if target_k > 4250 else 6500
    sent = await _smart_update(hass, lights, target_b, far_k)
    colour = [d for d in sent if "color_temp_kelvin" in d]
    assert colour and all(d.get("transition") == 0 for d in colour), sent


async def test_rm_b42_fallback_is_sent_with_transition_0(hass, no_frontend_registration, freezer):
    lights, om, controller = await _setup_light(hass, SMART)
    target_b, target_k = controller.calculate_target_values(dt_util.now())
    freezer.tick(timedelta(seconds=60))
    lights.fail.add("light.a")
    far_b = 100 if target_b < 50 else 1
    sent = await _smart_update(hass, lights, far_b, target_k + 300 if target_k < 6000 else target_k - 300)
    fallback = sent[-1]
    assert "brightness_pct" in fallback and "color_temp_kelvin" in fallback, sent
    assert fallback.get("transition") == 0, sent


async def test_rm_b42_default_light_profile_does_not_add_a_transition(
    hass, no_frontend_registration, tmp_path
):
    """With a default transition in light_profiles.csv, Home Assistant added it
    to the colour command of the compatibility mode (IKEA: the colour faded and
    the brightness command came during the colour transition)."""
    calls: list[dict] = []
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "light_profiles.csv").write_text(
        "id,x,y,brightness,transition\ngroup.all_lights.default,,,,2\n"
    )

    probe = _ProbeLight(calls)

    async def _setup_platform(hass, config, add, discovery_info=None):
        add([probe])

    mock_integration(hass, MockModule("probe"))
    mock_platform(hass, "probe.light", MockPlatform(async_setup_platform=_setup_platform))
    assert await async_setup_component(hass, "light", {"light": {"platform": "probe"}})
    await hass.async_block_till_done()
    entry = await setup_entry(hass, ["light.probe"], SMART)
    # light far from the HCL values: both values change
    target_b, target_k = core(hass, entry).controller.calculate_target_values(dt_util.now())
    probe._attr_brightness = 255 if target_b < 50 else 3
    probe._attr_color_temp_kelvin = 2200 if target_k > 4350 else 6500
    probe.async_write_ha_state()
    await hass.async_block_till_done()
    await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    await hass.async_block_till_done()
    for _ in range(50):
        await asyncio.sleep(0)
    colour = [c for c in calls if "color_temp_kelvin" in c]
    assert colour, calls
    assert all(c.get("transition", 0) == 0 for c in colour), calls


# ---------------------------------------------------------------- B-05
async def test_b05_xy_light_is_not_resent_every_cycle(hass, berlin, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    xy_attrs = {"supported_color_modes": ["xy"], "color_mode": "xy"}
    set_light(hass, "light.rgb", "on", brightness=10, xy_color=(0.5, 0.4), **xy_attrs)
    await setup_entry(hass, ["light.rgb"])
    sw = switch_entity(hass)
    await sw.async_turn_on()
    await hass.async_block_till_done()
    sent = calls_for(calls, "light.rgb")
    assert sent, "first cycle must send"
    x, y = sent[-1].data["xy_color"]
    # Light reports exactly what was sent (xy mode => color_temp_kelvin is None).
    set_light(hass, "light.rgb", "on", brightness=255, xy_color=(round(x, 4), round(y, 4)), color_temp_kelvin=None, **xy_attrs)
    await hass.async_block_till_done()
    calls.clear()
    await timer_cycle(hass)
    await hass.async_block_till_done()
    assert calls_for(calls, "light.rgb") == []


async def test_b05_clamped_ct_light_is_not_resent_every_cycle(hass, berlin, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    attrs = dict(CT_ATTRS, min_color_temp_kelvin=2200, max_color_temp_kelvin=4000)
    set_light(hass, "light.ikea", "on", brightness=255, color_temp_kelvin=4000, **attrs)
    await setup_entry(hass, ["light.ikea"])
    sw = switch_entity(hass)
    await sw.async_turn_on()
    await hass.async_block_till_done()
    assert calls_for(calls, "light.ikea") == [], "light already at its maximum reachable CT and 100 %"
    await timer_cycle(hass)
    await hass.async_block_till_done()
    assert calls_for(calls, "light.ikea") == []


async def test_b05_ct_light_in_range_still_updates(hass, berlin, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=4000, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    await switch_entity(hass).async_turn_on()
    await hass.async_block_till_done()
    sent = calls_for(calls, "light.a")
    assert sent and sent[-1].data["color_temp_kelvin"] == 6000


async def test_b05_clamped_light_brightness_change_still_updates(hass, berlin, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    attrs = dict(CT_ATTRS, min_color_temp_kelvin=2200, max_color_temp_kelvin=4000)
    set_light(hass, "light.ikea", "on", brightness=100, color_temp_kelvin=4000, **attrs)
    await setup_entry(hass, ["light.ikea"])
    await switch_entity(hass).async_turn_on()
    await hass.async_block_till_done()
    assert calls_for(calls, "light.ikea")
