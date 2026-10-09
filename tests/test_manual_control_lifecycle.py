"""Manual control over time: return to HCL, switching off, unavailable lights, events."""
from __future__ import annotations

import pytest

from datetime import timedelta
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.hcl_lighting import DATA_OVERRIDE_MANAGERS
from custom_components.hcl_lighting.const import REENGAGE_TRANSITION_SECONDS, UNREACHABLE_GRACE_SECONDS

from .support.entries import CT_ATTRS, SWITCH, calls_for, core, hcl_on, select_scenario, set_light, setup_entry, switch_entity, timer_cycle
from .support.lights import FakeLights


REENGAGE_DURATION = REENGAGE_TRANSITION_SECONDS


async def _expired_override(hass):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    sw = switch_entity(hass)
    om = core(hass, entry).override_manager
    await hcl_on(hass)
    om.set_override("light.a", since=dt_util.now() - timedelta(hours=5))
    calls.clear()
    await timer_cycle(hass)
    await hass.async_block_till_done()
    return calls, sw, om


@pytest.fixture
async def noon(hass: HomeAssistant, freezer):
    """12:00 Europe/Berlin (default curve: 100 % / 6000 K)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-01-15 11:00:00+00:00")
    return freezer


async def _light_on(hass, options=None):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options=options)
    await hcl_on(hass)
    return calls, entry


ON = {"brightness": 128, "color_temp_kelvin": 4000, **CT_ATTRS}  # 50 %, not the HCL value


@pytest.fixture
async def _late_morning(hass: HomeAssistant, freezer):
    """11:00 Europe/Berlin (default curve: 100 %, morning plateau)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-01-15 10:00:00+00:00")


async def _manual_light(hass, freezer, options=None):
    """HCL on, light.a under manual control, ignore window of the first command over."""
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", **ON)
    entry = await setup_entry(hass, ["light.a"], options=options)
    await switch_entity(hass).async_turn_on()
    await hass.async_block_till_done()
    om = core(hass, entry).override_manager
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


async def _expire_override_of_light_at(hass, freezer, hour, minute):
    """Light on at 100 %/6000 K, override expired; run one update cycle at hh:mm."""
    freezer.move_to(dt_util.now().replace(hour=hour, minute=minute, second=0, microsecond=0))
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    sw = switch_entity(hass)
    om = core(hass, entry).override_manager
    await sw.async_turn_on()
    await hass.async_block_till_done()
    om.set_override("light.a", since=dt_util.now() - timedelta(hours=5))
    calls.clear()
    await timer_cycle(hass)
    await hass.async_block_till_done()
    return calls, om


# ---------------------------------------------------------------- B-32
@pytest.mark.usefixtures("evening")
async def test_b32_reengage_sends_only_the_smooth_transition(hass, no_frontend_registration):
    calls, _sw, om = await _expired_override(hass)
    sent = calls_for(calls, "light.a")
    assert [c.data.get("transition") for c in sent] == [REENGAGE_DURATION]
    assert not om.is_overridden("light.a")


@pytest.mark.usefixtures("evening")
async def test_b32_following_cycles_leave_the_reengaging_light_alone(hass, no_frontend_registration, freezer):
    calls, sw, _om = await _expired_override(hass)
    calls.clear()
    for _ in range(3):  # three normal cycles within the smooth transition
        freezer.tick(timedelta(seconds=30))
        await timer_cycle(hass)
        await hass.async_block_till_done()
    assert calls_for(calls, "light.a") == []


@pytest.mark.usefixtures("evening")
async def test_b32_normal_updates_resume_after_the_transition(hass, no_frontend_registration, freezer):
    calls, sw, _om = await _expired_override(hass)
    calls.clear()
    freezer.tick(timedelta(seconds=REENGAGE_DURATION + 10))
    await timer_cycle(hass)
    await hass.async_block_till_done()
    sent = calls_for(calls, "light.a")
    assert sent and sent[-1].data.get("transition") != REENGAGE_DURATION


@pytest.mark.usefixtures("evening")
async def test_b32_scenario_change_ends_the_smooth_return(hass, no_frontend_registration):
    calls, _sw, _om = await _expired_override(hass)
    calls.clear()
    await select_scenario(hass, "focus")
    sent = calls_for(calls, "light.a")
    assert sent, "a scenario change must reach a light that is returning to HCL"


# ------------------------------------------------------------------ Ä-06
async def test_a06_timeout_option_and_never(hass, noon, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"override_timeout": 30})
    sw = switch_entity(hass)
    await sw.async_turn_on()
    om = core(hass, entry).override_manager
    om.set_override("light.a")
    noon.tick(timedelta(minutes=20))
    calls.clear()
    await timer_cycle(hass)
    await hass.async_block_till_done()
    assert calls_for(calls, "light.a") == []
    noon.tick(timedelta(minutes=11))
    await timer_cycle(hass)
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a") and calls_for(calls, "light.a")

    hass.config_entries.async_update_entry(entry, options={**entry.options, "override_timeout": 0})
    await hass.async_block_till_done()
    om = core(hass, entry).override_manager
    om.set_override("light.a")
    noon.tick(timedelta(days=2))
    await timer_cycle(hass)
    assert om.is_overridden("light.a")


async def test_a06_reset_on_off_disabled(hass, noon, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"override_reset_on_off": False})
    await switch_entity(hass).async_turn_on()
    om = core(hass, entry).override_manager
    om.set_override("light.a")
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await hass.async_block_till_done()
    assert om.is_overridden("light.a")
    calls.clear()
    set_light(hass, "light.a", "on", brightness=20, color_temp_kelvin=3000, **CT_ATTRS)
    await hass.async_block_till_done()
    assert calls_for(calls, "light.a") == [], "paused light keeps its own values when switched on"


async def test_a06_default_reset_on_off_and_off_lights_cleared(hass, noon, no_frontend_registration):
    async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    sw = switch_entity(hass)
    await sw.async_turn_on()
    om = core(hass, entry).override_manager
    om.set_override("light.a")
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).attributes["manual_control"] == ["light.a"]
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")
    assert hass.states.get(SWITCH).attributes["manual_control"] == []
    # A pause for a light that is off (switch-off not seen) is cleared by the cycle
    om.set_override("light.a")
    await timer_cycle(hass)
    assert not om.is_overridden("light.a")


# ---------------------------------------------------------------- F-07 event, logbook, diagnostics
@pytest.mark.usefixtures("evening")
async def test_f07_manual_control_fires_events(hass, no_frontend_registration):
    events = []
    # @callback: runs in the event loop in order (a plain function would run in
    # the executor, where the order of two events is not guaranteed)
    hass.bus.async_listen("hcl_lighting_manual_control", callback(lambda event: events.append(event)))
    _calls, entry = await _light_on(hass)
    om = core(hass, entry).override_manager
    om.set_override("light.a")
    om.set_override("light.a")  # no second event without change
    om.reset_override("light.a")
    await hass.async_block_till_done()
    assert [(e.data["entity_id"], e.data["manual_control"]) for e in events] == [
        ("light.a", True), ("light.a", False)
    ]
    assert events[0].data["instance"] == "HCL"


@pytest.mark.usefixtures("evening")
async def test_f07_logbook_describes_the_event(hass, no_frontend_registration):
    from custom_components.hcl_lighting import logbook as hcl_logbook
    from homeassistant.core import Event

    described = {}
    hcl_logbook.async_describe_events(hass, lambda domain, event, fn: described.setdefault(event, fn))
    fn = described["hcl_lighting_manual_control"]
    entry = fn(Event("hcl_lighting_manual_control", {"entity_id": "light.a", "manual_control": True, "instance": "Wohnen"}))
    assert entry["entity_id"] == "light.a" and entry["name"] == "HCL Wohnen" and entry["message"]


# ---------------------------------------------------------------- RM-B24
@pytest.mark.usefixtures("_late_morning")
@pytest.mark.parametrize("states", [["unavailable"], ["unknown"], ["unavailable", "unknown"]])
async def test_rm_b24_short_gap_keeps_manual_control(hass, no_frontend_registration, freezer, states):
    calls, _entry, om = await _manual_light(hass, freezer)
    await _gap(hass, freezer, states, 20)
    assert om.is_overridden("light.a")  # unavailable/unknown is not "switched off"
    await _back_on(hass)
    assert om.is_overridden("light.a")
    assert calls == []  # HCL does not overwrite the user's values


@pytest.mark.usefixtures("_late_morning")
async def test_rm_b24_long_gap_counts_as_switched_off(hass, no_frontend_registration, freezer):
    calls, _entry, om = await _manual_light(hass, freezer)
    # each step shorter than the limit, together longer: the gap counts from the first
    step = UNREACHABLE_GRACE_SECONDS / 2 + 10
    await _gap(hass, freezer, ["unavailable", "unknown"], step)
    assert om.is_overridden("light.a")
    await _back_on(hass)
    assert not om.is_overridden("light.a")
    assert calls, "a lamp back after a long gap gets the HCL values (fast path)"


@pytest.mark.usefixtures("_late_morning")
async def test_rm_b24_long_gap_keeps_manual_control_without_reset_on_off(
    hass, no_frontend_registration, freezer
):
    calls, _entry, om = await _manual_light(hass, freezer, options={"override_reset_on_off": False})
    await _gap(hass, freezer, ["unavailable"], UNREACHABLE_GRACE_SECONDS + 60)
    await _back_on(hass)
    assert om.is_overridden("light.a") and calls == []


@pytest.mark.usefixtures("_late_morning")
async def test_rm_b24_back_as_off_ends_manual_control(hass, no_frontend_registration, freezer):
    _calls, _entry, om = await _manual_light(hass, freezer)
    await _gap(hass, freezer, ["unavailable"], 20)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")


@pytest.mark.usefixtures("_late_morning")
@pytest.mark.parametrize("gap", [None, "unavailable", "unknown"])
async def test_rm_b24_persisted_manual_control_survives_the_restart(
    hass, hass_storage, no_frontend_registration, freezer, gap
):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", **ON)
    entry = await setup_entry(hass, ["light.a"], options={"persist_overrides": True})
    await switch_entity(hass).async_turn_on()
    core(hass, entry).override_manager.set_override("light.a")
    await hass.config_entries.async_unload(entry.entry_id)
    hass.bus.async_fire("homeassistant_final_write")
    await hass.async_block_till_done()
    hass.data[DATA_OVERRIDE_MANAGERS].pop(entry.entry_id)  # restart: in-memory state gone
    assert await hass.config_entries.async_setup(entry.entry_id)
    await switch_entity(hass).async_turn_on()  # restored "HCL active" = on
    await hass.async_block_till_done()
    om = core(hass, entry).override_manager
    assert om.is_overridden("light.a")
    freezer.tick(timedelta(seconds=30))
    calls.clear()
    if gap:  # MQTT/Zigbee lights report unavailable/unknown right after the start
        await _gap(hass, freezer, [gap], 40)
    await _back_on(hass)
    assert om.is_overridden("light.a")
    assert calls == []


# ---------------------------------------------------------------- RM-B04
async def test_rm_b04_failed_smooth_return_hands_the_light_back(hass, no_frontend_registration, freezer):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={"override_timeout": 1})
    await hcl_on(hass)
    om = core(hass, entry).override_manager
    om.set_override("light.a")
    freezer.tick(timedelta(minutes=2))
    lights.fail = {"light.a"}
    await timer_cycle(hass)
    await hass.async_block_till_done()
    assert not om.is_overridden("light.a")
    assert not om.is_reengaging("light.a")  # the 3-minute protection ends with the failure


# ---------------------------------------------------------------- B-17
async def test_b17_expired_override_does_not_turn_on_off_light(hass, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    sw = switch_entity(hass)
    om = core(hass, entry).override_manager
    await sw.async_turn_on()
    om.set_override("light.a", since=dt_util.now() - timedelta(hours=5))
    await sw.async_turn_off()
    set_light(hass, "light.a", "off", **CT_ATTRS)  # not seen by HCL (switch off)
    await hass.async_block_till_done()
    calls.clear()
    await sw.async_turn_on()
    await hass.async_block_till_done()
    assert calls_for(calls, "light.a") == []


async def test_b17_expired_override_reengages_light_that_is_on(hass, no_frontend_registration, freezer):
    # 20:00: the curve asks for warm, dim light, i.e. different values than the light has
    calls, om = await _expire_override_of_light_at(hass, freezer, 20, 0)
    assert not om.is_overridden("light.a")
    assert calls_for(calls, "light.a"), "light that is on must be re-engaged"


async def test_b17_expired_override_released_without_command_if_values_match(
    hass, no_frontend_registration, freezer
):
    # 12:00: the default curve asks for 100 %/6000 K, the values the light already has;
    # the light is released, traffic control sends nothing
    calls, om = await _expire_override_of_light_at(hass, freezer, 12, 0)
    assert not om.is_overridden("light.a")
    assert calls_for(calls, "light.a") == []


# ---------------------------------------------------------------- RM-T03
@pytest.mark.usefixtures("_late_morning")
async def test_rm_t03_stored_manual_control_keeps_its_format(hass, hass_storage, no_frontend_registration):
    """The typed override state reads and writes the stored format of 0.8.0b1
    ({light: start of manual control as ISO time})."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    since = (dt_util.now() - timedelta(minutes=30)).replace(microsecond=0)
    hass_storage["hcl_lighting.overrides.hcl_t03"] = {
        "version": 1, "minor_version": 1, "key": "hcl_lighting.overrides.hcl_t03",
        "data": {"light.a": since.isoformat()},
    }
    async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", **ON)
    entry = MockConfigEntry(
        domain="hcl_lighting", title="HCL", entry_id="hcl_t03",
        options={"target": {"entity_id": ["light.a"]}, "persist_overrides": True}, minor_version=2,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    om = core(hass, entry).override_manager
    assert om.is_overridden("light.a")
    assert om.export_overrides() == {"light.a": since.isoformat()}
