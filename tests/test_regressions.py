"""Regression tests for verified bugs from REVIEW_v0.5.0-beta2 (IDs B-xx)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol
from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import floor_registry as fr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import label_registry as lr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_mock_service,
    mock_restore_cache,
)

from custom_components.hcl_lighting import _async_register_lovelace_resource
from custom_components.hcl_lighting.const import (
    CONF_CURVE_CONFIG,
    CONF_MAX_BRIGHTNESS,
    CONF_MIDDAY_TIME,
    CONF_MIN_BRIGHTNESS,
    CONF_SLEEP_TIME,
    CONF_WAKE_TIME,
    DOMAIN,
)
from custom_components.hcl_lighting.logic.hcl_math import HCLCalculator

from .helpers import CT_ATTRS, core, set_light, setup_entry, switch_entity

COMPONENT = Path(__file__).parent.parent / "custom_components" / "hcl_lighting"


def _calls_for(calls, entity_id):
    out = []
    for c in calls:
        ids = c.data.get("entity_id")
        ids = [ids] if isinstance(ids, str) else list(ids or [])
        if entity_id in ids:
            out.append(c)
    return out


@pytest.fixture
async def berlin(hass: HomeAssistant, freezer):
    """Fixed local time 11:00 Europe/Berlin (curve plateau: 100 % / 6500 K)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-01-15 10:00:00+00:00")
    return freezer


# ---------------------------------------------------------------- B-01
async def test_b01_sleep_mode_allows_manual_turn_on(hass, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    sw = switch_entity(hass)
    await sw.async_turn_on()
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.hcl_scenario", "option": "sleep"}, blocking=True
    )
    await hass.async_block_till_done()
    calls.clear()

    # User switches the light on at night (wall switch / app).
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=2700, **CT_ATTRS)
    await hass.async_block_till_done()
    await sw._update_hcl()
    await hass.async_block_till_done()

    assert _calls_for(calls, "light.a") == [], "Sleep mode must not switch a manually switched-on light off again"
    assert core(hass, entry)["override_manager"].is_overridden("light.a")


async def test_b01_sleep_mode_still_turns_off_lights_on_activation(hass, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=2700, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    sw = switch_entity(hass)
    await sw.async_turn_on()
    calls.clear()
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.hcl_scenario", "option": "sleep"}, blocking=True
    )
    await hass.async_block_till_done()
    sent = _calls_for(calls, "light.a")
    assert sent and sent[-1].data["brightness_pct"] == 0


# ---------------------------------------------------------------- B-03
async def _run_options_flow(hass, entry, **changes):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    current = {
        "target": {"entity_id": ["light.a"]},
        CONF_WAKE_TIME: "07:00:00",
        CONF_MIDDAY_TIME: "12:30:00",
        CONF_SLEEP_TIME: "22:00:00",
        "smart_transition": False,
        CONF_MIN_BRIGHTNESS: 10,
        CONF_MAX_BRIGHTNESS: 100,
    }
    current.update(changes)
    result = await hass.config_entries.options.async_configure(result["flow_id"], current)
    # Steps "behavior" and "scenarios" with their defaults
    while result["type"] == "form" and result["step_id"] in ("behavior", "scenarios"):
        result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    return result


CUSTOM_POINTS = [{"t": 360, "b": 20, "k": 2700}, {"t": 720, "b": 90, "k": 5000}, {"t": 1260, "b": 10, "k": 2200}]


async def test_b03_options_save_keeps_custom_curve(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(
        hass,
        ["light.a"],
        options={
            CONF_WAKE_TIME: "07:00:00",
            CONF_MIDDAY_TIME: "12:30:00",
            CONF_SLEEP_TIME: "22:00:00",
            CONF_CURVE_CONFIG: {"points": CUSTOM_POINTS, "version": 2},
        },
    )
    await _run_options_flow(hass, entry, **{CONF_MAX_BRIGHTNESS: 80})
    assert entry.options[CONF_MAX_BRIGHTNESS] == 80
    assert entry.options.get(CONF_CURVE_CONFIG, {}).get("points") == CUSTOM_POINTS


async def test_b03_changed_anchor_times_regenerate_curve(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(
        hass,
        ["light.a"],
        options={
            CONF_WAKE_TIME: "07:00:00",
            CONF_MIDDAY_TIME: "12:30:00",
            CONF_SLEEP_TIME: "22:00:00",
            CONF_CURVE_CONFIG: {"points": CUSTOM_POINTS, "version": 2},
        },
    )
    await _run_options_flow(hass, entry, **{CONF_WAKE_TIME: "06:00:00"})
    assert CONF_CURVE_CONFIG not in entry.options
    first = core(hass, entry)["calculator"].active_curve[0]
    assert first["t"] == 360 and first["k"] == 2700  # regenerated from new wake time


# ---------------------------------------------------------------- B-04
async def test_b04_kelvin_change_inside_ignore_window_is_detected(hass, berlin, no_frontend_registration):
    async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    sw = switch_entity(hass)
    await sw.async_turn_on()  # sends 100 % / 6500 K and opens the ignore window
    om = core(hass, entry)["override_manager"]
    assert not om.is_overridden("light.a")
    # Light has reached the HCL target ...
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
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
    om = core(hass, entry)["override_manager"]
    # Intermediate transition reports moving towards 100 % / 6500 K.
    for b, k in ((170, 5000), (220, 6000), (255, 6500)):
        set_light(hass, "light.a", "on", brightness=b, color_temp_kelvin=k, **CT_ATTRS)
        await hass.async_block_till_done()
    assert not om.is_overridden("light.a")


# ---------------------------------------------------------------- B-05
async def test_b05_xy_light_is_not_resent_every_cycle(hass, berlin, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    xy_attrs = {"supported_color_modes": ["xy"], "color_mode": "xy"}
    set_light(hass, "light.rgb", "on", brightness=10, xy_color=(0.5, 0.4), **xy_attrs)
    await setup_entry(hass, ["light.rgb"])
    sw = switch_entity(hass)
    await sw.async_turn_on()
    await hass.async_block_till_done()
    sent = _calls_for(calls, "light.rgb")
    assert sent, "first cycle must send"
    x, y = sent[-1].data["xy_color"]
    # Light reports exactly what was sent (xy mode => color_temp_kelvin is None).
    set_light(hass, "light.rgb", "on", brightness=255, xy_color=(round(x, 4), round(y, 4)), color_temp_kelvin=None, **xy_attrs)
    await hass.async_block_till_done()
    calls.clear()
    await sw._update_hcl()
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.rgb") == []


async def test_b05_clamped_ct_light_is_not_resent_every_cycle(hass, berlin, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    attrs = dict(CT_ATTRS, min_color_temp_kelvin=2200, max_color_temp_kelvin=4000)
    set_light(hass, "light.ikea", "on", brightness=255, color_temp_kelvin=4000, **attrs)
    await setup_entry(hass, ["light.ikea"])
    sw = switch_entity(hass)
    await sw.async_turn_on()
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.ikea") == [], "light already at its maximum reachable CT and 100 %"
    await sw._update_hcl()
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.ikea") == []


async def test_b05_ct_light_in_range_still_updates(hass, berlin, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=4000, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    await switch_entity(hass).async_turn_on()
    await hass.async_block_till_done()
    sent = _calls_for(calls, "light.a")
    assert sent and sent[-1].data["color_temp_kelvin"] == 6500


async def test_b05_clamped_light_brightness_change_still_updates(hass, berlin, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    attrs = dict(CT_ATTRS, min_color_temp_kelvin=2200, max_color_temp_kelvin=4000)
    set_light(hass, "light.ikea", "on", brightness=100, color_temp_kelvin=4000, **attrs)
    await setup_entry(hass, ["light.ikea"])
    await switch_entity(hass).async_turn_on()
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.ikea")


# ---------------------------------------------------------------- B-06
async def test_b06_override_survives_entry_reload(hass, no_frontend_registration):
    async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    om = core(hass, entry)["override_manager"]
    om.set_last_set_values("light.a", 50, 4000)
    om.check_override("light.a", State("light.a", "on", {"brightness": 255, "color_temp_kelvin": 4000}), None)
    assert om.is_overridden("light.a")

    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_MAX_BRIGHTNESS: 90})
    await hass.async_block_till_done()
    assert core(hass, entry)["override_manager"].is_overridden("light.a")


async def test_b06_override_state_dropped_when_entry_removed(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id not in hass.data.get(f"{DOMAIN}_override_managers", {})


# ---------------------------------------------------------------- B-08
@pytest.mark.parametrize(
    ("wake", "midday", "sleep"),
    [
        ("07:00", "12:30", "22:00"),
        ("10:00", "12:30", "23:00"),
        ("07:00", "14:00", "21:00"),
        ("09:00", "13:00", "01:00"),
        ("05:00", "12:30", "22:00"),
        ("08:00", "12:00", "18:00"),  # 10 h day: too short for the full template
        ("22:00", "03:00", "14:00"),  # night shift
    ],
)
def test_b08_anchor_curves_are_strictly_ordered(wake, midday, sleep):
    calc = HCLCalculator()
    pts = calc.migrate_legacy_config(wake, midday, sleep)["points"]
    assert len(pts) == 12
    w = int(wake[:2]) * 60 + int(wake[3:])
    rel = [(p["t"] - w) % 1440 for p in pts]
    assert rel[0] == 0
    assert all(a < b for a, b in zip(rel, rel[1:])), f"not strictly increasing: {rel}"
    s = int(sleep[:2]) * 60 + int(sleep[3:])
    assert pts[-1]["t"] == s % 1440


def test_b08_valid_default_anchors_unchanged():
    calc = HCLCalculator()
    pts = calc.migrate_legacy_config("07:00", "12:30", "22:00")["points"]
    assert [p["t"] for p in pts] == [420, 540, 570, 600, 720, 750, 780, 810, 840, 960, 1080, 1320]


# ---------------------------------------------------------------- B-09
def _js_reference(points, t_target, key):
    """Port of hcl-curve-card.js _pchip (tripled arrays => circular curve)."""
    s = sorted(points, key=lambda p: p["t"])
    X, Y = [], []
    for off in (-1440, 0, 1440):
        for p in s:
            X.append(p["t"] + off)
            Y.append(p[key])
    i = 0
    while i < len(X) - 2 and t_target > X[i + 1]:
        i += 1

    def slope(a, b, c):
        dl, dr = b[0] - a[0], c[0] - b[0]
        if dl == 0 or dr == 0:
            return 0
        d1, d2 = (b[1] - a[1]) / dl, (c[1] - b[1]) / dr
        if d1 * d2 <= 0:
            return 0
        w1, w2 = 2 * dr + dl, dr + 2 * dl
        return (w1 + w2) / (w1 / d1 + w2 / d2)

    P = lambda j: (X[j], Y[j])
    cu, nx, pv, nn = P(i), P(i + 1), P(i - 1), P(i + 2)
    m0, m1 = slope(pv, cu, nx), slope(cu, nx, nn)
    h = nx[0] - cu[0]
    t = (t_target - cu[0]) / h
    t2, t3 = t * t, t * t * t
    return (2 * t3 - 3 * t2 + 1) * cu[1] + (t3 - 2 * t2 + t) * h * m0 + (-2 * t3 + 3 * t2) * nx[1] + (t3 - t2) * h * m1


def test_b09_two_point_curve_does_not_crash():
    calc = HCLCalculator()
    calc.calculate_curve_from_points([{"t": 360, "k": 2700, "b": 20}, {"t": 1200, "k": 5000, "b": 80}])
    for h in range(24):
        b, k = calc.get_hcl_values(datetime(2026, 1, 1, h, 0), 0, 100)
        assert 20 <= b <= 80 and 2700 <= k <= 5000


DAY_ONLY = [
    {"t": t, "k": k, "b": b}
    for t, k, b in [
        (360, 2700, 20), (420, 4000, 50), (480, 5000, 80), (540, 6000, 100), (600, 6000, 100), (660, 5000, 80),
        (720, 4500, 70), (780, 5000, 80), (840, 4500, 70), (900, 3500, 50), (960, 3000, 40), (1020, 2700, 30),
    ]
]


def test_b09_gap_over_12h_matches_card_and_has_no_overshoot():
    calc = HCLCalculator()
    calc.calculate_curve_from_points(DAY_ONLY)
    for m in range(0, 1440, 15):
        b, k = calc.get_hcl_values(datetime(2026, 1, 1, m // 60, m % 60), 0, 100)
        assert abs(b - round(_js_reference(DAY_ONLY, m, "b"))) <= 1, m
        assert abs(k - round(_js_reference(DAY_ONLY, m, "k"))) <= 1, m
        if m >= 1020 or m < 360:  # overnight segment 17:00 (30 %) -> 06:00 (20 %)
            assert 20 <= b <= 30, (m, b)


def test_b09_default_curve_unchanged():
    """Default curve values must not change through the slope fix (all gaps < 12 h)."""
    calc = HCLCalculator()
    got = [calc.get_hcl_values(datetime(2026, 1, 1, h, 0), 10, 100) for h in (0, 3, 6, 9, 12, 15, 18, 21)]
    assert got == [(11, 2219), (16, 2332), (26, 2581), (50, 4500), (100, 6500), (65, 5197), (30, 2700), (12, 2236)]


# ---------------------------------------------------------------- B-10
async def test_b10_floor_and_label_targets_are_resolved(hass, no_frontend_registration):
    ent_reg = er.async_get(hass)
    floor = fr.async_get(hass).async_create("EG")
    area = ar.async_get(hass).async_create("Wohnen", floor_id=floor.floor_id)
    label = lr.async_get(hass).async_create("HCL")
    e1 = ent_reg.async_get_or_create("light", "test", "1", suggested_object_id="floor_light")
    ent_reg.async_update_entity(e1.entity_id, area_id=area.id)
    e2 = ent_reg.async_get_or_create("light", "test", "2", suggested_object_id="label_light")
    ent_reg.async_update_entity(e2.entity_id, labels={label.label_id})
    set_light(hass, e1.entity_id, "off", **CT_ATTRS)
    set_light(hass, e2.entity_id, "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.unused"])
    ctl = core(hass, entry)["controller"]
    assert ctl.resolve_targets({"floor_id": [floor.floor_id]}) == {e1.entity_id}
    assert ctl.resolve_targets({"label_id": label.label_id}) == {e2.entity_id}


# ---------------------------------------------------------------- B-11
async def test_b11_group_loaded_after_startup_is_expanded(hass, no_frontend_registration):
    async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=10, color_temp_kelvin=2700, **CT_ATTRS)
    set_light(hass, "light.b", "on", brightness=10, color_temp_kelvin=2700, **CT_ATTRS)
    mock_restore_cache(hass, [State("switch.hcl_hcl_active", "on")])
    hass.set_state(CoreState.not_running)
    await setup_entry(hass, ["light.group"])  # group platform not loaded yet
    sw = switch_entity(hass)
    assert sw.is_on
    # Group appears later during startup.
    hass.states.async_set("light.group", "on", {"entity_id": ["light.a", "light.b"], **CT_ATTRS})
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert sw._resolved_targets == {"light.a", "light.b"}


# ---------------------------------------------------------------- B-13
async def test_b13_curve_sensor_exposes_brightness_limits(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await setup_entry(hass, ["light.a"], options={CONF_MIN_BRIGHTNESS: 5, CONF_MAX_BRIGHTNESS: 60})
    attrs = hass.states.get("sensor.hcl_curve_data").attributes
    assert attrs["min_brightness"] == 5
    assert attrs["max_brightness"] == 60


# ---------------------------------------------------------------- B-14
CARD_URL = "/hcl_lighting_static/hcl-curve-card.js?v=0.6.0"


async def _register_with_storage(hass, hass_storage, items):
    """Run the resource registration against an unloaded storage collection (state at HA start)."""
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    hass_storage["lovelace_resources"] = {
        "version": 1,
        "minor_version": 1,
        "key": "lovelace_resources",
        "data": {"items": items},
    }
    collection = ResourceStorageCollection(hass, MagicMock())
    assert collection.loaded is False
    hass.data["lovelace"] = MagicMock(resources=collection)
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    await _async_register_lovelace_resource(hass)
    await hass.async_block_till_done()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)  # flush delayed store writes (as on shutdown)
    await hass.async_block_till_done()
    # What the frontend sees later: a fresh load from storage.
    fresh = ResourceStorageCollection(hass, MagicMock())
    await fresh.async_get_info()
    return sorted(i["url"] for i in fresh.async_items())


async def test_b14_existing_resources_preserved_and_not_duplicated(hass, hass_storage):
    items = [
        {"id": "user", "type": "module", "url": "/local/other-card.js"},
        {"id": "abc", "type": "module", "url": CARD_URL},
    ]
    urls = await _register_with_storage(hass, hass_storage, items)
    assert urls == sorted(["/local/other-card.js", CARD_URL])


async def test_b14_old_version_resource_is_replaced(hass, hass_storage):
    items = [
        {"id": "user", "type": "module", "url": "/local/other-card.js"},
        {"id": "old", "type": "module", "url": "/hcl_lighting_static/hcl-curve-card.js?v=0.4.1"},
    ]
    urls = await _register_with_storage(hass, hass_storage, items)
    assert urls == sorted(["/local/other-card.js", CARD_URL])


# ---------------------------------------------------------------- B-17
async def test_b17_expired_override_does_not_turn_on_off_light(hass, no_frontend_registration):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=128, color_temp_kelvin=4000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    sw = switch_entity(hass)
    om = core(hass, entry)["override_manager"]
    await sw.async_turn_on()
    om._override_state.setdefault("light.a", {})["manual_override_time"] = dt_util.now() - timedelta(hours=5)
    await sw.async_turn_off()
    set_light(hass, "light.a", "off", **CT_ATTRS)  # not seen by HCL (switch off)
    await hass.async_block_till_done()
    calls.clear()
    await sw.async_turn_on()
    await hass.async_block_till_done()
    assert _calls_for(calls, "light.a") == []


async def _expire_override_of_light_at(hass, freezer, hour, minute):
    """Light on at 100 %/6500 K, override expired; run one update cycle at hh:mm."""
    freezer.move_to(dt_util.now().replace(hour=hour, minute=minute, second=0, microsecond=0))
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    sw = switch_entity(hass)
    om = core(hass, entry)["override_manager"]
    await sw.async_turn_on()
    await hass.async_block_till_done()
    om._override_state.setdefault("light.a", {})["manual_override_time"] = dt_util.now() - timedelta(hours=5)
    calls.clear()
    await sw._update_hcl()
    await hass.async_block_till_done()
    return calls, om


async def test_b17_expired_override_reengages_light_that_is_on(hass, no_frontend_registration, freezer):
    # 20:00: the curve asks for warm, dim light, i.e. different values than the light has
    calls, om = await _expire_override_of_light_at(hass, freezer, 20, 0)
    assert not om.is_overridden("light.a")
    assert _calls_for(calls, "light.a"), "light that is on must be re-engaged"


async def test_b17_expired_override_released_without_command_if_values_match(
    hass, no_frontend_registration, freezer
):
    # 10:30: the default curve asks for 100 %/6500 K, the values the light already has;
    # the light is released, traffic control sends nothing
    calls, om = await _expire_override_of_light_at(hass, freezer, 10, 30)
    assert not om.is_overridden("light.a")
    assert _calls_for(calls, "light.a") == []


# ---------------------------------------------------------------- B-20
def test_b20_english_translation_has_repair_issue_and_name_label():
    for fname in ("en.json", "de.json"):
        data = json.loads((COMPONENT / "translations" / fname).read_text(encoding="utf-8"))
        assert data["issues"]["setup_curve_card"]["title"], fname
        assert "{entity_id}" in data["issues"]["setup_curve_card"]["description"], fname
        assert data["config"]["step"]["user"]["data"]["name"], fname
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    assert strings["config"]["step"]["user"]["data"]["name"]


# ---------------------------------------------------------------- B-21
async def test_b21_update_curve_service_validates_input(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    for bad in (
        {"entity_id": "sensor.hcl_curve_data", "mode": "save"},  # no points
        {"entity_id": "sensor.hcl_curve_data", "mode": "save", "points": [{"t": 5000, "b": 50, "k": 3000}] * 2},
        {"entity_id": "sensor.hcl_curve_data", "mode": "preview", "points": [{"t": 60, "b": 50}]},
        {"entity_id": "sensor.hcl_curve_data", "mode": "bogus", "points": CUSTOM_POINTS},
    ):
        with pytest.raises((vol.Invalid, HomeAssistantError)):
            await hass.services.async_call(DOMAIN, "update_curve", bad, blocking=True)
    assert CONF_CURVE_CONFIG not in entry.options


async def test_b21_update_curve_valid_calls_still_work(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hass.services.async_call(
        DOMAIN, "update_curve", {"entity_id": "sensor.hcl_curve_data", "mode": "preview", "points": CUSTOM_POINTS}, blocking=True
    )
    await hass.services.async_call(DOMAIN, "update_curve", {"entity_id": "sensor.hcl_curve_data", "mode": "revert"}, blocking=True)
    await hass.services.async_call(
        DOMAIN, "update_curve", {"entity_id": "sensor.hcl_curve_data", "mode": "save", "points": CUSTOM_POINTS}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_CURVE_CONFIG]["points"] == CUSTOM_POINTS


# ---------------------------------------------------------------- B-23
async def test_b23_repair_issue_removed_with_entry(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    issue_id = f"setup_curve_card_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


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
    assert not core(hass, entry)["override_manager"].is_overridden("light.ikea")


async def test_b14_yaml_mode_resources_do_not_break_setup(hass):
    from homeassistant.components.lovelace.resources import ResourceYAMLCollection

    collection = ResourceYAMLCollection([{"id": "1", "type": "module", "url": "/hcl_lighting_static/hcl-curve-card.js?v=0.4.1"}])
    hass.data["lovelace"] = MagicMock(resources=collection)
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    await _async_register_lovelace_resource(hass)  # must not raise


# ---------------------------------------------------------------- B-26
async def test_b26_mode_select_belongs_to_hcl_device(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    set_light(hass, "light.b", "off", **CT_ATTRS)
    entry1 = await setup_entry(hass, ["light.a"])
    ent_reg = er.async_get(hass)

    def entities(entry):
        return {e.domain: e for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)}

    e1 = entities(entry1)
    assert e1["select"].device_id is not None
    assert e1["select"].device_id == e1["switch"].device_id == e1["sensor"].device_id
    assert e1["select"].entity_id == "select.hcl_scenario"

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry2 = MockConfigEntry(domain=DOMAIN, title="Kitchen", data={"name": "Kitchen", "target": {"entity_id": ["light.b"]}})
    entry2.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry2.entry_id)
    await hass.async_block_till_done()
    e2 = entities(entry2)
    assert e2["select"].entity_id == "select.kitchen_scenario"
    assert e2["select"].device_id == e2["switch"].device_id
    # The curve sensor still finds its own mode select (used by the card).
    assert hass.states.get("sensor.kitchen_curve_data").attributes["mode_entity_id"] == "select.kitchen_scenario"


async def test_b26_existing_select_entity_id_is_kept(hass, no_frontend_registration):
    """Installations created before the fix keep their registered entity_id."""
    set_light(hass, "light.a", "off", **CT_ATTRS)
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain=DOMAIN, title="HCL", data={"name": "HCL", "target": {"entity_id": ["light.a"]}})
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "select", DOMAIN, f"{entry.entry_id}_mode", suggested_object_id="mode", config_entry=entry
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("select.mode") is not None
    assert hass.states.get("sensor.hcl_curve_data").attributes["mode_entity_id"] == "select.mode"


# ---------------------------------------------------------------- B-27
async def test_b27_new_entry_exposes_mode_entity_id_immediately(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await setup_entry(hass, ["light.a"])  # first setup: select not yet in the registry
    assert hass.states.get("sensor.hcl_curve_data").attributes["mode_entity_id"] == "select.hcl_scenario"


async def test_b27_renamed_mode_select_is_followed(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    er.async_get(hass).async_update_entity("select.hcl_scenario", new_entity_id="select.wohnzimmer_hcl")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.hcl_curve_data").attributes["mode_entity_id"] == "select.wohnzimmer_hcl"
