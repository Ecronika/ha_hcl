"""Browser tests of hcl-curve-card.js: wake and sleep time as entities (RM-E05, E05-T19)."""
from __future__ import annotations

from card_support import DEFAULT_POINTS, POINTS, _hass, _points, _set_hass, frames

# Default curve of the integration for 06:00 / 23:00 (default_points)
DEFAULT_POINTS_0600_2300 = [
    {"t": 360, "k": 3000, "b": 30}, {"t": 380, "k": 4500, "b": 90}, {"t": 420, "k": 5000, "b": 100},
    {"t": 660, "k": 6000, "b": 100}, {"t": 1140, "k": 5000, "b": 100}, {"t": 1200, "k": 5000, "b": 100},
    {"t": 1380, "k": 2200, "b": 10}, {"t": 1395, "k": 2200, "b": 5}, {"t": 359, "k": 2200, "b": 5},
]
TIMES = {"wake_time": "07:00", "sleep_time": "22:00"}
LATER = {"wake_time": "06:00", "sleep_time": "23:00", "default_points": DEFAULT_POINTS_0600_2300}


async def _anchor_text(page) -> str:
    return await page.evaluate("() => card.shadowRoot.getElementById('anchor-info').textContent")


async def _update(page, extra: dict) -> None:
    """New sensor attributes; calls are recorded as before."""
    await page.evaluate(
        "(h) => { h.callService = card._hass.callService; card.hass = h; }", _hass("auto", extra=extra)
    )
    await frames(page)


async def test_e05_t19_card_shows_the_times(page):
    await _set_hass(page, "auto", extra=TIMES)
    assert await _anchor_text(page) == "Wake 07:00 · Sleep 22:00"
    await _set_hass(page, "auto", language="de", extra=TIMES)
    assert await _anchor_text(page) == "Aufwachen 07:00 · Schlafen 22:00"
    # format of the user profile
    h = _hass("auto", extra=TIMES)
    h["locale"]["time_format"] = "12"
    await page.evaluate("(h) => { h.callService = () => 0; card.hass = h; }", h)
    await frames(page)
    assert await _anchor_text(page) == "Wake 7:00 AM · Sleep 10:00 PM"
    # only shown: no field for the times (the time input is the point editor)
    assert await page.evaluate("() => card.shadowRoot.querySelectorAll('input[type=time]').length") == 1
    # an older integration without the attributes: no line
    await _set_hass(page, "auto")
    assert await _anchor_text(page) == ""
    assert page.errors == []


async def test_e05_t19_night_window_and_default_curve_follow_a_change(page):
    await _set_hass(page, "auto", extra=TIMES)
    await _update(page, LATER)
    assert await _anchor_text(page) == "Wake 06:00 · Sleep 23:00"
    assert await page.evaluate("() => [card._valSettings.nightStart, card._valSettings.nightEnd]") == [1380, 360]
    await page.evaluate("() => card._loadDefaultCurve()")
    assert await _points(page) == sorted([p["t"], p["b"], p["k"]] for p in DEFAULT_POINTS_0600_2300)
    # saving the loaded default curve sends exactly its points (the server
    # then stores no own curve, E05-PRD-20)
    await page.evaluate("() => card._saveCurve()")
    data = (await page.evaluate("() => window.__calls"))[-1][2]
    assert data["mode"] == "save"
    assert data["points"] == sorted(DEFAULT_POINTS_0600_2300, key=lambda p: p["t"])
    assert page.errors == []


async def test_e05_t19_draft_and_preview_survive_a_time_change(page):
    await _set_hass(page, "auto", extra={**TIMES, "default_points": DEFAULT_POINTS})
    await page.evaluate("() => { card._pushUndo(); card._points[0].b = 40; card._markChanged(); }")
    await page.evaluate("() => card._testCurve()")
    preview = [dict(p) for p in POINTS]
    preview[0]["b"] = 40
    await _update(page, {**TIMES, "control_points": preview, "preview_active": True})
    draft = await _points(page)
    # the time changes, the preview (active curve) stays
    await _update(page, {**LATER, "control_points": preview, "preview_active": True})
    assert await _points(page) == draft
    assert await page.evaluate("() => card._undo.length") == 1
    # still shown as not saved (active preview)
    assert await page.evaluate("() => card.shadowRoot.getElementById('btn-save').classList.contains('dirty')")
    # a time change during a drag: the points under the finger stay
    await page.evaluate("() => { card._drag = {index: 1}; }")
    await _update(page, {**TIMES, "control_points": POINTS, "preview_active": False})
    assert await _points(page) == draft
    await page.evaluate("() => { card._drag = null; }")
    # saving afterwards sends the visible points
    await page.evaluate("() => card._saveCurve()")
    data = (await page.evaluate("() => window.__calls"))[-1][2]
    assert data["mode"] == "save" and [[p["t"], p["b"], p["k"]] for p in data["points"]] == draft
    assert page.errors == []
