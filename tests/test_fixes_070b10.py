"""0.7.0b10: RM-B24 (manual control and unavailable/unknown lights) and RM-D03 (log message)."""
from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.hcl_lighting import DATA_OVERRIDE_MANAGERS
from custom_components.hcl_lighting.const import UNREACHABLE_GRACE_SECONDS

from .helpers import CT_ATTRS, core, set_light, setup_entry, switch_entity

ON = {"brightness": 128, "color_temp_kelvin": 4000, **CT_ATTRS}  # 50 %, not the HCL value
DIVERGENCE_LOG = "inside the ignore window"


@pytest.fixture(autouse=True)
async def _late_morning(hass: HomeAssistant, freezer):
    """11:00 Europe/Berlin (curve plateau: 100 % / 6500 K)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-01-15 10:00:00+00:00")


async def _manual_light(hass, freezer, options=None):
    """HCL on, light.a under manual control, ignore window of the first command over."""
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", **ON)
    entry = await setup_entry(hass, ["light.a"], options=options)
    await switch_entity(hass).async_turn_on()
    await hass.async_block_till_done()
    om = core(hass, entry)["override_manager"]
    om.set_override("light.a")
    freezer.tick(timedelta(seconds=60))
    calls.clear()
    return calls, entry, om


async def _gap(hass, freezer, states, seconds_each):
    for state in states:
        set_light(hass, "light.a", state, **CT_ATTRS)
        await hass.async_block_till_done()
        freezer.tick(timedelta(seconds=seconds_each))


async def _back_on(hass):
    set_light(hass, "light.a", "on", **ON)
    await hass.async_block_till_done()


# ---------------------------------------------------------------- RM-B24
@pytest.mark.parametrize("states", [["unavailable"], ["unknown"], ["unavailable", "unknown"]])
async def test_rm_b24_short_gap_keeps_manual_control(hass, no_frontend_registration, freezer, states):
    calls, _entry, om = await _manual_light(hass, freezer)
    await _gap(hass, freezer, states, 20)
    assert om.is_overridden("light.a")  # unavailable/unknown is not "switched off"
    await _back_on(hass)
    assert om.is_overridden("light.a")
    assert calls == []  # HCL does not overwrite the user's values


async def test_rm_b24_long_gap_counts_as_switched_off(hass, no_frontend_registration, freezer):
    calls, _entry, om = await _manual_light(hass, freezer)
    # each step shorter than the limit, together longer: the gap counts from the first
    step = UNREACHABLE_GRACE_SECONDS / 2 + 10
    await _gap(hass, freezer, ["unavailable", "unknown"], step)
    assert om.is_overridden("light.a")
    await _back_on(hass)
    assert not om.is_overridden("light.a")
    assert calls, "a lamp back after a long gap gets the HCL values (fast path)"


async def test_rm_b24_long_gap_keeps_manual_control_without_reset_on_off(
    hass, no_frontend_registration, freezer
):
    calls, _entry, om = await _manual_light(hass, freezer, options={"override_reset_on_off": False})
    await _gap(hass, freezer, ["unavailable"], UNREACHABLE_GRACE_SECONDS + 60)
    await _back_on(hass)
    assert om.is_overridden("light.a") and calls == []


async def test_rm_b24_back_as_off_ends_manual_control(hass, no_frontend_registration, freezer):
    _calls, _entry, om = await _manual_light(hass, freezer)
    await _gap(hass, freezer, ["unavailable"], 20)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")


@pytest.mark.parametrize("gap", [None, "unavailable", "unknown"])
async def test_rm_b24_persisted_manual_control_survives_the_restart(
    hass, hass_storage, no_frontend_registration, freezer, gap
):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", **ON)
    entry = await setup_entry(hass, ["light.a"], options={"persist_overrides": True})
    await switch_entity(hass).async_turn_on()
    core(hass, entry)["override_manager"].set_override("light.a")
    await hass.config_entries.async_unload(entry.entry_id)
    hass.bus.async_fire("homeassistant_final_write")
    await hass.async_block_till_done()
    hass.data[DATA_OVERRIDE_MANAGERS].pop(entry.entry_id)  # restart: in-memory state gone
    assert await hass.config_entries.async_setup(entry.entry_id)
    await switch_entity(hass).async_turn_on()  # restored "HCL active" = on
    await hass.async_block_till_done()
    om = core(hass, entry)["override_manager"]
    assert om.is_overridden("light.a")
    freezer.tick(timedelta(seconds=30))
    calls.clear()
    if gap:  # MQTT/Zigbee lights report unavailable/unknown right after the start
        await _gap(hass, freezer, [gap], 40)
    await _back_on(hass)
    assert om.is_overridden("light.a")
    assert calls == []


# ---------------------------------------------------------------- RM-D03
async def _in_ignore_window(hass):
    """HCL just sent its values to light.a (ignore window running)."""
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", **ON)
    entry = await setup_entry(hass, ["light.a"])
    await switch_entity(hass).async_turn_on()
    await hass.async_block_till_done()
    assert calls
    return core(hass, entry)["override_manager"]


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


async def test_rm_d03_change_away_in_the_ignore_window_is_still_detected(
    hass, no_frontend_registration, caplog
):
    om = await _in_ignore_window(hass)
    with caplog.at_level(logging.DEBUG, logger="custom_components.hcl_lighting"):
        set_light(hass, "light.a", "on", **{**ON, "brightness": 26})  # 50 % -> 10 %, away from 100 %
        await hass.async_block_till_done()
    assert f"{DIVERGENCE_LOG} for light.a" in caplog.text
    assert om.is_overridden("light.a")
