"""0.7.0b13: RM-B33 (a change on the device within 5 s after an HCL command
carries the context of that command)."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.core import Context
from homeassistant.util import dt as dt_util

from .helpers import CT_ATTRS, core, set_light, setup_entry, switch_entity
from .test_fixes_070b3 import Lights, _hcl_on, _settle


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
    lights = Lights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
    om = core(hass, entry)["override_manager"]
    controller = core(hass, entry)["controller"]
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
    await switch_entity(hass)._update_hcl()
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
    await _settle()
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
    await switch_entity(hass)._update_hcl()
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
    await switch_entity(hass)._update_hcl()
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
    await switch_entity(hass)._update_hcl()  # still inside the ignore window
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
    await switch_entity(hass)._update_hcl()
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
    lights = Lights(hass)
    xy = {"supported_color_modes": ["xy"], "color_mode": "xy"}
    set_light(hass, "light.a", "off", **xy)
    entry = await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
    om = core(hass, entry)["override_manager"]
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
