"""Daylight compensation (RM-E02) and environmental controller (RM-E01) in a
Home Assistant instance: options, cycles, sensors, persistence, conflicts."""
from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hcl_lighting.const import DOMAIN
from custom_components.hcl_lighting.logic.daylight_compensation import DAYLIGHT_KEY, read_lux
from custom_components.hcl_lighting.sensor import HCLSetpointSensor

from .support.daylight import LUX_ATTRS, LUX_SENSOR, config, daylight_options
from .support.entries import CT_ATTRS, SWITCH, core, hcl_on, select_scenario, set_light, setup_entry, switch_entity, timer_cycle
from .support.lights import FakeLights

TARGET_B = "sensor.hcl_target_brightness"
TARGET_K = "sensor.hcl_target_colour_temperature"
ON = {"brightness": 255, "color_temp_kelvin": 6000, **CT_ATTRS}


@pytest.fixture
async def noon(hass: HomeAssistant, freezer):
    """12:00 Europe/Berlin (default curve: 100 % / 6000 K)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-01-15 11:00:00+00:00")
    return freezer


def _lux(hass, value) -> None:
    hass.states.async_set(LUX_SENSOR, str(value), LUX_ATTRS, force_update=True)


async def _daylight(hass, lux=2000, options=None, lights=("light.a",)):
    fake = FakeLights(hass)
    _lux(hass, lux)
    for eid in lights:
        set_light(hass, eid, "on", **ON)
    entry = await setup_entry(hass, list(lights), options={**daylight_options(), **(options or {})})
    await hcl_on(hass)
    fake.calls.clear()
    return fake, entry


async def _cycles(hass, freezer, n=1, seconds=27):
    for _ in range(n):
        freezer.tick(timedelta(seconds=seconds))
        await timer_cycle(hass)
        await hass.async_block_till_done()


def _sent_brightness(fake, eid="light.a"):
    calls = [c for c in fake.for_light(eid) if "brightness_pct" in c.data]
    return calls[-1].data["brightness_pct"] if calls else None


# ---------------------------------------------------------------- disabled parity
async def test_rm_e01_without_daylight_nothing_changes(hass, noon, no_frontend_registration):
    """EC-T01: no feature: effective = base, no environment attributes."""
    fake = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hcl_on(hass)
    ctl = core(hass, entry).controller
    assert not ctl.environment.enabled
    assert ctl.calculate_target_values(dt_util.now()) == ctl.calculate_base_values(dt_util.now())
    assert "base_value" not in hass.states.get(TARGET_B).attributes
    assert _sent_brightness(fake) == 100


# ---------------------------------------------------------------- control in HA
async def test_rm_e02_bright_room_dims_the_lights(hass, noon, no_frontend_registration):
    fake, entry = await _daylight(hass, lux=3000)
    await _cycles(hass, noon, 20)
    sent = _sent_brightness(fake)
    assert sent is not None and sent < 100
    state = hass.states.get(TARGET_B)
    assert float(state.state) == sent  # EC-T14: sensor and command the same value
    assert state.attributes["base_value"] == 100
    assert state.attributes["environment_status"] == "active"
    assert state.attributes["environment_reason"] == "daylight_reducing"
    assert state.attributes["target_lux"] == 500
    assert hass.states.get(TARGET_K).attributes["base_value"] == float(hass.states.get(TARGET_K).state)


async def test_rm_e01_readers_do_not_advance_the_loop(hass, noon, no_frontend_registration):
    """EC-T02/E01-1: 100 sensor refreshes, 10 diagnostics and 5 apply between
    two cycles change no state of the loop."""
    from custom_components.hcl_lighting.diagnostics import async_get_config_entry_diagnostics

    fake, entry = await _daylight(hass, lux=3000)
    await _cycles(hass, noon, 3)
    env = core(hass, entry).environment
    state = env.state(DAYLIGHT_KEY)
    for _ in range(100):
        noon.tick(timedelta(seconds=0.1))
        async_dispatcher_send(hass, f"{DOMAIN}_{entry.entry_id}_environment")
    for _ in range(10):
        await async_get_config_entry_diagnostics(hass, entry)
    for _ in range(5):
        await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH}, blocking=True)
    await hass.async_block_till_done()
    assert env.state(DAYLIGHT_KEY) is state


async def test_rm_e01_both_target_sensors_show_one_snapshot(hass, noon, no_frontend_registration):
    """EC-T03."""
    fake, entry = await _daylight(hass, lux=3000)
    await _cycles(hass, noon, 5)
    result = core(hass, entry).controller.target_result(dt_util.now())
    b, k = hass.states.get(TARGET_B), hass.states.get(TARGET_K)
    assert (float(b.state), float(k.state)) == (result.effective.brightness, result.effective.kelvin)
    assert b.attributes["environment_status"] == k.attributes["environment_status"] == result.status


def test_rm_e01_environment_attributes_are_not_recorded():
    """EC-T09/E01-8."""
    assert {
        "base_value", "environment_status", "environment_reason", "reason_codes",
        "measured_lux", "filtered_lux", "target_lux", "cap_pct", "sensor_age",
    } <= HCLSetpointSensor._unrecorded_attributes


async def test_rm_e02_single_invalid_sample_sends_nothing(hass, noon, no_frontend_registration):
    """DL-T19: one unknown value: no light command, no jump to the base."""
    fake, entry = await _daylight(hass, lux=3000)
    await _cycles(hass, noon, 20)
    _lux(hass, 520)  # within the dead band: no change
    await _cycles(hass, noon, 3)
    # the light has the values (the test double does not change its state)
    b, k = (float(hass.states.get(e).state) for e in (TARGET_B, TARGET_K))
    set_light(hass, "light.a", "on", **{**ON, "brightness": round(b * 255 / 100), "color_temp_kelvin": int(k)})
    await hass.async_block_till_done()
    await _cycles(hass, noon)
    fake.calls.clear()
    before = float(hass.states.get(TARGET_B).state)
    hass.states.async_set(LUX_SENSOR, "unknown", LUX_ATTRS)
    await _cycles(hass, noon)
    _lux(hass, 520)
    await _cycles(hass, noon)
    assert fake.calls == []
    assert float(hass.states.get(TARGET_B).state) == before


async def test_rm_e02_hold_when_all_lights_are_manual(hass, noon, no_frontend_registration):
    """DL-PRD-09: manual control freezes the cap."""
    fake, entry = await _daylight(hass, lux=3000)
    await _cycles(hass, noon, 5)
    env = core(hass, entry).environment
    core(hass, entry).override_manager.set_override("light.a")
    cap = env.state(DAYLIGHT_KEY).cap_pct
    await _cycles(hass, noon, 20)
    assert env.state(DAYLIGHT_KEY).cap_pct == cap
    assert hass.states.get(TARGET_B).attributes["environment_status"] == "hold"


async def test_rm_e02_adapt_off_freezes_the_target_sensor(hass, noon, no_frontend_registration):
    """EC-T07/E02-15: target sensor shows the frozen effective value."""
    fake, entry = await _daylight(hass, lux=3000)
    await _cycles(hass, noon, 10)
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.hcl_adapt_brightness"}, blocking=True)
    await _cycles(hass, noon)
    frozen = hass.states.get(TARGET_B).state
    await _cycles(hass, noon, 20)
    assert hass.states.get(TARGET_B).state == frozen
    assert hass.states.get(TARGET_B).attributes["environment_reason"] == "daylight_hold_adapt_off"


async def test_rm_e02_scenario_bypasses_and_returns(hass, noon, no_frontend_registration):
    """DL-PRD-02: only in Auto; the scenario value is sent unchanged."""
    fake, entry = await _daylight(hass, lux=3000)
    await _cycles(hass, noon, 20)
    dimmed = _sent_brightness(fake)
    await select_scenario(hass, "focus")
    assert _sent_brightness(fake) == 100
    assert hass.states.get(TARGET_B).attributes["environment_status"] == "bypassed"
    await select_scenario(hass, "auto")
    assert abs(_sent_brightness(fake) - dimmed) <= 6  # the frozen cap is used again


async def test_rm_e02_hcl_off_no_step(hass, noon, no_frontend_registration):
    """EC-T16: no step while HCL is off; afterwards no jump of the cap."""
    fake, entry = await _daylight(hass, lux=3000)
    await _cycles(hass, noon, 5)
    env = core(hass, entry).environment
    await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    result = env.last_result
    await _cycles(hass, noon, 10, seconds=600)
    assert env.last_result is result
    cap = env.state(DAYLIGHT_KEY).cap_pct
    await hcl_on(hass)
    assert cap - env.state(DAYLIGHT_KEY).cap_pct <= 11 + 1e-9


async def test_rm_e02_light_switched_on_starts_dimmed(hass, noon, no_frontend_registration):
    """E02-5/E01-5: Fast-HCL uses the effective value of the last cycle."""
    fake, entry = await _daylight(hass, lux=3000, lights=("light.a", "light.b"))
    await _cycles(hass, noon, 20)
    effective = float(hass.states.get(TARGET_B).state)
    assert effective < 100
    set_light(hass, "light.b", "off", **CT_ATTRS)
    await hass.async_block_till_done()
    fake.calls.clear()
    set_light(hass, "light.b", "on", **ON)
    await hass.async_block_till_done()
    assert _sent_brightness(fake, "light.b") == effective


async def test_rm_e02_only_auto_values_seed_the_cap(hass, noon, no_frontend_registration):
    """DL-T24/DL-PRD-23: values of a scenario or apply are no seed."""
    fake, entry = await _daylight(hass, lux=3000)
    await _cycles(hass, noon, 3)
    sw = switch_entity(hass)
    om = core(hass, entry).override_manager
    assert om.last_source("light.a") == "auto"
    assert sw._cycle_lights()["seed_brightness"] is not None
    await select_scenario(hass, "focus")
    assert om.last_source("light.a") == "scenario"
    assert sw._cycle_lights()["seed_brightness"] is None
    await select_scenario(hass, "auto")
    set_light(hass, "light.a", "on", **{**ON, "brightness": 30})
    await hass.services.async_call(
        DOMAIN, "apply", {"entity_id": SWITCH, "release_manual_control": True}, blocking=True
    )
    assert om.last_source("light.a") == "apply"
    assert sw._cycle_lights()["seed_brightness"] is None


# ---------------------------------------------------------------- persistence
async def test_rm_e02_reload_resumes_the_cap(hass, noon, no_frontend_registration):
    """DL-PRD-13/D5: a reload (options saved) does not jump to the base."""
    fake, entry = await _daylight(hass, lux=3000)
    await _cycles(hass, noon, 20)
    dimmed = _sent_brightness(fake)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    fake.calls.clear()
    await _cycles(hass, noon)
    sent = _sent_brightness(fake)
    assert sent is None or abs(sent - dimmed) <= 6
    result = core(hass, entry).environment.last_result
    assert result.modifier(DAYLIGHT_KEY).details.get("start") == "daylight_resume"


async def test_rm_e02_early_turn_on_after_start_uses_the_persisted_cap(hass, hass_storage, noon, no_frontend_registration):
    """DL-T21: before the first cycle a light switched on gets the persisted cap."""
    fake = FakeLights(hass)
    _lux(hass, 3000)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    hass_storage[f"{DOMAIN}.daylight.dl_entry"] = {
        "version": 1, "minor_version": 1, "key": f"{DOMAIN}.daylight.dl_entry",
        "data": {"cap_pct": 30.0, "timestamp": (dt_util.utcnow() - timedelta(minutes=10)).isoformat()},
    }
    entry = MockConfigEntry(
        domain=DOMAIN, title="HCL", entry_id="dl_entry", minor_version=2,
        options={"target": {"entity_id": ["light.a"]}, **daylight_options()},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    sw = switch_entity(hass)
    sw.controller.hcl_active = True  # switched on, before its first cycle
    sw._is_on = True
    await sw._re_evaluate_targets_and_listeners()
    set_light(hass, "light.a", "on", **ON)
    await hass.async_block_till_done()
    assert _sent_brightness(fake) == 30


async def test_rm_e02_writes_are_coalesced(hass, noon, no_frontend_registration):
    """DL-T23: a stable cap does not write in every cycle."""
    fake, entry = await _daylight(hass, lux=520)  # dead band: the cap stays
    await _cycles(hass, noon, 100)
    store = core(hass, entry).controller.daylight_store
    assert store.writes <= 100 * 27 / 300 + 2


async def test_rm_e02_removed_entry_removes_the_store(hass, hass_storage, noon, no_frontend_registration):
    fake, entry = await _daylight(hass, lux=3000)
    await _cycles(hass, noon, 5)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    key = f"{DOMAIN}.daylight.{entry.entry_id}"
    assert key in hass_storage  # written when unloaded
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage


# ---------------------------------------------------------------- sensor reading
@pytest.mark.parametrize(
    "value,problem",
    [("812.5", None), ("unavailable", "unavailable"), ("unknown", "unknown"), ("abc", "invalid"),
     ("nan", "invalid"), ("inf", "invalid"), ("-3", "invalid")],
)
async def test_rm_e02_sensor_values(hass, value, problem):
    """DL §9/DL-PRD-12: finite numbers >= 0 only; no conversions."""
    hass.states.async_set(LUX_SENSOR, value, LUX_ATTRS)
    reading = read_lux(hass, config(), dt_util.utcnow())
    assert reading.problem == problem
    if problem is None:
        assert reading.lux == 812.5


async def test_rm_e02_stale_sensor_and_stale_check_off(hass, freezer):
    """DL-T11/E02-19: stale by last_reported; 0 switches the check off."""
    hass.states.async_set(LUX_SENSOR, "300", LUX_ATTRS)
    freezer.tick(timedelta(minutes=61))
    assert read_lux(hass, config(stale_after_s=3600), dt_util.utcnow()).problem == "stale"
    assert read_lux(hass, config(stale_after_s=0), dt_util.utcnow()).problem is None
    hass.states.async_set(LUX_SENSOR, "300", LUX_ATTRS, force_update=True)  # same value reported again
    assert read_lux(hass, config(stale_after_s=3600), dt_util.utcnow()).problem is None


async def test_rm_e02_missing_sensor_falls_back(hass, noon, no_frontend_registration):
    fake, entry = await _daylight(hass, lux=3000)
    hass.states.async_remove(LUX_SENSOR)
    await _cycles(hass, noon, 2)
    assert hass.states.get(TARGET_B).attributes["environment_reason"] == "daylight_sensor_missing"


# ---------------------------------------------------------------- conflicts
async def test_rm_e02_shared_lux_sensor_raises_a_repair_issue(hass, noon, no_frontend_registration):
    """EC-T10/DL-T17."""
    FakeLights(hass)
    _lux(hass, 600)
    issue_id = f"daylight_shared_sensor_{LUX_SENSOR}"
    for title, light in (("A", "light.a"), ("B", "light.b")):
        set_light(hass, light, "on", **ON)
        entry = MockConfigEntry(
            domain=DOMAIN, title=title, minor_version=2,
            options={"target": {"entity_id": [light]}, **daylight_options()},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    for switch in ("switch.a_hcl_active", "switch.b_hcl_active"):
        await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None and issue.translation_placeholders["instances"] == "A, B"
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.b_hcl_active"}, blocking=True)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


# ---------------------------------------------------------------- options and diagnostics
async def test_rm_e02_options_step(hass, no_frontend_registration):
    """E02-7: own step after the scenarios, sensor and target required when on,
    advanced parameters in a collapsed section; a cleared field is removed."""
    set_light(hass, "light.a", "off", **CT_ATTRS)
    _lux(hass, 100)
    entry = await setup_entry(hass, ["light.a"], options={"daylight_deadband_lux": 40})
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    base = {"target": {"entity_id": ["light.a"]}, "wake_time": "07:00:00",
            "sleep_time": "22:00:00", "smart_transition": False, "min_brightness": 3, "max_brightness": 100}
    result = await hass.config_entries.options.async_configure(flow["flow_id"], base)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"override_timeout": 240, "override_reset_on_off": True, "persist_overrides": False,
                          "respect_turn_on_values": False, "advanced": {"update_interval": 27, "transition": 20}},
    )
    result = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    assert result["step_id"] == "daylight"
    schema = {str(k): v for k, v in result["data_schema"].schema.items()}
    assert schema["daylight_advanced"].options["collapsed"] is True
    assert schema["daylight_sensor"].config["device_class"] in ("illuminance", ["illuminance"])
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"daylight_enabled": True, "daylight_advanced": {}}
    )
    assert result["errors"] == {
        "daylight_sensor": "daylight_sensor_required", "daylight_target_lux": "daylight_target_required",
    }
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {"daylight_enabled": True, "daylight_sensor": LUX_SENSOR, "daylight_target_lux": 400, "daylight_advanced": {}},
    )
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert entry.options["daylight_sensor"] == LUX_SENSOR and entry.options["daylight_target_lux"] == 400
    assert "daylight_deadband_lux" not in entry.options  # cleared
    assert core(hass, entry).environment.enabled


async def test_rm_e02_diagnostics_show_one_snapshot_without_ids(hass, noon, no_frontend_registration):
    """G6: base -> modifiers -> effective; the sensor ID is a pseudonym."""
    from custom_components.hcl_lighting.diagnostics import async_get_config_entry_diagnostics

    fake, entry = await _daylight(hass, lux=3000)
    await _cycles(hass, noon, 5)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    env = diag["environment"]
    assert env["now"]["base"]["brightness"] == 100
    assert env["now"]["modifiers"][0]["key"] == "daylight"
    assert env["last_cycle"]["status"] == "active"
    assert diag["options"]["daylight_sensor"].startswith("sensor.redacted_")
    assert LUX_SENSOR not in str(diag)

