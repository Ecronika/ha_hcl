"""0.7.1: RM-B41 (report "on" with brightness 0) and RM-B42 (compatibility
mode: colour temperature without transition)."""
from __future__ import annotations

import asyncio
from datetime import timedelta

from homeassistant.components.light import ColorMode, LightEntity, LightEntityFeature
from homeassistant.core import Context
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockModule,
    MockPlatform,
    mock_integration,
    mock_platform,
)

from custom_components.hcl_lighting.const import EVENT_MANUAL_CONTROL

from .helpers import CT_ATTRS, core, set_light, setup_entry, switch_entity
from .test_fixes_070b3 import SWITCH, Lights, _hcl_on, _settle


def _byte(pct: int) -> int:
    return round(pct * 255 / 100)


async def _report(hass, context, state="on", **attrs):
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


async def _setup(hass, options=None):
    lights = Lights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options)
    await _hcl_on(hass)
    return lights, core(hass, entry)["override_manager"], core(hass, entry)["controller"]


async def _switched_on(hass, lights, start_pct=50, kelvin=2700):
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


# ---------------------------------------------------------------- RM-B41
async def test_rm_b41_on_with_brightness_0_after_switching_on_is_not_manual(hass, no_frontend_registration):
    """KNX: the brightness status 0 arrives just after the switching status
    (with the context of the Fast-HCL command)."""
    lights, om, _controller = await _setup(hass)
    seen = _events(hass)
    ctx = await _switched_on(hass, lights, 31)
    await _report(hass, ctx, brightness=0)
    assert not om.is_overridden("light.a")
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report(hass, ctx, brightness=_byte(target_b), color_temp_kelvin=target_k)
    assert not om.is_overridden("light.a")
    assert seen == []


async def test_rm_b41_switched_on_with_brightness_0_first_is_not_manual(hass, no_frontend_registration):
    """KNX: switching status first ("on" with 0 %), the brightness status (the
    actuator's switch-on value) just after it, before HCL's value arrives."""
    lights, om, controller = await _setup(hass)
    seen = _events(hass)
    target, _k = controller.calculate_target_values(dt_util.now())
    lights.calls.clear()
    set_light(hass, "light.a", "on", brightness=0, color_temp_kelvin=2700, **CT_ATTRS)
    await hass.async_block_till_done()
    sent = lights.for_light("light.a")
    assert sent, "Fast-HCL must send the values"
    ctx = sent[-1].context
    actuator = min(100, target + 30)
    await _report(hass, ctx, brightness=_byte(actuator))
    assert not om.is_overridden("light.a")
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report(hass, ctx, brightness=_byte(target_b), color_temp_kelvin=target_k)
    assert not om.is_overridden("light.a")
    assert seen == []


async def test_rm_b41_report_without_brightness_after_switching_on_is_not_manual(hass, no_frontend_registration):
    lights, om, _controller = await _setup(hass)
    ctx = await _switched_on(hass, lights, 31)
    await _report(hass, ctx, brightness=None)
    assert not om.is_overridden("light.a")


async def test_rm_b41_colour_is_still_checked_with_brightness_0(hass, no_frontend_registration):
    """Brightness 0 carries no brightness information; the colour still counts."""
    lights, om, _controller = await _setup(hass)
    ctx = await _switched_on(hass, lights, 31)
    _b, target_k = om.tracking_snapshot("light.a")[0]
    user_k = 2000 if target_k > 4000 else 6500
    await _report(hass, ctx, brightness=0, color_temp_kelvin=user_k)
    assert om.is_overridden("light.a")


async def test_rm_b41_dimming_after_brightness_0_is_still_manual(hass, no_frontend_registration):
    lights, om, controller = await _setup(hass)
    target, _k = controller.calculate_target_values(dt_util.now())
    start, user = (100, target - 30) if target > 60 else (1, target + 30)
    ctx = await _switched_on(hass, lights, start)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report(hass, ctx, brightness=0)
    await _report(hass, ctx, brightness=_byte(target_b), color_temp_kelvin=target_k)
    await _report(hass, ctx, brightness=_byte(user))
    assert om.is_overridden("light.a")


async def test_rm_b41_on_with_brightness_0_when_switching_off_is_not_manual(
    hass, no_frontend_registration, freezer
):
    """Switching off at the device (no HCL context): "on" with 0 %, then "off"."""
    lights, om, _controller = await _setup(hass)
    seen = _events(hass)
    ctx = await _switched_on(hass, lights, 50)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report(hass, ctx, brightness=_byte(target_b), color_temp_kelvin=target_k)
    freezer.tick(timedelta(seconds=60))  # long after the command and its ignore window
    await _report(hass, Context(), brightness=0)
    assert not om.is_overridden("light.a")
    await _report(hass, Context(), state="off")
    assert not om.is_overridden("light.a")
    assert seen == []


async def test_rm_b41_on_with_brightness_0_inside_the_ignore_window_is_not_manual(
    hass, no_frontend_registration
):
    """A report without HCL's context while the ignore window of the command runs."""
    lights, om, _controller = await _setup(hass)
    ctx = await _switched_on(hass, lights, 50)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report(hass, ctx, brightness=_byte(target_b), color_temp_kelvin=target_k)
    await _report(hass, Context(), brightness=0)
    assert not om.is_overridden("light.a")


async def test_rm_b41_dimming_without_hcl_context_is_still_manual(hass, no_frontend_registration, freezer):
    lights, om, _controller = await _setup(hass)
    ctx = await _switched_on(hass, lights, 50)
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    await _report(hass, ctx, brightness=_byte(target_b), color_temp_kelvin=target_k)
    freezer.tick(timedelta(seconds=60))
    user = target_b - 30 if target_b > 40 else target_b + 30
    await _report(hass, Context(), brightness=_byte(user))
    assert om.is_overridden("light.a")


# ---------------------------------------------------------------- RM-B42
async def _smart_update(hass, lights, brightness_pct, kelvin):
    """Light at the given values; one update cycle in the compatibility mode."""
    set_light(hass, "light.a", "on", brightness=_byte(brightness_pct), color_temp_kelvin=kelvin, **CT_ATTRS)
    await hass.async_block_till_done()
    lights.calls.clear()
    await switch_entity(hass)._update_hcl()
    await hass.async_block_till_done()
    await _settle()
    return [dict(c.data) for c in lights.for_light("light.a")]


SMART = {"smart_transition": True, "transition": 20, "update_interval": 27}


async def test_rm_b42_colour_temperature_is_sent_with_transition_0(hass, no_frontend_registration, freezer):
    lights, om, controller = await _setup(hass, SMART)
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
    lights, om, controller = await _setup(hass, SMART)
    target_b, target_k = controller.calculate_target_values(dt_util.now())
    freezer.tick(timedelta(seconds=60))
    # colour temperature changes more than the brightness: both snap
    far_k = 2000 if target_k > 4250 else 6500
    sent = await _smart_update(hass, lights, target_b, far_k)
    colour = [d for d in sent if "color_temp_kelvin" in d]
    assert colour and all(d.get("transition") == 0 for d in colour), sent


async def test_rm_b42_fallback_is_sent_with_transition_0(hass, no_frontend_registration, freezer):
    lights, om, controller = await _setup(hass, SMART)
    target_b, target_k = controller.calculate_target_values(dt_util.now())
    freezer.tick(timedelta(seconds=60))
    lights.fail.add("light.a")
    far_b = 100 if target_b < 50 else 1
    sent = await _smart_update(hass, lights, far_b, target_k + 300 if target_k < 6000 else target_k - 300)
    fallback = sent[-1]
    assert "brightness_pct" in fallback and "color_temp_kelvin" in fallback, sent
    assert fallback.get("transition") == 0, sent


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
    target_b, target_k = core(hass, entry)["controller"].calculate_target_values(dt_util.now())
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
