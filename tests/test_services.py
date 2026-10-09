"""Actions apply, set_manual_control, set_scenario, get_curve."""
from __future__ import annotations

import asyncio
import json
import pytest

from datetime import timedelta
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pathlib import Path
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

from custom_components.hcl_lighting.const import COMMAND_TIMEOUT_SECONDS, DOMAIN
from custom_components.hcl_lighting.logic import light_controller

from .support.entries import CT_ATTRS, SELECT, SWITCH, calls_for, core, hcl_on, select_scenario, set_light, settle, setup_entry, setup_two_dim_lights, timer_cycle
from .support.lights import FakeLights


COMPONENT = Path(__file__).parent.parent / "custom_components" / "hcl_lighting"


async def _light_on(hass, options=None):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options=options)
    await hcl_on(hass)
    return calls, entry


async def _apply(hass, **data):
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, **data}, blocking=True)


class _OldServiceCall:
    """ServiceCall up to Home Assistant 2024.12 (no hass parameter)."""

    def __init__(self, domain, service, data=None, context=None, return_response=False):
        self.domain, self.service, self.data = domain, service, data or {}


class _NewServiceCall:
    """ServiceCall since Home Assistant 2025.1 (hass first)."""

    def __init__(self, hass, domain, service, data=None, context=None, return_response=False):
        self.hass, self.domain, self.service, self.data = hass, domain, service, data or {}


# ------------------------------------------------------------------ Ä-15 / Ä-16
async def test_a15_service_registered_once_and_translated(hass, no_frontend_registration):
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    assert hass.services.has_service(DOMAIN, "update_curve")
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.services.has_service(DOMAIN, "update_curve")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "update_curve", {"entity_id": "sensor.hcl_curve_data", "mode": "revert"}, blocking=True
        )
    for name in ("en.json", "de.json"):
        data = json.loads((COMPONENT / "translations" / name).read_text(encoding="utf-8"))
        assert data["services"]["update_curve"]["name"]


# ---------------------------------------------------------------- F-02 services
@pytest.mark.usefixtures("evening")
async def test_f02_apply_sends_now_and_never_switches_on(hass, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    set_light(hass, "light.b", "off", **CT_ATTRS)
    await setup_entry(hass, ["light.a", "light.b"])
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SELECT, "transition": 1}, blocking=True)
    await hass.async_block_till_done()
    assert calls_for(calls, "light.a")[-1].data["transition"] == 1
    assert calls_for(calls, "light.b") == []


@pytest.mark.usefixtures("evening")
async def test_b58_long_apply_transition_is_not_cut_short(hass, no_frontend_registration, freezer):
    """0.7.0b2 (B-58): the next update cycles leave a light alone during a long apply transition."""
    calls, entry = await _light_on(hass)
    om = core(hass, entry).override_manager
    calls.clear()
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 120}, blocking=True)
    await hass.async_block_till_done()
    assert calls_for(calls, "light.a")[-1].data["transition"] == 120
    calls.clear()
    target_b, target_k = om.tracking_snapshot("light.a")[0]
    # from 100 % / 6500 K towards the target of the curve
    steps = [
        (30 * i, round((100 + (target_b - 100) * i / 4) * 255 / 100), round(6500 + (target_k - 6500) * i / 4))
        for i in (1, 2, 3)
    ]
    for seconds, brightness, kelvin in steps:
        freezer.tick(timedelta(seconds=30))
        # intermediate values reported by the light during the transition
        set_light(hass, "light.a", "on", brightness=brightness, color_temp_kelvin=kelvin, **CT_ATTRS)
        await hass.async_block_till_done()
        await timer_cycle(hass)
        await hass.async_block_till_done()
        assert calls_for(calls, "light.a") == [], seconds
    assert not om.is_overridden("light.a")
    # after the transition the normal adaptation resumes
    freezer.tick(timedelta(seconds=35))
    await timer_cycle(hass)
    await hass.async_block_till_done()
    assert calls_for(calls, "light.a")[-1].data["transition"] == 20


@pytest.mark.usefixtures("evening")
async def test_b58_short_apply_transition_sets_no_protection(hass, no_frontend_registration):
    calls, entry = await _light_on(hass)
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 5}, blocking=True)
    assert not core(hass, entry).override_manager.is_reengaging("light.a")


@pytest.mark.usefixtures("evening")
async def test_b58_scenario_change_ends_the_apply_protection(hass, no_frontend_registration):
    calls, entry = await _light_on(hass)
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 120}, blocking=True)
    assert core(hass, entry).override_manager.is_reengaging("light.a")
    calls.clear()
    await select_scenario(hass, "focus")
    assert calls_for(calls, "light.a")


@pytest.mark.usefixtures("evening")
async def test_f02_apply_skips_or_releases_manual_control(hass, no_frontend_registration):
    calls, entry = await _light_on(hass)
    om = core(hass, entry).override_manager
    om.set_override("light.a")
    calls.clear()
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH}, blocking=True)
    assert calls_for(calls, "light.a") == []
    await hass.services.async_call(
        DOMAIN, "apply", {"entity_id": SWITCH, "release_manual_control": True}, blocking=True
    )
    await hass.async_block_till_done()
    assert calls_for(calls, "light.a") and not om.is_overridden("light.a")


@pytest.mark.usefixtures("evening")
async def test_f02_apply_rejects_foreign_lights_and_guest_mode(hass, no_frontend_registration):
    from homeassistant.exceptions import ServiceValidationError

    await _light_on(hass)
    # ServiceNotFound is a ServiceValidationError too: check the messages
    with pytest.raises(ServiceValidationError, match="Not controlled by this HCL instance: light.other"):
        await hass.services.async_call(
            DOMAIN, "apply", {"entity_id": SWITCH, "lights": ["light.other"]}, blocking=True
        )
    await select_scenario(hass, "guest")
    with pytest.raises(ServiceValidationError, match="Guest mode"):
        await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH}, blocking=True)
    with pytest.raises(ServiceValidationError, match="is not an HCL Lighting entity"):
        await hass.services.async_call(DOMAIN, "apply", {"entity_id": "light.a"}, blocking=True)


@pytest.mark.usefixtures("evening")
async def test_f02_set_manual_control(hass, no_frontend_registration):
    calls, entry = await _light_on(hass)
    om = core(hass, entry).override_manager
    await hass.services.async_call(
        DOMAIN, "set_manual_control", {"entity_id": SWITCH, "lights": ["light.a"]}, blocking=True
    )
    assert om.is_overridden("light.a")
    assert hass.states.get(SWITCH).attributes["manual_control"] == ["light.a"]
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    calls.clear()
    await hass.services.async_call(
        DOMAIN, "set_manual_control", {"entity_id": SWITCH, "manual_control": False}, blocking=True
    )
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")
    assert calls_for(calls, "light.a")  # follows HCL again right away


@pytest.mark.usefixtures("evening")
async def test_f02_set_scenario_with_duration(hass, no_frontend_registration, freezer):
    await _light_on(hass)
    await hass.services.async_call(
        DOMAIN, "set_scenario", {"entity_id": SWITCH, "scenario": "focus", "duration": 30}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "focus"
    assert hass.states.get(SELECT).attributes["until"] is not None
    later = dt_util.utcnow() + timedelta(minutes=31)
    freezer.move_to(later)
    async_fire_time_changed(hass, later)
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "auto"


@pytest.mark.usefixtures("evening")
async def test_f02_get_curve_returns_points(hass, no_frontend_registration):
    await setup_entry(hass, ["light.a"])
    result = await hass.services.async_call(
        DOMAIN, "get_curve", {"entity_id": SELECT}, blocking=True, return_response=True
    )
    assert len(result["points"]) == 9 and result["saved_points"] is None
    assert "midday_time" not in result  # RM-R07
    assert (result["wake_time"], result["sleep_time"], result["preview_active"]) == ("07:00", "22:00", False)


# ---------------------------------------------------------------- RM-B16 (review RM-B15)
async def test_rm_b16_apply_reports_failed_lights(hass, no_frontend_registration):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    set_light(hass, "light.b", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.a", "light.b"])
    await hcl_on(hass)
    lights.fail = {"light.a", "light.b"}
    with pytest.raises(HomeAssistantError, match="light.a, light.b"):
        await _apply(hass)
    lights.fail = {"light.b"}  # partial failure is reported too
    with pytest.raises(HomeAssistantError, match="failed for light.b:"):
        await _apply(hass)
    assert "light.a" in lights.applied
    lights.fail = set()
    await _apply(hass)  # success: no error


# ---------------------------------------------------------------- RM-B19
def test_rm_b19_service_call_keeps_the_target_with_both_signatures(monkeypatch):
    target = {"area_id": ["living"], "entity_id": ["light.a"]}
    for cls in (_OldServiceCall, _NewServiceCall):
        # imported at module level since 0.7.0b12 (RM-T16)
        monkeypatch.setattr(light_controller, "ServiceCall", cls)
        call = light_controller._service_call(object(), target)
        assert isinstance(call, cls)
        assert (call.domain, call.service, call.data) == ("light", "turn_on", target), cls.__name__


# ---------------------------------------------------------------- RM-B23
async def test_rm_b23_apply_reports_a_light_without_answer(hass, no_frontend_registration, freezer):
    lights, entry = await setup_two_dim_lights(hass)
    lights.hang["light.a"] = asyncio.Event()
    # the lights still report other values (the mock does not change them)
    call = hass.async_create_task(
        hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 0}, blocking=True)
    )
    await settle()
    assert lights.for_light("light.a")
    assert not call.done()
    freezer.tick(timedelta(seconds=COMMAND_TIMEOUT_SECONDS + 1))
    await settle()
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
