"""Browser tests of hcl-curve-card.js: scenario chips, the "now" line with setpoints and environmental notes, the end of a timed scenario."""
from __future__ import annotations

import pytest

from card_support import _hass, frames, _set_hass, _active_chips, _points, _status, _setpoint_hass, _ha_like, _until_hass, _show


async def test_b12_mode_chips_follow_select_state(page):
    await _set_hass(page, "sleep")
    assert await _active_chips(page) == ["sleep"]
    await _set_hass(page, "auto")
    assert await _active_chips(page) == ["auto"]
    assert page.errors == []


async def test_rm_r12_no_chip_for_the_removed_scenario_guest(page):
    await _set_hass(page, "auto")
    chips = await page.evaluate("() => [...card.shadowRoot.querySelectorAll('.chip')].map(c => c.dataset.mode)")
    assert sorted(chips) == ["auto", "cleaning", "focus", "night_light", "relax", "sleep"]


async def test_b12_chip_click_still_calls_select_service(page):
    await _set_hass(page, "auto")
    await page.evaluate("() => card.shadowRoot.querySelector('.chip[data-mode=relax]').click()")
    calls = await page.evaluate("() => window.__calls")
    assert calls[-1] == ["select", "select_option", {"entity_id": "select.mode", "option": "relax"}]
    # 0.7.0 (B-43): the active chip follows the confirmed state of the select
    assert await _active_chips(page) == ["auto"]
    await _set_hass(page, "relax")
    assert await _active_chips(page) == ["relax"]


async def test_b19_active_scenario_line_is_drawn(page):
    await page.evaluate(
        """() => {
            window.__lines = [];
            const orig = card._drawOverrideLine.bind(card);
            card._drawOverrideLine = (chart, value, color) => { window.__lines.push([chart.canvas.id, value]); orig(chart, value, color); };
        }"""
    )
    await _set_hass(page, "focus")
    await page.evaluate("() => { card._chartB.update('none'); card._chartK.update('none'); }")
    lines = await page.evaluate("() => window.__lines")
    assert ["chartB", 100] in lines and ["chartK", 5500] in lines
    await page.evaluate("() => { window.__lines = []; }")
    await _set_hass(page, "auto")
    await page.evaluate("() => { card._chartB.update('none'); card._chartK.update('none'); }")
    assert await page.evaluate("() => window.__lines") == []
    assert page.errors == []


async def test_a07_scenario_line_uses_configured_values(page):
    await page.evaluate(
        """() => {
            window.__lines = [];
            const orig = card._drawOverrideLine.bind(card);
            card._drawOverrideLine = (chart, value, color) => { window.__lines.push([chart.canvas.id, value]); orig(chart, value, color); };
        }"""
    )
    await _set_hass(page, "focus", extra={"scenarios": {"focus": {"b": 80, "k": 5000}}})
    await page.evaluate("() => { card._chartB.update('none'); card._chartK.update('none'); }")
    lines = await page.evaluate("() => window.__lines")
    assert ["chartB", 80] in lines and ["chartK", 5000] in lines


async def test_b43_failed_mode_change_is_reported_and_not_shown_active(page):
    await _set_hass(page, "auto")
    await page.evaluate("""() => { card._hass.callService = () => Promise.reject(new Error('not allowed'));
        card.shadowRoot.querySelector('.chip[data-mode=focus]').click(); }""")
    await frames(page)
    assert await _active_chips(page) == ["auto"]
    assert await page.evaluate("() => card.shadowRoot.querySelector('.chip.pending')") is None
    status = await _status(page)
    assert status["error"] and "not allowed" in status["text"]
    assert page.errors == []


async def test_b45_curve_editable_in_every_mode_with_hint(page):
    await _set_hass(page, "relax")
    await page.evaluate("""() => card.shadowRoot.querySelector('#handles-b .handle-input[data-idx="1"]')
        .dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowUp', bubbles: true}))""")
    assert (await _points(page))[1][1] == 51
    assert await page.evaluate("() => card.shadowRoot.querySelector('.charts.disabled')") is None
    assert "applies in Auto" in (await _status(page))["text"]


async def test_b49_now_shows_the_active_setpoint(page):
    extra = {"scenarios": {"focus": {"b": 80, "k": 5000}},
             "target_brightness_entity_id": "sensor.tb", "target_color_temp_entity_id": "sensor.tk"}
    h = _hass("focus", extra=extra)
    h["states"]["sensor.tb"] = {"state": "80", "attributes": {}}
    h["states"]["sensor.tk"] = {"state": "5000", "attributes": {}}
    await page.evaluate("(h) => { h.callService = () => 0; card.hass = h; }", h)
    await frames(page)
    info = await page.evaluate("() => card.shadowRoot.getElementById('now-info').textContent")
    assert "Focus" in info and "80 %" in info and "5,000 K" in info
    # a draft is shown separately
    await _set_hass(page, "auto")
    await page.evaluate("() => { card._points.forEach(p => p.b = 5); card._markChanged(); }")
    assert (await page.evaluate("() => card.shadowRoot.getElementById('draft-info').textContent")).startswith("Draft")


async def test_k7_night_light_chip_and_clipped_effective_curve(page):
    # 0.7.0b9 (RM-R02): min/max only clip; an old scaling attribute is ignored
    await _set_hass(page, "night_light", extra={"min_brightness": 20, "max_brightness": 60, "brightness_scaling": True})
    assert await _active_chips(page) == ["night_light"]
    effective = await page.evaluate("() => card._chartB.data.datasets[1].data.find(p => p.x === 750).y")
    assert round(effective) == 50  # within min/max: the curve value, same as the integration
    clipped = await page.evaluate("() => card._chartB.data.datasets[1].data.find(p => p.x === 1320).y")
    assert round(clipped) == 20  # 10 % at 22:00 clipped to the minimum
    assert page.errors == []


async def _now_info(page, h) -> str:
    await page.evaluate("(h) => { h.callService = () => 0; card.hass = h; }", h)
    await frames(page)
    return await page.evaluate("() => card.shadowRoot.getElementById('now-info').textContent")


@pytest.mark.parametrize("mode", ["focus", "night_light", "auto"])
@pytest.mark.parametrize("value", ["unknown", "unavailable"])
async def test_b57_unavailable_setpoint_sensors_show_no_substitute_values(page, mode, value):
    info = await _now_info(page, _setpoint_hass(mode, value, value))
    assert "%" not in info and " K" not in info
    assert "not available" in info


async def test_b57_one_unavailable_setpoint_sensor_is_enough(page):
    info = await _now_info(page, _setpoint_hass("focus", "80", "unavailable"))
    assert "%" not in info and "not available" in info


@pytest.mark.parametrize("mode,expected", [("focus", ["80 %", "5,000 K"]), ("night_light", ["3 %", "2,200 K"])])
async def test_b57_fallback_without_setpoint_sensors_uses_the_scenario(page, mode, expected):
    # sensors disabled (not in the states) or older integration without references
    for h in (_setpoint_hass(mode, None, None), _hass(mode, extra={"scenarios": {"focus": {"b": 80, "k": 5000},
                                                                                  "night_light": {"b": 3, "k": 2200}}})):
        info = await _now_info(page, h)
        for text in expected:
            assert text in info, info


async def test_b57_fallback_in_auto_uses_the_curve(page):
    info = await _now_info(page, _setpoint_hass("auto", None, None))
    assert "%" in info and "K" in info and "not available" not in info


async def _expected_clock(page) -> str:
    return await page.evaluate("() => card._fmt.clock(card._nowMinutes(new Date(card._modeUntil)))")


async def test_rm_f04_end_of_the_scenario_within_a_day(page):
    info = await _show(page, _until_hass("night_light", 3))
    assert f"Night light · until {await _expected_clock(page)} · 3 %" in info
    info = await _show(page, _until_hass("night_light", 3, language="de"))
    assert f"Nachtlicht · bis {await _expected_clock(page)} · 3 %" in info
    assert page.errors == []


async def test_rm_f04_end_more_than_a_day_ahead_shows_the_date(page):
    info = await _show(page, _until_hass("focus", 30, language="de"))
    clock = await _expected_clock(page)
    date = await page.evaluate(
        "() => new Intl.DateTimeFormat('de', {timeZone: 'Europe/Berlin', day: 'numeric', month: 'numeric'})"
        ".format(new Date(card._modeUntil))"
    )
    assert f"Fokus · bis {date} {clock} · " in info


@pytest.mark.parametrize("mode,hours", [("night_light", None), ("auto", 3), ("night_light", -1)])
async def test_rm_f04_no_end_shown(page, mode, hours):
    """No end (duration 0), Auto, or an end that has just passed."""
    info = await _show(page, _until_hass(mode, hours))
    assert "until" not in info


async def test_rm_f04_new_end_with_the_same_scenario_arrives(page):
    await _show(page, _until_hass("night_light", None))
    await _ha_like(page, await page.evaluate("() => window.h"))
    now = lambda: page.evaluate("() => card.shadowRoot.getElementById('now-info').textContent")  # noqa: E731
    assert "until" not in await now()
    await page.evaluate(
        "() => next({'select.mode': {state: 'night_light', attributes: {until: new Date(Date.now() + 2 * 3600e3).toISOString()}}})"
    )
    assert f"until {await _expected_clock(page)}" in await now()
    await page.evaluate("() => next({'select.mode': {state: 'night_light', attributes: {until: null}}})")
    assert "until" not in await now()
    # foreign changes still cost no DOM work (RM-F03)
    await page.evaluate("() => record()")
    await page.evaluate("() => { for (let i = 0; i < 100; i++) next(); }")
    assert await page.evaluate("() => stop()") == {"mutations": 0, "formats": 0}
    assert page.errors == []


async def test_rm_b25_end_a_full_day_ahead_shows_the_date(page):
    await page.evaluate("(h) => { h.callService = () => 0; card.hass = h; }", _until_hass("night_light", None, language="de"))
    now = await page.evaluate("() => Date.parse('2026-10-03T18:27:00Z')")
    # duration 1440: the end is set on the server a moment before the card renders
    day = await page.evaluate(f"() => card._untilText({now} + 1440 * 60000 - 2000, {now})")
    assert day.startswith("bis ") and "." in day.split(" ")[1]  # with the date
    before = await page.evaluate(f"() => card._untilText({now} + 1440 * 60000 - 61000, {now})")
    assert before.count(":") == 1 and "." not in before  # time only (reads as tomorrow)


def _environment_hass(base: str, value: str, status: str, reason: str) -> dict:
    h = _setpoint_hass("auto", value, "4000")
    h["states"]["sensor.tb"]["attributes"] = {
        "base_value": float(base), "environment_status": status, "environment_reason": reason,
    }
    return h


async def test_rm_e01_now_shows_base_and_effective_with_the_reason(page):
    info = await _now_info(page, _environment_hass("80", "35", "active", "daylight_reducing"))
    assert "80 % → 35 %" in info and "daylight" in info, info
    info = await _now_info(page, _environment_hass("80", "35", "hold", "daylight_hold_manual_control"))
    assert "80 % → 35 %" in info and "daylight held" in info, info
    info = await _now_info(page, _environment_hass("80", "60", "fallback", "daylight_sensor_fallback"))
    assert "daylight sensor without value" in info, info


async def test_rm_e01_no_note_when_the_effective_value_is_the_base(page):
    info = await _now_info(page, _environment_hass("80", "80", "active", "daylight_within_deadband"))
    assert "→" not in info and "daylight" not in info and "80 %" in info, info


async def test_rm_e01_older_backend_without_environment_attributes(page):
    info = await _now_info(page, _setpoint_hass("auto", "55", "4000"))
    assert "55 %" in info and "→" not in info and "daylight" not in info, info
