"""Detection of manual control (commands, device reports, HCL's own reports)."""
from __future__ import annotations

import logging
import pytest

from datetime import timedelta
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.hcl_lighting.const import DOMAIN, EVENT_MANUAL_CONTROL

from .support.entries import CT_ATTRS, SWITCH, calls_for, core, hcl_on, set_light, settle, setup_entry, switch_entity, timer_cycle
from .support.lights import FakeLights


async def _after_hcl_command(hass, freezer):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    om = core(hass, entry).override_manager
    await hcl_on(hass)
    sent = calls_for(calls, "light.a")
    assert sent
    freezer.tick(timedelta(seconds=60))  # well after the ignore window
    return sent[-1].context, om


ADAPT_B = "switch.hcl_adapt_brightness"


@pytest.fixture
async def noon(hass: HomeAssistant, freezer):
    """12:00 Europe/Berlin (default curve: 100 % / 6000 K)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-01-15 11:00:00+00:00")
    return freezer


async def _user_turn_on(hass, **data):
    """A light command from outside HCL (app, scene, automation)."""
    await hass.services.async_call("light", "turn_on", data, blocking=True)
    await hass.async_block_till_done()


ON = {"brightness": 128, "color_temp_kelvin": 4000, **CT_ATTRS}  # 50 %, not the HCL value


DIVERGENCE_LOG = "inside the ignore window"


@pytest.fixture
async def _late_morning(hass: HomeAssistant, freezer):
    """11:00 Europe/Berlin (default curve: 100 %, morning plateau)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-01-15 10:00:00+00:00")


async def _in_ignore_window(hass):
    """HCL just sent its values to light.a (ignore window running)."""
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", **ON)
    entry = await setup_entry(hass, ["light.a"])
    await switch_entity(hass).async_turn_on()
    await hass.async_block_till_done()
    assert calls
    return core(hass, entry).override_manager


def _byte(pct: int) -> int:
    return round(pct * 255 / 100)


async def _report(hass, context, brightness_pct=None, kelvin=None, state="on"):
    """State report of light.a with the context Home Assistant gives it.

    Home Assistant keeps the context of the last command for state changes of
    the light within 5 seconds, also for a change made on the device.
    """
    old = hass.states.get("light.a")
    attrs = dict(old.attributes) if old else dict(CT_ATTRS)
    if brightness_pct is not None:
        attrs["brightness"] = _byte(brightness_pct)
    if kelvin is not None:
        attrs["color_temp_kelvin"] = kelvin
    hass.states.async_set("light.a", state, attrs, context=context)
    await hass.async_block_till_done()


async def _setup(hass):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    om = core(hass, entry).override_manager
    controller = core(hass, entry).controller
    return lights, om, controller


def _away(target: int) -> tuple[int, int]:
    """(value at the command, value the user dims to) on opposite sides of the target."""
    if target > 60:
        return 100, target - 30  # e.g. light on at 100 %, HCL 68 %, user 38 %
    return 1, target + 30


async def _switched_on(hass, lights, om, start_pct):
    """The light is switched on at the device; HCL sends its values at once."""
    lights.calls.clear()
    set_light(hass, "light.a", "on", brightness=_byte(start_pct), color_temp_kelvin=2700, **CT_ATTRS)
    await hass.async_block_till_done()
    sent = lights.for_light("light.a")
    assert sent, "Fast-HCL must send the values"
    return sent[-1].context


async def _report_attrs(hass, context, state="on", **attrs):
    """State report of light.a (attributes of the last state, changed by attrs)."""
    old = hass.states.get("light.a")
    data = dict(old.attributes) if old else dict(CT_ATTRS)
    for key, value in attrs.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    hass.states.async_set("light.a", state, data, context=context)
    await hass.async_block_till_done()


async def _setup_light(hass, options=None):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options)
    await hcl_on(hass)
    return lights, core(hass, entry).override_manager, core(hass, entry).controller


async def _switched_on_ctx(hass, lights, start_pct=50, kelvin=2700):
    """Switched on at the device; Fast-HCL sends its values (context returned)."""
    lights.calls.clear()
    set_light(hass, "light.a", "on", brightness=_byte(start_pct), color_temp_kelvin=kelvin, **CT_ATTRS)
    await hass.async_block_till_done()
    sent = lights.for_light("light.a")
    assert sent, "Fast-HCL must send the values"
    return sent[-1].context


def _events(hass):
    seen = []
    hass.bus.async_listen(EVENT_MANUAL_CONTROL, lambda e: seen.append(e.data))
    return seen


@pytest.fixture
async def berlin(hass: HomeAssistant, freezer):
    """Fixed local time 12:00 Europe/Berlin (default curve: 100 % / 6000 K)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-01-15 11:00:00+00:00")
    return freezer


# ---------------------------------------------------------------- B-33
@pytest.mark.usefixtures("evening")
async def test_b33_late_state_report_with_hcl_context_is_not_manual(hass, no_frontend_registration, freezer):
    ctx, om = await _after_hcl_command(hass, freezer)
    hass.states.async_set(
        "light.a", "on", {**CT_ATTRS, "brightness": 150, "color_temp_kelvin": 4000}, context=ctx
    )
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")


@pytest.mark.usefixtures("evening")
async def test_b33_child_context_of_hcl_command_is_not_manual(hass, no_frontend_registration, freezer):
    ctx, om = await _after_hcl_command(hass, freezer)
    hass.states.async_set(
        "light.a", "on", {**CT_ATTRS, "brightness": 150, "color_temp_kelvin": 4000},
        context=Context(parent_id=ctx.id),
    )
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")


@pytest.mark.usefixtures("evening")
async def test_b33_foreign_state_change_is_still_manual(hass, no_frontend_registration, freezer):
    _ctx, om = await _after_hcl_command(hass, freezer)
    hass.states.async_set(
        "light.a", "on", {**CT_ATTRS, "brightness": 150, "color_temp_kelvin": 4000}, context=Context()
    )
    await hass.async_block_till_done()
    assert om.is_overridden("light.a")


# ------------------------------------------------------------------ Ä-01
async def test_a01_ha_command_with_values_pauses_light(hass, noon, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    sw = switch_entity(hass)
    await sw.async_turn_on()
    await hass.async_block_till_done()
    om = core(hass, entry).override_manager
    assert not om.is_overridden("light.a"), "HCL's own commands are no manual control"

    # Inside the ignore window, towards the HCL target: previously undetectable
    await _user_turn_on(hass, entity_id="light.a", brightness_pct=90)
    assert om.is_overridden("light.a")
    calls.clear()
    await timer_cycle(hass)
    await hass.async_block_till_done()
    assert calls_for(calls, "light.a") == []
    assert hass.states.get(SWITCH).attributes["manual_control"] == ["light.a"]


async def test_a01_area_target_and_toggle_and_plain_turn_on(hass, noon, no_frontend_registration):
    async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "light", "toggle")
    area = ar.async_get(hass).async_create("Wohnen")
    ent = er.async_get(hass).async_get_or_create("light", "test", "1", suggested_object_id="a")
    er.async_get(hass).async_update_entity(ent.entity_id, area_id=area.id)
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    set_light(hass, "light.other", "on", brightness=128, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await switch_entity(hass).async_turn_on()
    om = core(hass, entry).override_manager

    await _user_turn_on(hass, entity_id="light.a")  # no values
    await hass.services.async_call("light", "toggle", {"entity_id": "light.a", "brightness_pct": 5}, blocking=True)
    await _user_turn_on(hass, entity_id="light.other", brightness_pct=5)  # not an HCL light
    assert not om.is_overridden("light.a")

    await _user_turn_on(hass, area_id=area.id, color_temp_kelvin=2700)
    assert om.is_overridden("light.a")


async def test_a01_turn_on_values_default_and_option(hass, noon, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await switch_entity(hass).async_turn_on()
    # Default (unchanged behaviour): HCL values are applied on turn-on
    await _user_turn_on(hass, entity_id="light.a", brightness_pct=5)
    set_light(hass, "light.a", "on", brightness=13, color_temp_kelvin=2200, **CT_ATTRS)
    await hass.async_block_till_done()
    fast = [c for c in calls_for(calls, "light.a") if c.data.get("brightness_pct") == 100]
    assert fast, "fast path must still apply HCL by default"
    assert not core(hass, entry).override_manager.is_overridden("light.a")

    # Option: keep the values of turn-on commands
    set_light(hass, "light.a", "off", **CT_ATTRS)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "respect_turn_on_values": True})
    await hass.async_block_till_done()
    calls.clear()
    await _user_turn_on(hass, entity_id="light.a", brightness_pct=5)
    set_light(hass, "light.a", "on", brightness=13, color_temp_kelvin=2200, **CT_ATTRS)
    await hass.async_block_till_done()
    assert [c for c in calls_for(calls, "light.a") if c.data.get("brightness_pct") == 100] == []
    assert core(hass, entry).override_manager.is_overridden("light.a")


# ------------------------------------------------------------------ Ä-02
async def test_a02_brightness_change_is_no_override_when_not_adapted(hass, noon, no_frontend_registration):
    async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hass.services.async_call("switch", "turn_off", {"entity_id": ADAPT_B}, blocking=True)
    await switch_entity(hass).async_turn_on()
    om = core(hass, entry).override_manager
    await _user_turn_on(hass, entity_id="light.a", brightness_pct=30)
    noon.tick(timedelta(seconds=60))
    set_light(hass, "light.a", "on", brightness=77, color_temp_kelvin=6000, **CT_ATTRS)
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")
    await _user_turn_on(hass, entity_id="light.a", color_temp_kelvin=2700)
    assert om.is_overridden("light.a")


# ---------------------------------------------------------------- RM-D03
@pytest.mark.usefixtures("_late_morning")
async def test_rm_d03_switch_off_in_the_ignore_window_logs_no_divergence(
    hass, no_frontend_registration, caplog
):
    om = await _in_ignore_window(hass)
    om.set_override("light.a")
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="custom_components.hcl_lighting"):
        set_light(hass, "light.a", "off", **CT_ATTRS)
        await hass.async_block_till_done()
    assert "ignore window" not in caplog.text.lower()  # 0.7.0b9: "Override detected inside Ignore Window!"
    assert not om.is_overridden("light.a")  # switching off ends manual control, also in the window


@pytest.mark.usefixtures("_late_morning")
async def test_rm_d03_change_away_in_the_ignore_window_is_still_detected(
    hass, no_frontend_registration, caplog
):
    om = await _in_ignore_window(hass)
    with caplog.at_level(logging.DEBUG, logger="custom_components.hcl_lighting"):
        set_light(hass, "light.a", "on", **{**ON, "brightness": 26})  # 50 % -> 10 %, away from 100 %
        await hass.async_block_till_done()
    assert f"{DIVERGENCE_LOG} for light.a" in caplog.text
    assert om.is_overridden("light.a")


# ---------------------------------------------------------------- RM-B33
async def test_rm_b33_dimming_at_the_device_after_switching_on_is_manual(hass, no_frontend_registration):
    lights, om, controller = await _setup(hass)
    target, _k = controller.calculate_target_values(dt_util.now())
    start, user = _away(target)
    ctx = await _switched_on(hass, lights, om, start)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report(hass, ctx, target_b, target_k)  # the light reaches the HCL values
    assert not om.is_overridden("light.a")
    await _report(hass, ctx, user)  # dimmed at the wall dimmer 1.5 s later
    assert om.is_overridden("light.a")
    # the next update leaves the light alone
    lights.calls.clear()
    await timer_cycle(hass)
    await hass.async_block_till_done()
    assert lights.for_light("light.a") == []


async def test_rm_b33_dimming_at_the_device_after_an_update_is_manual(hass, no_frontend_registration, freezer):
    lights, om, controller = await _setup(hass)
    ctx = await _switched_on(hass, lights, om, 50)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report(hass, ctx, target_b, target_k)
    freezer.tick(timedelta(seconds=30))  # after the ignore window of the command
    # an update sends new values (scenario), the light reports them
    lights.calls.clear()
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.hcl_scenario", "option": "relax"}, blocking=True
    )
    await hass.async_block_till_done()
    await settle()
    sent = lights.for_light("light.a")
    assert sent
    ctx2 = sent[-1].context
    b2, k2 = om.tracking_snapshot("light.a")[0]
    await _report(hass, ctx2, b2, k2)
    assert not om.is_overridden("light.a")
    user = b2 - 30 if b2 > 40 else b2 + 30
    await _report(hass, ctx2, user)
    # at once (beyond the value before the update) or when the transition
    # has ended (back towards it); the update leaves the user's value
    freezer.tick(timedelta(seconds=30))
    lights.calls.clear()
    await timer_cycle(hass)
    await hass.async_block_till_done()
    assert om.is_overridden("light.a")
    assert lights.for_light("light.a") == []


async def test_rm_b33_colour_change_at_the_device_is_manual(hass, no_frontend_registration):
    lights, om, controller = await _setup(hass)
    ctx = await _switched_on(hass, lights, om, 50)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report(hass, ctx, target_b, target_k)
    user_k = 2000 if target_k > 4000 else 6500
    await _report(hass, ctx, kelvin=user_k)
    assert om.is_overridden("light.a")


async def test_rm_b33_change_of_a_group_member_is_manual(hass, no_frontend_registration):
    lights, om, controller = await _setup(hass)
    target, _k = controller.calculate_target_values(dt_util.now())
    start, user = _away(target)
    ctx = await _switched_on(hass, lights, om, start)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report(hass, Context(parent_id=ctx.id), target_b, target_k)
    await _report(hass, Context(parent_id=ctx.id), user)
    assert om.is_overridden("light.a")


async def test_rm_b33_dimming_back_towards_the_switch_on_value_is_manual(
    hass, no_frontend_registration, freezer
):
    """The 0.7.0b12 field test: switched on, HCL sends its value, the user dims
    at once towards the value the light had - decided after the transition."""
    lights, om, controller = await _setup(hass)
    target, _k = controller.calculate_target_values(dt_util.now())
    start = 100 if target <= 60 else 1
    ctx = await _switched_on(hass, lights, om, start)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report(hass, ctx, target_b, target_k)
    user = (start + target_b) // 2
    await _report(hass, ctx, user)  # could still be the device's transition
    assert not om.is_overridden("light.a")
    freezer.tick(timedelta(seconds=10))  # the transition has ended
    lights.calls.clear()
    await timer_cycle(hass)
    await hass.async_block_till_done()
    assert om.is_overridden("light.a")
    assert lights.for_light("light.a") == []  # the user's value stays


# ---------------------------------------------------------------- RM-B45
async def test_rm_b45_failed_command_keeps_an_open_report(hass, no_frontend_registration, freezer):
    """An open report (RM-B33) stays open when the next command fails: the
    change on the device is still decided after the transition."""
    lights, om, controller = await _setup(hass)
    target, _k = controller.calculate_target_values(dt_util.now())
    start = 100 if target <= 60 else 1
    ctx = await _switched_on(hass, lights, om, start)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report(hass, ctx, target_b, target_k)
    await _report(hass, ctx, (start + target_b) // 2)  # open: decided after the transition
    lights.fail.add("light.a")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH}, blocking=True)
    await hass.async_block_till_done()
    lights.fail.clear()
    freezer.tick(timedelta(seconds=10))  # the transition has ended
    lights.calls.clear()
    await timer_cycle(hass)
    await hass.async_block_till_done()
    assert om.is_overridden("light.a")
    assert lights.for_light("light.a") == []  # the user's value stays


async def test_rm_b33_open_report_is_left_alone_while_the_transition_runs(hass, no_frontend_registration):
    lights, om, controller = await _setup(hass)
    target, _k = controller.calculate_target_values(dt_util.now())
    start = 100 if target <= 60 else 1
    ctx = await _switched_on(hass, lights, om, start)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report(hass, ctx, target_b, target_k)
    await _report(hass, ctx, (start + target_b) // 2)
    lights.calls.clear()
    await timer_cycle(hass)  # still inside the ignore window
    await hass.async_block_till_done()
    assert lights.for_light("light.a") == []
    assert not om.is_overridden("light.a")


async def test_rm_b33_intermediate_values_of_the_transition_stay_own(hass, no_frontend_registration, freezer):
    """Values between the light's value at the command and the target, in any
    order (e.g. the target first, then the device's own reports), are HCL's
    when the light ends at the target."""
    lights, om, controller = await _setup(hass)
    target, _k = controller.calculate_target_values(dt_util.now())
    start, _user = _away(target)
    ctx = await _switched_on(hass, lights, om, start)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    middle = (start + target_b) // 2
    for value in (target_b, middle, (middle + target_b) // 2, target_b):
        await _report(hass, ctx, value, target_k)
        assert not om.is_overridden("light.a"), value
    freezer.tick(timedelta(seconds=10))
    await timer_cycle(hass)
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")


async def test_rm_b33_ramp_towards_the_target_after_the_window_stays_own(hass, no_frontend_registration, freezer):
    """A device that ramps slowly (e.g. a KNX actuator with a dimming time)."""
    lights, om, controller = await _setup(hass)
    target, _k = controller.calculate_target_values(dt_util.now())
    start, _user = _away(target)
    ctx = await _switched_on(hass, lights, om, start)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    freezer.tick(timedelta(seconds=10))  # after the ignore window
    for step in (1, 2, 3, 4):
        value = start + (target_b - start) * step // 4
        await _report(hass, ctx, value, target_k)
        assert not om.is_overridden("light.a"), value


async def test_rm_b33_brightness_not_adapted_is_not_checked(hass, no_frontend_registration):
    lights, om, controller = await _setup(hass)
    controller.adapt_brightness = False
    ctx = await _switched_on(hass, lights, om, 50)
    _b, target_k = om.tracking_snapshot("light.a")[0]
    await _report(hass, ctx, 50, target_k)
    await _report(hass, ctx, 90)
    assert not om.is_overridden("light.a")


async def test_rm_b33_switching_off_with_hcl_context_is_no_manual_control(hass, no_frontend_registration):
    lights, om, controller = await _setup(hass)
    ctx = await _switched_on(hass, lights, om, 50)
    await _report(hass, ctx, state="off")
    assert not om.is_overridden("light.a")


async def test_rm_b33_colour_light_changed_at_the_device_is_manual(hass, no_frontend_registration):
    """Colour lights (XY simulation): the distance to the HCL colour decides."""
    lights = FakeLights(hass)
    xy = {"supported_color_modes": ["xy"], "color_mode": "xy"}
    set_light(hass, "light.a", "off", **xy)
    entry = await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    om = core(hass, entry).override_manager
    set_light(hass, "light.a", "on", brightness=128, xy_color=(0.4, 0.4), **xy)
    await hass.async_block_till_done()
    sent = lights.for_light("light.a")
    assert sent and "xy_color" in sent[-1].data
    ctx, target_xy = sent[-1].context, tuple(sent[-1].data["xy_color"])
    target_b = om.tracking_snapshot("light.a")[0][0]
    attrs = {"brightness": _byte(target_b), **xy}
    # on the way from the colour at switching on to the HCL colour: HCL's own
    middle = ((0.4 + target_xy[0]) / 2, (0.4 + target_xy[1]) / 2)
    for value in (target_xy, middle, target_xy):
        hass.states.async_set("light.a", "on", {**attrs, "xy_color": value}, context=ctx)
        await hass.async_block_till_done()
        assert not om.is_overridden("light.a"), value
    # a colour chosen on the device (e.g. the manufacturer's remote)
    hass.states.async_set("light.a", "on", {**attrs, "xy_color": (0.15, 0.06)}, context=ctx)
    await hass.async_block_till_done()
    assert om.is_overridden("light.a")


# ---------------------------------------------------------------- RM-B41
async def test_rm_b41_on_with_brightness_0_after_switching_on_is_not_manual(hass, no_frontend_registration):
    """KNX: the brightness status 0 arrives just after the switching status
    (with the context of the Fast-HCL command)."""
    lights, om, _controller = await _setup_light(hass)
    seen = _events(hass)
    ctx = await _switched_on_ctx(hass, lights, 31)
    await _report_attrs(hass, ctx, brightness=0)
    assert not om.is_overridden("light.a")
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report_attrs(hass, ctx, brightness=_byte(target_b), color_temp_kelvin=target_k)
    assert not om.is_overridden("light.a")
    assert seen == []


async def test_rm_b41_switched_on_with_brightness_0_first_is_not_manual(hass, no_frontend_registration):
    """KNX: switching status first ("on" with 0 %), the brightness status (the
    actuator's switch-on value) just after it, before HCL's value arrives."""
    lights, om, controller = await _setup_light(hass)
    seen = _events(hass)
    target, _k = controller.calculate_target_values(dt_util.now())
    lights.calls.clear()
    set_light(hass, "light.a", "on", brightness=0, color_temp_kelvin=2700, **CT_ATTRS)
    await hass.async_block_till_done()
    sent = lights.for_light("light.a")
    assert sent, "Fast-HCL must send the values"
    ctx = sent[-1].context
    actuator = min(100, target + 30)
    await _report_attrs(hass, ctx, brightness=_byte(actuator))
    assert not om.is_overridden("light.a")
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report_attrs(hass, ctx, brightness=_byte(target_b), color_temp_kelvin=target_k)
    assert not om.is_overridden("light.a")
    assert seen == []


async def test_rm_b41_report_without_brightness_after_switching_on_is_not_manual(hass, no_frontend_registration):
    lights, om, _controller = await _setup_light(hass)
    ctx = await _switched_on_ctx(hass, lights, 31)
    await _report_attrs(hass, ctx, brightness=None)
    assert not om.is_overridden("light.a")


async def test_rm_b41_colour_is_still_checked_with_brightness_0(hass, no_frontend_registration):
    """Brightness 0 carries no brightness information; the colour still counts."""
    lights, om, _controller = await _setup_light(hass)
    ctx = await _switched_on_ctx(hass, lights, 31)
    _b, target_k = om.tracking_snapshot("light.a")[0]
    user_k = 2000 if target_k > 4000 else 6500
    await _report_attrs(hass, ctx, brightness=0, color_temp_kelvin=user_k)
    assert om.is_overridden("light.a")


async def test_rm_b41_dimming_after_brightness_0_is_still_manual(hass, no_frontend_registration):
    lights, om, controller = await _setup_light(hass)
    target, _k = controller.calculate_target_values(dt_util.now())
    start, user = (100, target - 30) if target > 60 else (1, target + 30)
    ctx = await _switched_on_ctx(hass, lights, start)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report_attrs(hass, ctx, brightness=0)
    await _report_attrs(hass, ctx, brightness=_byte(target_b), color_temp_kelvin=target_k)
    await _report_attrs(hass, ctx, brightness=_byte(user))
    assert om.is_overridden("light.a")


async def test_rm_b41_on_with_brightness_0_when_switching_off_is_not_manual(
    hass, no_frontend_registration, freezer
):
    """Switching off at the device (no HCL context): "on" with 0 %, then "off"."""
    lights, om, _controller = await _setup_light(hass)
    seen = _events(hass)
    ctx = await _switched_on_ctx(hass, lights, 50)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report_attrs(hass, ctx, brightness=_byte(target_b), color_temp_kelvin=target_k)
    freezer.tick(timedelta(seconds=60))  # long after the command and its ignore window
    await _report_attrs(hass, Context(), brightness=0)
    assert not om.is_overridden("light.a")
    await _report_attrs(hass, Context(), state="off")
    assert not om.is_overridden("light.a")
    assert seen == []


async def test_rm_b41_on_with_brightness_0_inside_the_ignore_window_is_not_manual(
    hass, no_frontend_registration
):
    """A report without HCL's context while the ignore window of the command runs."""
    lights, om, _controller = await _setup_light(hass)
    ctx = await _switched_on_ctx(hass, lights, 50)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report_attrs(hass, ctx, brightness=_byte(target_b), color_temp_kelvin=target_k)
    await _report_attrs(hass, Context(), brightness=0)
    assert not om.is_overridden("light.a")


async def test_rm_b41_dimming_without_hcl_context_is_still_manual(hass, no_frontend_registration, freezer):
    lights, om, _controller = await _setup_light(hass)
    ctx = await _switched_on_ctx(hass, lights, 50)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report_attrs(hass, ctx, brightness=_byte(target_b), color_temp_kelvin=target_k)
    freezer.tick(timedelta(seconds=60))
    user = target_b - 30 if target_b > 40 else target_b + 30
    await _report_attrs(hass, Context(), brightness=_byte(user))
    assert om.is_overridden("light.a")


# ---------------------------------------------------------------- B-04
async def test_b04_kelvin_change_inside_ignore_window_is_detected(hass, berlin, no_frontend_registration):
    async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    sw = switch_entity(hass)
    await sw.async_turn_on()  # sends 100 % / 6000 K and opens the ignore window
    om = core(hass, entry).override_manager
    assert not om.is_overridden("light.a")
    # Light has reached the HCL target ...
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6000, **CT_ATTRS)
    await hass.async_block_till_done()
    # ... and the user sets 2700 K a few seconds later (still inside the window).
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=2700, **CT_ATTRS)
    await hass.async_block_till_done()
    assert om.is_overridden("light.a")


async def test_b04_hcl_transition_inside_window_is_not_an_override(hass, berlin, no_frontend_registration):
    async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await switch_entity(hass).async_turn_on()
    om = core(hass, entry).override_manager
    # Intermediate transition reports moving towards 100 % / 6000 K.
    for b, k in ((170, 5000), (220, 5800), (255, 6000)):
        set_light(hass, "light.a", "on", brightness=b, color_temp_kelvin=k, **CT_ATTRS)
        await hass.async_block_till_done()
    assert not om.is_overridden("light.a")


# ---------------------------------------------------------------- B-23 / Ä-20
async def test_b05_clamped_light_small_change_is_not_a_false_override(hass, berlin, no_frontend_registration):
    async_mock_service(hass, "light", "turn_on")
    attrs = dict(CT_ATTRS, min_color_temp_kelvin=2200, max_color_temp_kelvin=4000)
    set_light(hass, "light.ikea", "on", brightness=100, color_temp_kelvin=4000, **attrs)
    entry = await setup_entry(hass, ["light.ikea"])
    sw = switch_entity(hass)
    await sw.async_turn_on()  # sends 100 %
    set_light(hass, "light.ikea", "on", brightness=255, color_temp_kelvin=4000, **attrs)
    await hass.async_block_till_done()
    berlin.tick(timedelta(seconds=60))  # ignore window over
    set_light(hass, "light.ikea", "on", brightness=253, color_temp_kelvin=4000, **attrs)  # 1 % jitter
    await hass.async_block_till_done()
    assert not core(hass, entry).override_manager.is_overridden("light.ikea")


# ---------------------------------------------------------------- RM-B49 (review 10.10.2026)
async def _dimmed_off_on_with_hcl_context(hass, options=None):
    """Switched on, HCL sends its values, dimmed at the wall (manual control),
    switched off and on again - all within 5 s, so every report carries the
    context of HCL's command."""
    lights, om, controller = await _setup_light(hass, options)
    target, _k = controller.calculate_target_values(dt_util.now())
    start, user = _away(target)
    ctx = await _switched_on_ctx(hass, lights, start)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report(hass, ctx, target_b, target_k)
    await _report(hass, ctx, user)  # dimmed at the wall
    assert om.is_overridden("light.a")
    await _report(hass, ctx, state="off")
    lights.calls.clear()
    await _report(hass, ctx, user, state="on")  # on again before the next update
    return lights, om


async def test_rm_b49_switching_off_with_hcl_context_ends_manual_control(hass, no_frontend_registration):
    lights, om = await _dimmed_off_on_with_hcl_context(hass)
    assert not om.is_overridden("light.a")
    assert lights.for_light("light.a"), "switched on again: HCL sends its values (Fast-HCL)"


async def test_rm_b49_manual_control_kept_without_reset_on_off(hass, no_frontend_registration):
    _lights, om = await _dimmed_off_on_with_hcl_context(hass, {"override_reset_on_off": False})
    assert om.is_overridden("light.a")


# ---------------------------------------------------------------- RM-B50 (review 10.10.2026)
@pytest.mark.parametrize("brightness", [0, None], ids=["brightness_0", "no_brightness"])
async def test_rm_b50_colour_change_without_brightness_is_manual(hass, no_frontend_registration, freezer, brightness):
    """A report without HCL's context, "on" without brightness information but
    with another colour temperature: only the brightness comparison is skipped."""
    _ctx, om = await _after_hcl_command(hass, freezer)
    _b, last_k = om.last_set("light.a")
    user_k = 2000 if last_k > 4000 else 6500
    await _report_attrs(hass, Context(), brightness=brightness, color_temp_kelvin=user_k)
    assert om.is_overridden("light.a")


async def test_rm_b50_no_brightness_and_same_colour_is_no_manual_control(hass, no_frontend_registration, freezer):
    _ctx, om = await _after_hcl_command(hass, freezer)
    _b, last_k = om.last_set("light.a")
    await _report_attrs(hass, Context(), brightness=0, color_temp_kelvin=last_k)
    assert not om.is_overridden("light.a")


async def test_rm_b49_unavailable_with_hcl_context_keeps_manual_control(hass, no_frontend_registration):
    """Unavailable says nothing about the light (RM-B24), also with HCL's context."""
    lights, om, controller = await _setup_light(hass)
    target, _k = controller.calculate_target_values(dt_util.now())
    start, user = _away(target)
    ctx = await _switched_on_ctx(hass, lights, start)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report(hass, ctx, target_b, target_k)
    await _report(hass, ctx, user)  # dimmed at the wall
    assert om.is_overridden("light.a")
    await _report(hass, ctx, state="unavailable")
    assert om.is_overridden("light.a")
