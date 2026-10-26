"""Browser tests of hcl-curve-card.js: draft and saving, changes from the server, missing, unavailable or changing entities, status line."""
from __future__ import annotations

import pytest

from card_support import POINTS, _hass, frames, _set_hass, _active_chips, _status, _set_points, _setpoint_hass, _ha_like, _until_hass, _show


async def test_b36_failed_save_keeps_the_draft_marked(page):
    await _set_hass(page, "auto")
    await page.evaluate("() => card.shadowRoot.getElementById('btn-add').click()")
    assert await page.evaluate("() => card._isDirty") is True
    await page.evaluate("() => { card._hass.callService = () => Promise.reject(new Error('points must have different times')); }")
    await page.evaluate("() => card._saveCurve()")
    assert await page.evaluate("() => card._isDirty") is True
    status = await _status(page)
    assert status["shown"] and status["error"] and "points must have different times" in status["text"]
    assert await page.evaluate("() => card.shadowRoot.getElementById('btn-save').classList.contains('dirty')")
    assert page.errors == []


async def test_b36_save_clears_the_mark_only_after_confirmation(page):
    await _set_hass(page, "auto")
    await page.evaluate("() => card.shadowRoot.getElementById('btn-add').click()")
    await page.evaluate("""() => { window.__resolve = null;
        card._hass.callService = () => new Promise(r => { window.__resolve = r; }); }""")
    await page.evaluate("() => { window.__saving = card._saveCurve(); }")
    assert await page.evaluate("() => card._isDirty") is True  # not confirmed yet
    await page.evaluate("async () => { window.__resolve(); await window.__saving; }")
    assert await page.evaluate("() => card._isDirty") is False
    assert (await _status(page))["shown"] is False
    assert page.errors == []


async def test_b36_active_preview_is_not_shown_as_saved(page):
    await _set_hass(page, "auto", extra={"preview_active": True})
    status = await _status(page)
    assert status["shown"] and not status["error"] and status["text"].startswith("Preview active")
    assert await page.evaluate("() => card.shadowRoot.getElementById('btn-save').classList.contains('dirty')")
    await _set_hass(page, "auto", extra={"preview_active": False})
    assert (await _status(page))["shown"] is False
    assert not await page.evaluate("() => card.shadowRoot.getElementById('btn-save').classList.contains('dirty')")
    assert page.errors == []


async def test_b40_server_update_does_not_overwrite_a_newer_draft(page):
    await _set_hass(page, "auto")
    await page.evaluate("() => { card._pushUndo(); card._points[0].b = 40; card._markChanged(); }")
    await page.evaluate("""() => { window.__res = null;
        card._hass.callService = () => new Promise(r => { window.__res = r; });
        window.__p = card._saveCurve(); }""")
    await page.evaluate("() => { card._pushUndo(); card._points[0].b = 55; card._markChanged(); }")
    saved = [dict(p) for p in POINTS]
    saved[0]["b"] = 40
    await _set_points(page, saved)  # the server reports the saved (older) curve
    await page.evaluate("async () => { window.__res(); await window.__p; }")
    assert await page.evaluate("() => card._points[0].b") == 55
    assert await page.evaluate("() => card._isDirty") is True
    assert await page.evaluate("() => card._undo.length") == 2
    assert "changed elsewhere" not in (await _status(page))["text"]  # own save, no conflict
    assert page.errors == []


async def test_b40_foreign_change_while_editing_is_offered_not_applied(page):
    await _set_hass(page, "auto")
    await page.evaluate("() => { card._points[2].b = 60; card._markChanged(); }")
    other = [dict(p) for p in POINTS]
    other[5]["b"] = 20  # another card saved something else
    await _set_points(page, other)
    assert await page.evaluate("() => card._points[2].b") == 60
    status = await _status(page)
    assert "changed elsewhere" in status["text"]
    await page.evaluate("() => card.shadowRoot.getElementById('btn-adopt').click()")
    assert await page.evaluate("() => [card._points[2].b, card._points[5].b, card._isDirty]") == [75, 20, False]
    await page.evaluate("() => card._undoLast()")  # the draft is not lost
    assert await page.evaluate("() => card._points[2].b") == 60


async def test_b40_clean_card_follows_foreign_changes(page):
    await _set_hass(page, "auto")
    other = [dict(p) for p in POINTS]
    other[5]["b"] = 20
    await _set_points(page, other)
    assert await page.evaluate("() => [card._points[5].b, card._isDirty]") == [20, False]


async def test_b40_failed_revert_keeps_the_draft(page):
    await _set_hass(page, "auto")
    await page.evaluate("() => { card._points[0].b = 44; card._markChanged(); window.confirm = () => true; }")
    await page.evaluate("() => { card._hass.callService = () => Promise.reject(new Error('offline')); }")
    await page.evaluate("() => card._revertCurve()")
    assert await page.evaluate("() => [card._points[0].b, card._isDirty]") == [44, True]
    assert "offline" in (await _status(page))["text"]
    await page.evaluate("() => { card._hass.callService = () => Promise.resolve(); }")
    await page.evaluate("() => card._revertCurve()")
    assert await page.evaluate("() => [card._points[0].b, card._isDirty]") == [30, False]


async def test_b44_missing_unavailable_or_invalid_entity_is_shown(page):
    await _set_hass(page, "auto")
    h = _hass("auto")
    del h["states"]["sensor.hcl_curve_data"]
    await page.evaluate("(h) => { h.callService = () => 0; card.hass = h; }", h)
    await frames(page)
    assert await page.evaluate("() => card.shadowRoot.querySelectorAll('.handle').length") == 0
    assert await page.evaluate("() => card.shadowRoot.getElementById('now-info').textContent") == ""
    assert "not found" in (await _status(page))["text"]
    h = _hass("auto")
    h["states"]["sensor.hcl_curve_data"] = {"state": "unavailable", "attributes": {}}
    await page.evaluate("(h) => { h.callService = () => 0; card.hass = h; }", h)
    await frames(page)
    assert "unavailable" in (await _status(page))["text"]
    h = _hass("auto", extra={"control_points": "bogus"})
    await page.evaluate("(h) => { h.callService = () => 0; card.hass = h; }", h)
    await frames(page)
    assert "not an HCL curve sensor" in (await _status(page))["text"]
    await _set_hass(page, "auto")  # data is back
    assert await page.evaluate("() => card.shadowRoot.querySelectorAll('#handles-b .handle').length") == len(POINTS)
    assert page.errors == []


async def test_b44_entity_change_resets_the_card(page):
    await _set_hass(page, "auto")
    await page.evaluate("() => { card._points[0].b = 1; card._markChanged(); card.setConfig({entity: 'sensor.other'}); }")
    await frames(page)
    assert await page.evaluate("() => [card._points.length, card._isDirty, card._undo.length]") == [0, False, 0]
    assert "sensor.other" in (await _status(page))["text"]


def _curve_state(state: str = "x", attributes: dict | None = None) -> dict:
    return {"state": state, "attributes": attributes if attributes is not None else {
        "control_points": POINTS, "mode_entity_id": "select.mode", "min_brightness": 10, "max_brightness": 100}}


async def _set_curve(page, curve: dict | None, mode: str = "auto") -> None:
    h = _hass(mode)
    if curve is None:
        del h["states"]["sensor.hcl_curve_data"]
    else:
        h["states"]["sensor.hcl_curve_data"] = curve
    await page.evaluate("(h) => { h.callService = () => 0; card.hass = h; }", h)
    await frames(page)


@pytest.mark.parametrize("gap", ["missing", "unavailable", "unknown", "invalid"])
@pytest.mark.parametrize("server_changed", [False, True])
async def test_b54_draft_survives_a_temporarily_missing_sensor(page, gap, server_changed):
    await _set_hass(page, "auto")
    await page.evaluate("() => { card._pushUndo(); card._points[0].b = 55; card._markChanged(); }")
    assert await page.evaluate("() => card._isDirty") is True
    gaps = {
        "missing": None,
        "unavailable": _curve_state("unavailable", {}),
        "unknown": _curve_state("unknown"),  # old attributes kept
        "invalid": _curve_state("x", {"control_points": "garbage"}),
    }
    await _set_curve(page, gaps[gap])
    assert await page.evaluate("() => card._dataState") != "ready"
    points = [dict(p) for p in POINTS]
    if server_changed:
        points[5]["b"] = 44
    await _set_points(page, points)
    assert await page.evaluate("() => card._dataState") == "ready"
    assert await page.evaluate("() => card._points[0].b") == 55
    assert await page.evaluate("() => card._isDirty") is True
    assert await page.evaluate("() => card._undo.length") == 1
    # a different server curve is offered, not adopted
    assert await page.evaluate("() => card._serverChanged") is server_changed
    assert await page.evaluate("() => card._points[5].b") == 50
    assert page.errors == []


@pytest.mark.parametrize("state", ["unavailable", "unknown"])
async def test_b56_unavailable_sensor_with_old_attributes_is_not_ready(page, state):
    await _set_hass(page, "auto")
    await _set_curve(page, _curve_state(state))
    assert await page.evaluate("() => card._dataState") == "unavailable"
    assert await page.evaluate("() => card.shadowRoot.querySelectorAll('.handle').length") == 0
    assert await page.evaluate("() => card.shadowRoot.getElementById('now-info').textContent") == ""
    assert (await _status(page))["text"]
    await _set_hass(page, "auto")
    assert await page.evaluate("() => card._dataState") == "ready"


async def test_rm_f03_foreign_state_changes_cost_no_dom_work(page):
    await _ha_like(page, _setpoint_hass("auto", "40", "3000"))
    await page.evaluate("() => record()")
    await page.evaluate("() => { for (let i = 0; i < 200; i++) next(); }")
    result = await page.evaluate("() => stop()")
    assert result == {"mutations": 0, "formats": 0}
    # the card still works with the latest hass (service calls)
    assert await page.evaluate("() => card._hass === window.h") is True
    assert page.errors == []


async def test_rm_f03_relevant_changes_still_arrive(page):
    await _ha_like(page, _setpoint_hass("auto", "40", "3000"))
    now = lambda: page.evaluate("() => card.shadowRoot.getElementById('now-info').textContent")  # noqa: E731
    assert "40 %" in await now()
    # setpoint sensor
    await page.evaluate("() => next({'sensor.tb': {state: '55', attributes: {}}})")
    assert "55 %" in await now()
    # mode select
    await page.evaluate("() => next({'select.mode': {state: 'focus', attributes: {}}})")
    assert await _active_chips(page) == ["focus"]
    # curve from the sensor
    await page.evaluate("""() => {
        const s = window.h.states['sensor.hcl_curve_data'];
        const pts = s.attributes.control_points.map(p => ({...p, b: 20}));
        next({'sensor.hcl_curve_data': {...s, attributes: {...s.attributes, control_points: pts}}});
    }""")
    assert await page.evaluate("() => card._points.every(p => p.b === 20)") is True
    # language and number format (new locale object)
    await page.evaluate("() => { const n = {...window.h, language: 'de', locale: {language: 'de', time_format: '24'}}; window.h = n; card.hass = n; }")
    assert await page.evaluate("() => card._lang") == "de"
    assert "Jetzt" in await now()
    # theme
    await page.evaluate("() => { const n = {...window.h, themes: {darkMode: true}}; window.h = n; card.hass = n; }")
    assert "true" in await page.evaluate("() => card._themeKey")
    # time zone
    await page.evaluate("() => { const n = {...window.h, config: {time_zone: 'Asia/Tokyo'}}; window.h = n; card.hass = n; }")
    assert await page.evaluate("() => card._timeZone") == "Asia/Tokyo"
    assert page.errors == []


async def test_rm_f03_sensor_appearing_later_is_picked_up(page):
    h = _hass("auto")
    sensor = h["states"].pop("sensor.hcl_curve_data")
    h["states"] = {}
    await _ha_like(page, h)
    assert await page.evaluate("() => card._dataState") == "loading"
    await page.evaluate("() => next()")  # states loaded, sensor still missing
    assert await page.evaluate("() => card._dataState") == "missing"
    await page.evaluate("(s) => next({'sensor.hcl_curve_data': s, 'select.mode': {state: 'auto', attributes: {}}})", sensor)
    assert await page.evaluate("() => card._dataState") == "ready"
    assert await page.evaluate("() => card.shadowRoot.querySelectorAll('#handles-b .handle').length") == len(POINTS)
    assert page.errors == []


async def test_rm_f03_curve_held_back_during_a_drag_arrives_afterwards(page):
    await _ha_like(page, _hass("auto"))
    await page.evaluate("""() => {
        card._drag = {fake: true};  // a point is under the finger
        const s = window.h.states['sensor.hcl_curve_data'];
        const pts = s.attributes.control_points.map(p => ({...p, b: 25}));
        next({'sensor.hcl_curve_data': {...s, attributes: {...s.attributes, control_points: pts}}});
    }""")
    assert await page.evaluate("() => card._points.every(p => p.b === 25)") is False
    # after the drag the next hass (only a foreign entity changed) delivers it
    await page.evaluate("() => { card._drag = null; next(); }")
    assert await page.evaluate("() => card._points.every(p => p.b === 25)") is True
    assert page.errors == []


async def test_rm_b29_status_line_reads_without_dots(page):
    await _show(page, _until_hass("night_light", 3, language="de"))
    parts = await page.evaluate("""() => {
        const el = card.shadowRoot.getElementById('now-info');
        return {shown: el.querySelector('[aria-hidden=true]').textContent, read: el.querySelector('.sr-only').textContent};
    }""")
    assert " · " in parts["shown"] and "·" not in parts["read"]
    assert parts["read"] == parts["shown"].replace(" · ", ", ")
    snap = await page.locator("hcl-curve-card").aria_snapshot()
    assert "Nachtlicht, bis" in snap and "· Nachtlicht" not in snap
    # draft line too
    await page.evaluate("() => { card._points.forEach(p => p.b = 5); card._markChanged(); }")
    draft = await page.evaluate("() => card.shadowRoot.querySelector('#draft-info .sr-only').textContent")
    assert draft.startswith("Entwurf") and "·" not in draft and ", " in draft
