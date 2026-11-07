"""Wake and sleep time as entities (RM-E05): stretching, checks, no reload,
scenario end, permissions, preview, interfaces (tests E05-T01 to E05-T30)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from homeassistant.core import Context, State, callback
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
    mock_restore_cache_with_extra_data,
)

from custom_components.hcl_lighting.const import (
    CONF_CURVE_CONFIG,
    CONF_SLEEP_TIME,
    CONF_WAKE_TIME,
    DOMAIN,
    signal_update,
)
from custom_components.hcl_lighting.logic.hcl_math import (
    HCLCalculator,
    anchor_pair_error,
    default_points,
    normalize_points,
    saved_points,
    stretch_points,
)
from custom_components.hcl_lighting.time import async_set_anchor_time

from .support.curves import CUSTOM_POINTS
from .support.entries import CT_ATTRS, DIM, SELECT, SENSOR, SWITCH, calls_for, core, hcl_on, light_on, set_light, setup_entry
from .support.lights import FakeLights

WAKE = "time.hcl_wake_time"
SLEEP = "time.hcl_sleep_time"


def _hm(text: str) -> int:
    hours, minutes = text.split(":")[:2]
    return int(hours) * 60 + int(minutes)


def _at(points, hhmm: str) -> tuple[int, int]:
    """Brightness and kelvin of a curve at a local time (limits 1-100 %)."""
    calc = HCLCalculator()
    calc.calculate_curve_from_points(points)
    minutes = _hm(hhmm)
    return calc.get_hcl_values(datetime(2026, 1, 1, minutes // 60, minutes % 60), 1, 100)


def _times(points) -> list[str]:
    return [f"{p['t'] // 60:02d}:{p['t'] % 60:02d}" for p in points]


def _v3(points, wake: str, sleep: str) -> dict:
    return {"version": 3, "points": points, CONF_WAKE_TIME: wake, CONF_SLEEP_TIME: sleep}


async def _call(hass, entity_id: str, value: str, context: Context | None = None) -> None:
    await hass.services.async_call(
        "time", "set_value", {"entity_id": entity_id, "time": value}, blocking=True, context=context
    )


async def _set(hass, entity_id: str, value: str, context: Context | None = None) -> None:
    await _call(hass, entity_id, value, context)
    await hass.async_block_till_done()


@pytest.fixture
def reloads(hass):
    """Entry ids reloaded during the test."""
    calls: list[str] = []
    real_reload = hass.config_entries.async_reload

    async def _reload(entry_id):
        calls.append(entry_id)
        return await real_reload(entry_id)

    hass.config_entries.async_reload = _reload
    return calls


@pytest.fixture
async def berlin(hass):
    await hass.config.async_set_time_zone("Europe/Berlin")


# ---------------------------------------------------------------- stretching (E05-T01 to T05, T25, T26, T29, T30)
def test_e05_t01_same_shift_of_both_times_is_a_pure_shift():
    ref = default_points("07:00", "22:00")
    out = stretch_points(normalize_points(ref), _hm("07:00"), _hm("22:00"), _hm("08:00"), _hm("23:00"))
    assert out == sorted(({**p, "t": (p["t"] + 60) % 1440} for p in ref), key=lambda p: p["t"])
    # unchanged times: the reference curve itself
    assert stretch_points(normalize_points(ref), 420, 1320, 420, 1320) == normalize_points(ref)


def test_e05_t02_later_sleep_time_stretches_the_day_and_compresses_the_night():
    ref = normalize_points(default_points("07:00", "22:00"))
    out = stretch_points(ref, 420, 1320, 420, 1380)
    by_value = {(p["b"], p["k"], i): p["t"] for i, p in enumerate(out)}
    assert {p["t"] for p in out} >= {420, 1380}  # the anchor points stay on the anchors
    assert [p["t"] for p in out if p["t"] == 420][0] == 420
    # day points: 900 -> 960 minutes from the wake time
    for p in ref:
        rel = (p["t"] - 420) % 1440
        if 0 < rel < 900:
            assert {**p, "t": (420 + round(rel * 960 / 900)) % 1440} in out
    # night: 540 -> 480 minutes, the point one minute before the wake time stays there
    assert {"t": 419, "b": 5, "k": 2200} in out
    assert len(by_value) == len(ref)


def test_e05_t03_stretching_over_midnight():
    ref = normalize_points(default_points("07:00", "22:00"))
    out = stretch_points(ref, 420, 1320, 420, 30)  # sleep time 00:30
    assert all(0 <= p["t"] < 1440 for p in out)
    assert {"t": 30, "b": 10, "k": 2200} in out  # sleep anchor at 00:30
    assert {"t": 420, "b": 30, "k": 3000} in out
    assert out == sorted(out, key=lambda p: p["t"])


def test_e05_t05_collision_and_clamp_rule():
    # K04 (old values, night of 1 min): the night point is dropped, 30 % / 3000 K at 07:00
    ref = [{"t": 419, "b": 5, "k": 2200}, {"t": 420, "b": 30, "k": 3000}, {"t": 1000, "b": 100, "k": 5000}]
    out = stretch_points(normalize_points(ref), 420, 1320, 420, 419)
    assert {"t": 420, "b": 30, "k": 3000} in out and all(p["t"] != 419 for p in out)
    assert _at(out, "07:00") == (30, 3000)
    # mirrored at the sleep point: a day without a free minute drops its inner points
    ref2 = [{"t": 420, "b": 30, "k": 3000}, {"t": 1319, "b": 50, "k": 4000}, {"t": 1320, "b": 10, "k": 2200}]
    out2 = stretch_points(normalize_points(ref2), 420, 1320, 420, 421)
    assert out2 == [{"t": 420, "b": 30, "k": 3000}, {"t": 421, "b": 10, "k": 2200}]
    # no point next to an anchor lands on an anchor
    ref3 = normalize_points(default_points("07:00", "22:00"))
    for w1, s1 in ((300, 30), (240, 0), (420, 1100), (60, 1430)):
        out3 = stretch_points(ref3, 420, 1320, w1, s1)
        anchors = {w1 % 1440, s1 % 1440}
        assert [p for p in out3 if p["t"] in anchors] == [
            p for p in out3 if (p["b"], p["k"]) in ((30, 3000), (10, 2200)) and p["t"] in anchors
        ]
        # at most one point per minute
        assert len({p["t"] for p in out3}) == len(out3)
        # independent of the order of the input
        assert stretch_points(list(reversed(ref3)), 420, 1320, w1, s1) == out3
    # points falling on the same minute: closest to the exact position wins
    crowded = [{"t": 420, "b": 30, "k": 3000}, {"t": 600, "b": 40, "k": 3500},
               {"t": 601, "b": 41, "k": 3600}, {"t": 1320, "b": 10, "k": 2200}]
    out4 = stretch_points(crowded, 420, 1320, 420, 790)  # day 900 -> 370 min
    assert len(out4) == 3 and {"t": 494, "b": 40, "k": 3500} in out4
    # the reference curve is not changed
    assert crowded[1] == {"t": 600, "b": 40, "k": 3500}


def test_e05_t05_point_at_midnight():
    ref = [{"t": 1440, "b": 20, "k": 2200}, {"t": 420, "b": 30, "k": 3000}, {"t": 1320, "b": 10, "k": 2200}]
    out = stretch_points(normalize_points(ref), 420, 1320, 480, 1380)
    assert {"t": 60, "b": 20, "k": 2200} in out


def test_e05_t25_only_the_wake_time_changes():
    """Morning moves, day and evening are compressed proportionally."""
    options = {CONF_WAKE_TIME: "08:30:00", CONF_SLEEP_TIME: "22:30:00",
               CONF_CURVE_CONFIG: _v3(default_points("06:30", "22:30"), "06:30:00", "22:30:00")}
    points = saved_points(options)
    times = _times(points)
    assert "08:48" in times and times[times.index("08:48")] == "08:48"
    assert {"t": _hm("08:48"), "b": 90, "k": 4500} in points  # 90 % reached at 08:48
    assert {"t": _hm("19:52"), "b": 100, "k": 5000} in points  # evening from 19:52
    assert _at(points, "21:00") == (70, 3891)
    # the default curve that follows the times keeps 20 min and 3 h
    follow = default_points("08:30", "22:30")
    assert {"t": _hm("08:50"), "b": 90, "k": 4500} in follow and {"t": _hm("19:30"), "b": 100, "k": 5000} in follow


@pytest.mark.parametrize(("wake", "sleep", "night_point"), [("05:00", "00:30", "04:59"), ("04:00", "00:00", "03:59")])
def test_e05_t26_night_point_is_not_moved_onto_the_wake_time(wake, sleep, night_point):
    options = {CONF_WAKE_TIME: wake, CONF_SLEEP_TIME: sleep,
               CONF_CURVE_CONFIG: _v3(default_points("07:00", "22:00"), "07:00", "22:00")}
    points = saved_points(options)
    assert {"t": _hm(night_point), "b": 5, "k": 2200} in points
    assert _at(points, "03:30") == (5, 2200)


def test_e05_t29_normalized_before_stretching():
    """An old curve with 24:00 and 00:00 (reverse order, different values): 00:00 wins (B41)."""
    points = [{"t": 1440, "b": 90, "k": 6000}, {"t": 0, "b": 20, "k": 2200},
              {"t": 420, "b": 30, "k": 3000}, {"t": 1320, "b": 10, "k": 2200}]
    options = {CONF_WAKE_TIME: "08:00", CONF_SLEEP_TIME: "23:00", CONF_CURVE_CONFIG: _v3(points, "07:00", "22:00")}
    out = saved_points(options)
    assert {"t": 60, "b": 20, "k": 2200} in out and all(p["b"] != 90 for p in out)


def test_e05_t30_fewer_than_two_points_use_the_default_curve(caplog):
    points = [{"t": 1380, "b": 5, "k": 2200}, {"t": 1381, "b": 5, "k": 2200}]
    options = {CONF_WAKE_TIME: "07:00", CONF_SLEEP_TIME: "06:58", CONF_CURVE_CONFIG: _v3(points, "07:00", "22:00")}
    with caplog.at_level(logging.WARNING):
        assert saved_points(options) == default_points("07:00", "06:58")
    assert "fewer than 2 points" in caplog.text


def test_e05_saved_points_version_2_is_drawn_for_the_current_times():
    options = {CONF_WAKE_TIME: "06:00", CONF_SLEEP_TIME: "21:00",
               CONF_CURVE_CONFIG: {"version": 2, "points": CUSTOM_POINTS}}
    assert saved_points(options) == CUSTOM_POINTS
    assert saved_points({CONF_WAKE_TIME: "06:00", CONF_SLEEP_TIME: "21:00"}) == default_points("06:00", "21:00")


@pytest.mark.parametrize(
    ("wake", "sleep", "error"),
    [("06:30", "22:30", None), ("09:00", "00:30", None), ("02:00", "23:00", None),
     ("23:00", "22:00", "night_too_short"), ("01:59", "23:00", "night_too_short"),
     ("13:00", "19:00", "active_span_too_short"), ("13:00", "19:01", None)],
)
def test_e05_anchor_pair_rule(wake, sleep, error):
    assert anchor_pair_error(dt_util.parse_time(wake), dt_util.parse_time(sleep)) == error


# ---------------------------------------------------------------- entities (E05-T20)
async def test_e05_t20_entities(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={CONF_WAKE_TIME: "06:30:00", CONF_SLEEP_TIME: "22:30:00"})
    registry = er.async_get(hass)
    switch_device = registry.async_get(SWITCH).device_id
    for entity_id, key, name in ((WAKE, "wake_time", "HCL Wake time"), (SLEEP, "sleep_time", "HCL Sleep time")):
        entity = registry.async_get(entity_id)
        assert entity.unique_id == f"{entry.entry_id}_{key}"
        assert entity.entity_category == EntityCategory.CONFIG
        assert entity.translation_key == key and entity.device_id == switch_device
        assert hass.states.get(entity_id).attributes["friendly_name"] == name
    assert hass.states.get(WAKE).state == "06:30:00" and hass.states.get(SLEEP).state == "22:30:00"


# ---------------------------------------------------------------- check rule (E05-T06)
@pytest.mark.parametrize(
    ("entity_id", "value", "error"),
    [(SLEEP, "13:00:00", "active_span_too_short"),  # day 6 h
     (SLEEP, "13:01:00", None),  # 6 h 1 min
     (WAKE, "23:00:00", "night_too_short"),  # night 1 h
     (WAKE, "01:59:00", "night_too_short"),  # 2 h 59 min (sleep 23:00 below)
     (WAKE, "02:00:00", None)],  # 3 h
)
async def test_e05_t06_check_rule(hass, no_frontend_registration, entity_id, value, error):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "on", **DIM)
    sleep = "23:00:00" if value in ("01:59:00", "02:00:00") else "22:00:00"
    entry = await setup_entry(hass, ["light.a"], options={CONF_WAKE_TIME: "07:00:00", CONF_SLEEP_TIME: sleep})
    await hcl_on(hass)
    lights.calls.clear()
    before = dict(entry.options)
    curve = list(core(hass, entry).calculator.active_curve)
    if error is None:
        await _set(hass, entity_id, value)
        assert hass.states.get(entity_id).state == value
        return
    with pytest.raises(ServiceValidationError) as err:
        await _set(hass, entity_id, value)
    assert err.value.translation_key == error
    wake = value[:5] if entity_id == WAKE else "07:00"
    assert err.value.translation_placeholders == {"wake": wake, "sleep": value[:5] if entity_id == SLEEP else sleep[:5]}
    assert wake in str(err.value)
    assert dict(entry.options) == before and core(hass, entry).calculator.active_curve == curve
    assert lights.calls == []
    assert hass.states.get(entity_id).state == before[CONF_WAKE_TIME if entity_id == WAKE else CONF_SLEEP_TIME]


# ---------------------------------------------------------------- setup (E05-T16)
async def test_e05_t16_setup_checks_the_pair(hass, no_frontend_registration):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    data = {"name": "Büro", "target": {"entity_id": ["light.a"]}, "wake_time": "23:00:00", "sleep_time": "22:00:00"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
    assert result["errors"] == {"base": "night_too_short"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**data, "wake_time": "16:00:00"})
    assert result["errors"] == {"base": "active_span_too_short"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**data, "wake_time": "02:00:00",
                                                                                "sleep_time": "23:00:00"})
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"


# ---------------------------------------------------------------- no reload, effect (E05-T07 to T09)
async def test_e05_t07_time_change_does_not_reload(hass, no_frontend_registration, reloads, freezer, berlin):
    freezer.move_to("2026-11-10 09:00:00+00:00")  # 10:00
    lights = FakeLights(hass)
    for eid in ("light.a", "light.b"):
        set_light(hass, eid, "on", **DIM)
    entry = await setup_entry(hass, ["light.a", "light.b"])
    await hcl_on(hass)
    await hass.services.async_call(DOMAIN, "set_manual_control", {"entity_id": SWITCH, "lights": ["light.b"]},
                                   blocking=True)
    await hass.services.async_call(DOMAIN, "set_scenario", {"entity_id": SELECT, "scenario": "focus"}, blocking=True)
    await hass.async_block_till_done()
    runtime = core(hass, entry)
    lights.calls.clear()
    await _set(hass, SLEEP, "23:00:00")
    assert reloads == []
    assert entry.runtime_data is runtime and runtime.applied_config.options[CONF_SLEEP_TIME] == "23:00:00"
    assert runtime.override_manager.is_overridden("light.b")
    assert hass.states.get(SELECT).state == "focus"
    assert entry.options[CONF_SLEEP_TIME] == "23:00:00"
    # the default curve follows the times (E05-T09)
    assert runtime.calculator.active_curve == normalize_points(default_points("07:00", "23:00:00"))
    assert hass.states.get(SENSOR).attributes["sleep_time"] == "23:00"


async def test_e05_t08_lights_get_the_new_curve_at_once(hass, no_frontend_registration, freezer, berlin):
    freezer.move_to("2026-11-10 06:10:00+00:00")  # 07:10, in the morning rise of 07:00
    calls, entry = await light_on(hass)
    calls.clear()
    await _set(hass, WAKE, "06:00:00")
    sent = calls_for(calls, "light.a")
    assert sent and sent[-1].data["transition"] == 20  # transition of the updates
    assert (sent[-1].data["brightness_pct"], sent[-1].data["color_temp_kelvin"]) == _at(
        default_points("06:00", "22:00"), "07:10"
    )
    # the same time (stored "06:00:00", set 06:00:30) sends nothing
    calls.clear()
    await _set(hass, WAKE, "06:00:30")
    assert calls_for(calls, "light.a") == [] and entry.options[CONF_WAKE_TIME] == "06:00:00"
    # HCL off: stored, no light commands
    await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    await hass.async_block_till_done()
    calls.clear()
    await _set(hass, WAKE, "06:30:00")
    assert calls_for(calls, "light.a") == [] and entry.options[CONF_WAKE_TIME] == "06:30:00"


async def test_e05_t08_same_time_without_seconds_is_no_change(hass, no_frontend_registration):
    calls, entry = await light_on(hass, options={CONF_WAKE_TIME: "07:00", CONF_SLEEP_TIME: "22:00"})
    calls.clear()
    await _set(hass, WAKE, "07:00:00")
    assert calls_for(calls, "light.a") == [] and entry.options[CONF_WAKE_TIME] == "07:00"


async def test_e05_t08_adapt_switch_and_manual_control_apply(hass, no_frontend_registration, freezer, berlin):
    freezer.move_to("2026-11-10 06:10:00+00:00")
    calls = async_mock_service(hass, "light", "turn_on")
    for eid in ("light.a", "light.b"):
        set_light(hass, eid, "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    await setup_entry(hass, ["light.a", "light.b"])
    await hcl_on(hass)
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.hcl_adapt_brightness"}, blocking=True)
    await hass.services.async_call(DOMAIN, "set_manual_control", {"entity_id": SWITCH, "lights": ["light.b"]},
                                   blocking=True)
    await hass.async_block_till_done()
    calls.clear()
    await _set(hass, WAKE, "06:00:00")
    sent = calls_for(calls, "light.a")
    assert sent and "brightness_pct" not in sent[-1].data and "color_temp_kelvin" in sent[-1].data
    assert calls_for(calls, "light.b") == []


# ---------------------------------------------------------------- stored curve (E05-T04, T10, T11, T14, T24, T27, T28)
async def test_e05_t04_back_and_forth_is_lossless(hass, no_frontend_registration, reloads):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={
        CONF_WAKE_TIME: "07:00:00", CONF_SLEEP_TIME: "22:00:00",
        CONF_CURVE_CONFIG: _v3(CUSTOM_POINTS, "06:00:00", "21:00:00")})
    calc = core(hass, entry).calculator
    start = list(calc.active_curve)
    for wake, sleep in (("08:30:00", "23:45:00"), ("05:10:00", "21:00:00"), ("07:00:00", "22:00:00")):
        await _set(hass, WAKE, wake)
        await _set(hass, SLEEP, sleep)
    assert calc.active_curve == start
    assert entry.options[CONF_CURVE_CONFIG] == _v3(CUSTOM_POINTS, "06:00:00", "21:00:00")
    assert reloads == []


async def test_e05_t10_saving_stores_the_current_times_as_reference(hass, no_frontend_registration, reloads):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await _set(hass, WAKE, "06:15:00")
    await hass.services.async_call(DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": "save",
                                                            "points": CUSTOM_POINTS}, blocking=True)
    await hass.async_block_till_done()
    assert entry.options[CONF_CURVE_CONFIG] == _v3(CUSTOM_POINTS, "06:15:00", "22:00")
    assert core(hass, entry).applied_config.curve == entry.options[CONF_CURVE_CONFIG]
    assert reloads == []
    # the saved points are absolute times now: a later change stretches them
    await _set(hass, SLEEP, "23:00:00")
    assert core(hass, entry).calculator.active_curve == saved_points(entry.options) != CUSTOM_POINTS


async def test_e05_t11_times_and_stretched_curve_survive_a_reload(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={CONF_CURVE_CONFIG: {"version": 2, "points": CUSTOM_POINTS}})
    await _set(hass, WAKE, "05:30:00")
    curve = list(core(hass, entry).calculator.active_curve)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(WAKE).state == "05:30:00"
    assert core(hass, entry).calculator.active_curve == curve


async def test_e05_t14_t28_version_2_without_migration(hass, no_frontend_registration, reloads):
    lights = FakeLights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={
        CONF_WAKE_TIME: "06:00:00", CONF_SLEEP_TIME: "21:00:00",
        CONF_CURVE_CONFIG: {"points": CUSTOM_POINTS, "version": 2}})
    assert (entry.version, entry.minor_version) == (1, 2)
    assert entry.options[CONF_CURVE_CONFIG] == {"points": CUSTOM_POINTS, "version": 2}
    assert core(hass, entry).calculator.active_curve == CUSTOM_POINTS
    assert lights.calls == []
    await _set(hass, WAKE, "07:00:00")
    assert reloads == []
    assert entry.options[CONF_CURVE_CONFIG] == _v3(CUSTOM_POINTS, "06:00:00", "21:00:00")
    assert core(hass, entry).applied_config.curve == entry.options[CONF_CURVE_CONFIG]
    assert core(hass, entry).calculator.active_curve == saved_points(entry.options)


async def test_e05_t24_saving_the_default_curve_returns_to_it(hass, no_frontend_registration, reloads):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={
        CONF_WAKE_TIME: "06:30:00", CONF_SLEEP_TIME: "22:30:00",
        CONF_CURVE_CONFIG: _v3(CUSTOM_POINTS, "06:00", "21:00")})
    default = hass.states.get(SENSOR).attributes["default_points"]
    await hass.services.async_call(DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": "save",
                                                            "points": default}, blocking=True)
    await hass.async_block_till_done()
    assert CONF_CURVE_CONFIG not in entry.options and core(hass, entry).applied_config.curve is None
    assert reloads == []
    await _set(hass, WAKE, "08:00:00")
    assert core(hass, entry).calculator.active_curve == normalize_points(default_points("08:00", "22:30"))
    # one point moved: an own curve (version 3)
    moved = [dict(p) for p in hass.states.get(SENSOR).attributes["default_points"]]
    moved[1]["b"] -= 1
    await hass.services.async_call(DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": "save",
                                                            "points": moved}, blocking=True)
    await hass.async_block_till_done()
    assert entry.options[CONF_CURVE_CONFIG]["version"] == 3


async def test_e05_t27_one_source_for_the_saved_curve(hass, no_frontend_registration):
    from custom_components.hcl_lighting.diagnostics import async_get_config_entry_diagnostics

    set_light(hass, "light.a", "off", **CT_ATTRS)
    options = {CONF_WAKE_TIME: "08:00:00", CONF_SLEEP_TIME: "23:30:00",
               CONF_CURVE_CONFIG: _v3(CUSTOM_POINTS, "06:00:00", "21:00:00")}
    entry = await setup_entry(hass, ["light.a"], options=options)
    expected = saved_points(options)
    calc = core(hass, entry).calculator
    assert calc.active_curve == expected  # setup
    response = await hass.services.async_call(DOMAIN, "get_curve", {"entity_id": SENSOR}, blocking=True,
                                              return_response=True)
    assert response["saved_points"] == expected
    assert (response["wake_time"], response["sleep_time"]) == ("08:00", "23:30")
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["saved_curve"] == CUSTOM_POINTS
    assert diag["saved_curve_reference"] == {"version": 3, "wake_time": "06:00:00", "sleep_time": "21:00:00"}
    assert diag["saved_curve_effective"] == expected
    await hass.services.async_call(DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": "preview",
                                                            "points": CUSTOM_POINTS}, blocking=True)
    await hass.services.async_call(DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": "revert"}, blocking=True)
    assert calc.active_curve == expected  # revert
    await _set(hass, WAKE, "07:00:00")
    await _set(hass, WAKE, "08:00:00")
    assert calc.active_curve == expected  # time change


async def test_e05_t17_interfaces_without_own_curve(hass, no_frontend_registration):
    from custom_components.hcl_lighting.diagnostics import async_get_config_entry_diagnostics

    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await _set(hass, WAKE, "06:00:00")
    response = await hass.services.async_call(DOMAIN, "get_curve", {"entity_id": SENSOR}, blocking=True,
                                              return_response=True)
    assert response["saved_points"] is None and response["wake_time"] == "06:00"
    assert response["points"] == normalize_points(default_points("06:00", "22:00"))
    attrs = hass.states.get(SENSOR).attributes
    assert (attrs["wake_time"], attrs["sleep_time"]) == ("06:00", "22:00")
    assert attrs["default_points"] == default_points("06:00", "22:00")
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["saved_curve"] is None and diag["saved_curve_reference"] is None
    assert diag["saved_curve_effective"] is None


# ---------------------------------------------------------------- preview (E05-T18)
@pytest.mark.parametrize("mode", ["preview", "apply"])
async def test_e05_t18_preview_stays_active(hass, no_frontend_registration, mode):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options={CONF_CURVE_CONFIG: _v3(CUSTOM_POINTS, "06:00", "21:00")})
    preview = [{"t": 100, "b": 50, "k": 3000}, {"t": 800, "b": 80, "k": 5000}]
    await hass.services.async_call(DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": mode,
                                                            "points": preview}, blocking=True)
    calc = core(hass, entry).calculator
    await _set(hass, WAKE, "06:30:00")
    assert calc.preview_active is True and calc.active_curve == preview
    assert hass.states.get(SENSOR).attributes["control_points"] == preview
    await hass.services.async_call(DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": "revert"}, blocking=True)
    assert calc.preview_active is False and calc.active_curve == saved_points(entry.options)
    # saving a preview stores its points with the current times as reference
    await hass.services.async_call(DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": mode,
                                                            "points": preview}, blocking=True)
    await _set(hass, SLEEP, "23:00:00")
    await hass.services.async_call(DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": "save",
                                                            "points": preview}, blocking=True)
    await hass.async_block_till_done()
    assert entry.options[CONF_CURVE_CONFIG] == _v3(preview, "06:30:00", "23:00:00")


# ---------------------------------------------------------------- permissions (E05-T13)
async def test_e05_t13_permissions(hass, no_frontend_registration, hass_read_only_user):
    lights = FakeLights(hass)
    for eid in ("light.a", "light.b"):
        set_light(hass, eid, "on", **DIM)
    entry = await setup_entry(hass, ["light.a", "light.b"])
    await hcl_on(hass)
    hass_read_only_user.mock_policy({"entities": {"entity_ids": {WAKE: True, "light.a": True}}})
    lights.calls.clear()
    with pytest.raises(Unauthorized):
        await _set(hass, WAKE, "06:00:00", Context(user_id=hass_read_only_user.id))
    assert CONF_WAKE_TIME not in entry.options and lights.calls == []
    # without the time entity: Home Assistant refuses it
    hass_read_only_user.mock_policy({"entities": {"entity_ids": {"light.a": True, "light.b": True}}})
    with pytest.raises(Unauthorized):
        await _set(hass, WAKE, "06:00:00", Context(user_id=hass_read_only_user.id))
    hass_read_only_user.mock_policy({"entities": {"entity_ids": {WAKE: True, "light.a": True, "light.b": True}}})
    await _set(hass, WAKE, "06:00:00", Context(user_id=hass_read_only_user.id))
    assert entry.options[CONF_WAKE_TIME] == "06:00:00"
    await _set(hass, WAKE, "06:30:00")  # automation without a user
    assert entry.options[CONF_WAKE_TIME] == "06:30:00"


# ---------------------------------------------------------------- overlapping calls (E05-T22, T23)
async def test_e05_t22_overlapping_time_changes_leave_a_valid_pair(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    gates: list[asyncio.Event] = []

    async def _held(*_args):
        gate = asyncio.Event()
        gates.append(gate)
        await gate.wait()

    with patch("custom_components.hcl_lighting.time.async_check_lights", _held):
        first = hass.async_create_task(_call(hass, WAKE, "12:00:00"))
        second = hass.async_create_task(_call(hass, SLEEP, "17:00:00"))
        while len(gates) < 2:
            await asyncio.sleep(0)
        gates[0].set()
        await first
        gates[1].set()
        with pytest.raises(ServiceValidationError):
            await second
    assert (entry.options[CONF_WAKE_TIME], entry.options.get(CONF_SLEEP_TIME, "22:00")) == ("12:00:00", "22:00")


async def test_e05_t22_time_change_and_saving_overlap(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    gate, entered = asyncio.Event(), asyncio.Event()

    async def _held(*_args):
        entered.set()
        await gate.wait()

    with patch("custom_components.hcl_lighting.services.async_check_lights", _held):
        save = hass.async_create_task(hass.services.async_call(
            DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": "save", "points": CUSTOM_POINTS}, blocking=True
        ))
        await entered.wait()
        await _call(hass, WAKE, "08:00:00")  # while the save waits for its permission check
        gate.set()
        await save
    await hass.async_block_till_done()
    # reference curve and reference times match: the times when it was written
    assert entry.options[CONF_CURVE_CONFIG] == _v3(CUSTOM_POINTS, "08:00:00", "22:00")
    assert core(hass, entry).calculator.active_curve == saved_points(entry.options) == CUSTOM_POINTS


async def test_e05_t23_pending_reload_still_happens(hass, no_frontend_registration, reloads):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    # options saved, the update listener has not run yet
    hass.config_entries.async_update_entry(entry, options={**entry.options, "transition": 10})
    await async_set_anchor_time(hass, entry, CONF_WAKE_TIME, dt_util.parse_time("06:00"), None)
    await hass.async_block_till_done()
    assert reloads == [entry.entry_id]
    assert core(hass, entry).applied_config.options["transition"] == 10
    assert entry.options[CONF_WAKE_TIME] == "06:00:00"


# ---------------------------------------------------------------- scenario end (E05-T12)
async def _night(hass, freezer, local: str, wake="07:00:00", mode="night_light", **extra):
    """Night light (or Sleep) chosen at a local time in Berlin (2026-11-10, UTC+1)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(dt_util.as_utc(dt_util.parse_datetime(f"2026-11-10T{local}:00+01:00")))
    calls, entry = await light_on(hass, options={CONF_WAKE_TIME: wake, "scenario_transition": 3})
    await hass.services.async_call(
        DOMAIN, "set_scenario", {"entity_id": SELECT, "scenario": mode, **extra}, blocking=True
    )
    await hass.async_block_till_done()
    return calls, entry


def _until(hass):
    until = hass.states.get(SELECT).attributes["until"]
    return dt_util.as_local(dt_util.parse_datetime(until)).strftime("%d. %H:%M") if until else None


def _fire(hass, freezer, utc: datetime):
    freezer.move_to(utc)
    async_fire_time_changed(hass, utc)


@pytest.mark.parametrize("mode", ["sleep", "night_light"])
async def test_e05_t12_earlier_wake_time_moves_the_end(hass, no_frontend_registration, freezer, mode):
    await _night(hass, freezer, "23:00", mode=mode)
    assert _until(hass) == "11. 07:00"
    freezer.tick(timedelta(minutes=30))
    await _set(hass, WAKE, "06:00:00")
    assert _until(hass) == "11. 06:00"  # visible at once
    _fire(hass, freezer, dt_util.parse_datetime("2026-11-11T05:00:01+00:00"))
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "auto"


async def test_e05_t12_later_wake_time_and_the_old_timer(hass, no_frontend_registration, freezer):
    await _night(hass, freezer, "23:00")
    _fire(hass, freezer, dt_util.parse_datetime("2026-11-11T05:45:00+00:00"))  # 06:45
    await _set(hass, WAKE, "09:00:00")
    assert _until(hass) == "11. 09:00"
    _fire(hass, freezer, dt_util.parse_datetime("2026-11-11T06:00:01+00:00"))  # 07:00: the old timer is gone
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "night_light"
    _fire(hass, freezer, dt_util.parse_datetime("2026-11-11T08:00:01+00:00"))
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "auto"


@pytest.mark.parametrize(("start", "change_at", "wake"), [("23:00", "2026-11-11T05:45:00+00:00", "06:30:00"),
                                                         ("02:00", "2026-11-10T01:30:00+00:00", "01:00:00")])
async def test_e05_t12_wake_time_already_past_ends_now(hass, no_frontend_registration, freezer, start, change_at, wake):
    calls, entry = await _night(hass, freezer, start)
    _fire(hass, freezer, dt_util.parse_datetime(change_at))
    await hass.async_block_till_done()
    calls.clear()
    signals = []
    async_dispatcher_connect(hass, signal_update(entry.entry_id), callback(lambda *a: signals.append(a)))
    await _set(hass, WAKE, wake)
    assert hass.states.get(SELECT).state == "auto" and _until(hass) is None
    assert len(signals) == 1
    assert calls_for(calls, "light.a")[-1].data["transition"] == 3  # transition of a scenario change


async def test_e05_t12_ends_that_stay(hass, no_frontend_registration, freezer):
    await _night(hass, freezer, "23:00")
    # rejected value: the end stays
    with pytest.raises(ServiceValidationError):
        await _set(hass, WAKE, "23:00:00")
    assert _until(hass) == "11. 07:00"
    # only the sleep time: the end stays
    await _set(hass, SLEEP, "23:30:00")
    assert _until(hass) == "11. 07:00"


@pytest.mark.parametrize(("duration", "until"), [(75, "11. 00:15"), (0, None)])
async def test_e05_t12_end_with_duration_stays(hass, no_frontend_registration, freezer, duration, until):
    await _night(hass, freezer, "23:00", duration=duration)
    assert _until(hass) == until
    await _set(hass, WAKE, "06:00:00")
    assert _until(hass) == until and hass.states.get(SELECT).state == "night_light"


async def test_e05_t12_moved_end_survives_a_reload(hass, no_frontend_registration, freezer):
    _calls, entry = await _night(hass, freezer, "23:00")
    await _set(hass, WAKE, "06:00:00")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "night_light" and _until(hass) == "11. 06:00"
    await _set(hass, WAKE, "06:30:00")  # still follows the wake time
    assert _until(hass) == "11. 06:30"


async def test_e05_t12_restore_without_the_field_keeps_the_end(hass, no_frontend_registration, freezer):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-11-10T22:00:00+00:00")
    until = "2026-11-11T06:00:00+00:00"
    mock_restore_cache_with_extra_data(hass, [(State(SELECT, "night_light"), {"until": until})])
    await light_on(hass)
    assert _until(hass) == "11. 07:00"
    await _set(hass, WAKE, "06:00:00")
    assert _until(hass) == "11. 07:00"


@pytest.mark.parametrize(
    ("start_utc", "wake", "expected_utc"),
    [
        # 28.03.2027: 02:30 does not exist in Berlin, it becomes 03:30 summer time
        ("2027-03-27T22:00:00+00:00", "02:30:00", "2027-03-28T01:30:00+00:00"),
        # 31.10.2027: 02:30 exists twice, the first one (summer time) counts
        ("2027-10-30T21:00:00+00:00", "02:30:00", "2027-10-31T00:30:00+00:00"),
    ],
)
async def test_e05_t12_summer_and_winter_time(hass, no_frontend_registration, freezer, start_utc, wake, expected_utc):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(start_utc)  # 23:00 local
    await light_on(hass)
    await hass.services.async_call(DOMAIN, "set_scenario", {"entity_id": SELECT, "scenario": "night_light"},
                                   blocking=True)
    await hass.async_block_till_done()
    await _set(hass, WAKE, wake)
    until = dt_util.parse_datetime(hass.states.get(SELECT).attributes["until"])
    assert until == dt_util.parse_datetime(expected_utc)


async def test_e05_t12_local_date_differs_from_utc(hass, no_frontend_registration, freezer):
    await hass.config.async_set_time_zone("Asia/Tokyo")
    freezer.move_to("2026-11-10T14:00:00+00:00")  # 23:00 in Tokyo
    await light_on(hass)
    await hass.services.async_call(DOMAIN, "set_scenario", {"entity_id": SELECT, "scenario": "night_light"},
                                   blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).attributes["until"] == "2026-11-10T22:00:00+00:00"  # 07:00 on the 11th
    await _set(hass, WAKE, "06:00:00")
    assert hass.states.get(SELECT).attributes["until"] == "2026-11-10T21:00:00+00:00"
