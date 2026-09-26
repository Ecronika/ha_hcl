"""Browser tests for hcl-curve-card.js (headless Chromium via Playwright).

Run separately from the Home Assistant tests:  pytest tests_frontend
Uses the Chromium given in env HCL_TEST_CHROMIUM (default /opt/pw-browsers/chromium)
or, if that path does not exist, the Chromium installed by `playwright install chromium`.
Skipped automatically when Playwright or Chromium is not available, unless
HCL_TEST_REQUIRE_BROWSER=1 is set (CI), then a missing browser is an error.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

if os.environ.get("HCL_TEST_REQUIRE_BROWSER") == "1":
    import playwright.async_api as playwright_api
else:
    playwright_api = pytest.importorskip("playwright.async_api")

FRONTEND = Path(__file__).parents[1] / "custom_components" / "hcl_lighting" / "frontend"
CHROMIUM = os.environ.get("HCL_TEST_CHROMIUM", "/opt/pw-browsers/chromium")

POINTS = [
    {"t": 420, "k": 2700, "b": 30}, {"t": 540, "k": 4500, "b": 50}, {"t": 570, "k": 5500, "b": 75},
    {"t": 600, "k": 6500, "b": 100}, {"t": 720, "k": 6500, "b": 100}, {"t": 750, "k": 4000, "b": 50},
    {"t": 780, "k": 4000, "b": 50}, {"t": 810, "k": 6000, "b": 75}, {"t": 840, "k": 6000, "b": 75},
    {"t": 960, "k": 4000, "b": 50}, {"t": 1080, "k": 2700, "b": 30}, {"t": 1320, "k": 2200, "b": 10},
]


def _hass(
    mode: str, language: str = "en", dark: bool = False, extra: dict | None = None,
    time_zone: str | None = None,
) -> dict:
    return {
        "config": {"time_zone": time_zone} if time_zone else {},
        "language": language,
        "locale": {"language": language, "time_format": "24"},
        "themes": {"darkMode": dark},
        "states": {
            "sensor.hcl_curve_data": {
                "state": "x",
                "attributes": {
                    "control_points": POINTS,
                    "mode_entity_id": "select.mode",
                    "min_brightness": 10,
                    "max_brightness": 100,
                    **(extra or {}),
                },
            },
            "select.mode": {"state": mode, "attributes": {}},
        }
    }


@pytest.fixture
async def page():
    async with playwright_api.async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(
                executable_path=CHROMIUM if Path(CHROMIUM).exists() else None
            )
        except Exception as err:  # noqa: BLE001 - no browser installed
            if os.environ.get("HCL_TEST_REQUIRE_BROWSER") == "1":
                raise
            pytest.skip(f"Chromium not available: {err}")
        pg = await browser.new_page(viewport={"width": 900, "height": 900})
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        await pg.set_content("<html><body></body></html>")
        await pg.add_script_tag(content=(FRONTEND / "chart.js").read_text(encoding="utf-8"))
        # The card is a JavaScript module (Lovelace resource type "module")
        await pg.add_script_tag(content=(FRONTEND / "hcl-curve-card.js").read_text(encoding="utf-8"), type="module")
        await pg.wait_for_function("() => !!customElements.get('hcl-curve-card')")
        await pg.evaluate(
            """() => {
                window.__calls = [];
                window.card = document.createElement('hcl-curve-card');
                card.setConfig({entity: 'sensor.hcl_curve_data'});
                document.body.appendChild(card);
            }"""
        )
        await pg.wait_for_timeout(300)
        pg.errors = errors
        yield pg
        await browser.close()


async def _set_hass(page, mode: str, **kwargs) -> None:
    await page.evaluate(
        "(h) => { h.callService = (...a) => window.__calls.push(a); card.hass = h; }",
        _hass(mode, **kwargs),
    )
    await page.wait_for_timeout(200)


async def _active_chips(page) -> list[str]:
    return await page.evaluate("() => [...card.shadowRoot.querySelectorAll('.chip.active')].map(c => c.dataset.mode)")


async def test_b12_mode_chips_follow_select_state(page):
    await _set_hass(page, "sleep")
    assert await _active_chips(page) == ["sleep"]
    await _set_hass(page, "auto")
    assert await _active_chips(page) == ["auto"]
    assert page.errors == []


async def test_b12_chip_click_still_calls_select_service(page):
    await _set_hass(page, "auto")
    await page.evaluate("() => card.shadowRoot.querySelector('.chip[data-mode=relax]').click()")
    calls = await page.evaluate("() => window.__calls")
    assert calls[-1] == ["select", "select_option", {"entity_id": "select.mode", "option": "relax"}]
    # 0.7.0 (B-43): the active chip follows the confirmed state of the select
    assert await _active_chips(page) == ["auto"]
    await _set_hass(page, "relax")
    assert await _active_chips(page) == ["relax"]


async def test_b18_card_styles_are_applied(page):
    """The :host rule is parsed (theme-based variables resolve on the card)."""
    b_color = await page.evaluate("() => getComputedStyle(card).getPropertyValue('--hcl-b-color').trim()")
    assert b_color.lower() == "#ffb300"  # fallback without HA theme


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
    await _set_hass(page, "guest")
    await page.evaluate("() => { card._chartB.update('none'); card._chartK.update('none'); }")
    assert await page.evaluate("() => window.__lines") == []
    assert page.errors == []


async def test_editor_basics_unchanged(page):
    """Existing behaviour: handles rendered for all points, no JS errors."""
    await _set_hass(page, "auto")
    n = await page.evaluate("() => card.shadowRoot.querySelectorAll('#handles-b .handle').length")
    assert n == len(POINTS)
    assert page.errors == []


async def _points(page):
    return await page.evaluate("() => card._points.map(p => [p.t, p.b, p.k])")


async def test_a09_german_texts(page):
    await _set_hass(page, "sleep", language="de")
    texts = await page.evaluate("""() => ({
        title: card.shadowRoot.querySelector('.title').textContent,
        chip: card.shadowRoot.querySelector('.chip[data-mode=sleep] span').textContent,
        save: card.shadowRoot.getElementById('btn-save').textContent,
        now: card.shadowRoot.getElementById('now-info').textContent,
    })""")
    assert texts["title"] == "HCL-Konfigurator"
    assert texts["chip"] == "Schlafen"
    assert texts["save"] == "Speichern"
    assert texts["now"].startswith("Jetzt ")
    await _set_hass(page, "sleep", language="en")
    assert await page.evaluate("() => card.shadowRoot.querySelector('.title').textContent") == "HCL Configurator"
    assert page.errors == []


async def test_a09_chart_colours_follow_theme(page):
    await _set_hass(page, "auto")
    await page.evaluate("() => { card.style.setProperty('--divider-color', 'rgb(1, 2, 3)'); card.style.setProperty('--primary-text-color', 'rgb(4, 5, 6)'); }")
    await _set_hass(page, "auto", dark=True)  # theme change
    await page.wait_for_timeout(100)
    grid, ticks = await page.evaluate("() => [card._chartB.options.scales.y.grid.color, card._chartK.options.scales.y.ticks.color]")
    assert grid == "rgb(1, 2, 3)" and ticks == "rgb(4, 5, 6)"
    assert page.errors == []


async def test_a08_add_delete_undo(page):
    await _set_hass(page, "auto")
    before = await _points(page)
    await page.evaluate("() => card.shadowRoot.getElementById('btn-add').click()")
    after_add = await _points(page)
    assert len(after_add) == len(before) + 1
    assert [p[0] for p in after_add] == sorted(p[0] for p in after_add)
    assert await page.evaluate("() => card.shadowRoot.querySelectorAll('#handles-b .handle').length") == len(after_add)
    assert await page.evaluate("() => card._isDirty") is True
    # delete the selected (new) point, then undo twice
    await page.evaluate("() => card.shadowRoot.getElementById('btn-delete').click()")
    assert await _points(page) == before
    await page.evaluate("() => card.shadowRoot.getElementById('btn-undo').click()")
    assert await _points(page) == after_add
    await page.evaluate("() => card.dispatchEvent(new KeyboardEvent('keydown', {key: 'z', ctrlKey: true}))")
    assert await _points(page) == before
    assert await page.evaluate("() => card._isDirty") is False
    assert page.errors == []


async def test_a08_double_click_adds_point_at_time(page):
    await _set_hass(page, "auto")
    await page.evaluate("""() => {
        const c = card._chartB; const r = c.canvas.getBoundingClientRect();
        const x = r.left + c.scales.x.getPixelForValue(1200);
        c.canvas.dispatchEvent(new MouseEvent('dblclick', {clientX: x, clientY: r.top + 20, bubbles: true}));
    }""")
    assert 1200 in [p[0] for p in await _points(page)]
    assert page.errors == []


async def test_a08_keyboard_keeps_order_and_minimum_points(page):
    await _set_hass(page, "auto")
    # point 1 (09:00) cannot pass point 2 (09:30)
    for _ in range(5):
        await page.evaluate("""() => card.shadowRoot.querySelector('#handles-b .handle[data-idx="1"]')
            .dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true}))""")
    pts = await _points(page)
    assert pts[1][0] == 555 and pts[1][0] < pts[2][0]
    # delete down to two points; the last two cannot be deleted
    for _ in range(20):
        await page.evaluate("""() => { const h = card.shadowRoot.querySelector('#handles-b .handle[data-idx="0"]');
            h && h.dispatchEvent(new KeyboardEvent('keydown', {key: 'Delete', bubbles: true})); }""")
    assert len(await _points(page)) == 2
    assert page.errors == []


async def test_a08_numeric_editor(page):
    await _set_hass(page, "auto")
    await page.evaluate("() => card._select(4)")  # 12:00
    await page.evaluate("""() => {
        const $ = (id) => card.shadowRoot.getElementById(id);
        $('in-t').value = '13:50'; $('in-b').value = '120'; $('in-k').value = '5000';
        $('in-k').dispatchEvent(new Event('change'));
    }""")
    pt = (await _points(page))[4]
    # time clamped to the next point (12:30) minus 15 min, brightness clamped to 100
    assert pt == [735, 100, 5000]
    assert page.errors == []


async def test_a08_now_marker_and_limits(page):
    await _set_hass(page, "auto", extra={"max_brightness": 60})
    info = await page.evaluate("() => card.shadowRoot.getElementById('now-info').textContent")
    assert info.startswith("Now ") and "%" in info and "K" in info
    dashed = await page.evaluate("() => card._chartB.data.datasets[1].data.length")
    assert dashed == 97  # effective (limited) brightness drawn
    assert await page.evaluate("() => Math.max(...card._chartB.data.datasets[1].data.map(p => p.y))") == 60
    await _set_hass(page, "auto", extra={"max_brightness": 100})
    await page.evaluate("() => card._updateVisuals()")
    assert await page.evaluate("() => card._chartB.data.datasets[1].data.length") == 0


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


# ---------------------------------------------------------------- 0.6.1
async def _status(page):
    return await page.evaluate("""() => { const s = card.shadowRoot.getElementById('status');
        return {text: s.textContent, shown: s.textContent.trim() !== '', error: s.classList.contains('error')}; }""")


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


async def test_b38_now_uses_the_home_assistant_time_zone(page):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    for zone in ("Pacific/Kiritimati", "Pacific/Pago_Pago"):  # UTC+14 / UTC-11
        await _set_hass(page, "auto", time_zone=zone)
        got = await page.evaluate("() => card._nowMinutes()")
        now = datetime.now(ZoneInfo(zone))
        expected = now.hour * 60 + now.minute
        assert min(abs(got - expected), 1440 - abs(got - expected)) <= 1, zone
        info = await page.evaluate("() => card.shadowRoot.getElementById('now-info').textContent")
        assert f"{got // 60:02d}:{got % 60:02d}" in info
    assert page.errors == []


async def _night_warnings(page):
    return await page.evaluate("""() => card._validationResult.warnings
        .filter(w => w.type === 'night').map(w => [w.xMin, w.xMax])""")


async def test_b30_night_window_follows_sleep_and_wake_time(page):
    # night shift: active 22:00–05:00, sleeping 08:00–16:00
    shift = [
        {"t": 60, "b": 100, "k": 6500}, {"t": 300, "b": 100, "k": 6500},
        {"t": 480, "b": 5, "k": 2200}, {"t": 960, "b": 5, "k": 2200},
        {"t": 1320, "b": 100, "k": 6500},
    ]
    await _set_hass(page, "auto", extra={"sleep_time": "08:00", "wake_time": "16:00"})
    assert await page.evaluate("() => [card._valSettings.nightStart, card._valSettings.nightEnd]") == [480, 960]
    await page.evaluate("(pts) => { card._points = pts; card._markChanged(true); }", shift)
    assert await _night_warnings(page) == []
    # with the usual anchors (22:00–07:00) the same curve is flagged
    await _set_hass(page, "auto", extra={"sleep_time": "22:00", "wake_time": "07:00"})
    await page.evaluate("(pts) => { card._points = pts; card._markChanged(true); }", shift)
    assert await _night_warnings(page)
    assert page.errors == []


async def test_b24_default_preset_equals_the_backend_default_curve(page):
    preset = await page.evaluate("() => card._presets.default.map(p => [p.t, p.b, p.k])")
    assert preset == [[p["t"], p["b"], p["k"]] for p in POINTS]


# ---------------------------------------------------------------- 0.7.0 (frontend review cdcc389)
async def _set_points(page, points, **kwargs):
    await page.evaluate(
        "(h) => { h.callService = card._hass.callService; card.hass = h; }",
        _hass("auto", extra={"control_points": points, **kwargs.pop("extra", {})}, **kwargs),
    )
    await page.wait_for_timeout(100)


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


async def test_b41_midnight_24_00_is_the_same_as_00_00(page):
    got = await page.evaluate("""() => {
        const { normalize: hclNormalize, valueAt: hclValueAt } = customElements.get('hcl-curve-card').curve;
        const pts = hclNormalize([{t: 0, b: 10, k: 2200}, {t: 720, b: 50, k: 4000}, {t: 1440, b: 90, k: 6500}]);
        const owl = hclNormalize([{t: 540, b: 20, k: 2700}, {t: 1200, b: 21, k: 2700}, {t: 1440, b: 5, k: 2200}]);
        return [pts.map(p => p.t), hclValueAt(pts, 0).b, owl.map(p => p.t), hclValueAt(owl, 0).b]; }""")
    assert got == [[0, 720], 10, [0, 540, 1200], 5]
    presets = await page.evaluate("() => Object.values(card._presets).every(p => p.every(x => x.t < 1440))")
    assert presets


async def test_b42_invalid_inputs_change_nothing(page):
    await _set_hass(page, "auto")
    await page.evaluate("() => card._select(2)")
    before = await _points(page)
    for field, value in (("in-t", ""), ("in-t", "7:"), ("in-b", ""), ("in-k", "abc")):
        await page.evaluate("""([f, v]) => { const $ = (id) => card.shadowRoot.getElementById(id);
            card._updateEditor(); $(f).value = v; $(f).dispatchEvent(new Event('change')); }""", [field, value])
        assert await _points(page) == before, field
    assert await page.evaluate("() => card._undo.length") == 0
    assert (await _status(page))["error"] is True
    assert page.errors == []


async def test_b43_failed_mode_change_is_reported_and_not_shown_active(page):
    await _set_hass(page, "auto")
    await page.evaluate("""() => { card._hass.callService = () => Promise.reject(new Error('not allowed'));
        card.shadowRoot.querySelector('.chip[data-mode=focus]').click(); }""")
    await page.wait_for_timeout(100)
    assert await _active_chips(page) == ["auto"]
    assert await page.evaluate("() => card.shadowRoot.querySelector('.chip.pending')") is None
    status = await _status(page)
    assert status["error"] and "not allowed" in status["text"]
    assert page.errors == []


async def test_b44_missing_unavailable_or_invalid_entity_is_shown(page):
    await _set_hass(page, "auto")
    h = _hass("auto")
    del h["states"]["sensor.hcl_curve_data"]
    await page.evaluate("(h) => { h.callService = () => 0; card.hass = h; }", h)
    await page.wait_for_timeout(100)
    assert await page.evaluate("() => card.shadowRoot.querySelectorAll('.handle').length") == 0
    assert await page.evaluate("() => card.shadowRoot.getElementById('now-info').textContent") == ""
    assert "not found" in (await _status(page))["text"]
    h = _hass("auto")
    h["states"]["sensor.hcl_curve_data"] = {"state": "unavailable", "attributes": {}}
    await page.evaluate("(h) => { h.callService = () => 0; card.hass = h; }", h)
    await page.wait_for_timeout(100)
    assert "unavailable" in (await _status(page))["text"]
    h = _hass("auto", extra={"control_points": "bogus"})
    await page.evaluate("(h) => { h.callService = () => 0; card.hass = h; }", h)
    await page.wait_for_timeout(100)
    assert "not an HCL curve sensor" in (await _status(page))["text"]
    await _set_hass(page, "auto")  # data is back
    assert await page.evaluate("() => card.shadowRoot.querySelectorAll('#handles-b .handle').length") == len(POINTS)
    assert page.errors == []


async def test_b44_entity_change_resets_the_card(page):
    await _set_hass(page, "auto")
    await page.evaluate("() => { card._points[0].b = 1; card._markChanged(); card.setConfig({entity: 'sensor.other'}); }")
    await page.wait_for_timeout(100)
    assert await page.evaluate("() => [card._points.length, card._isDirty, card._undo.length]") == [0, False, 0]
    assert "sensor.other" in (await _status(page))["text"]


async def test_b45_curve_editable_in_every_mode_with_hint(page):
    await _set_hass(page, "guest")
    await page.evaluate("""() => card.shadowRoot.querySelector('#handles-b .handle[data-idx="1"]')
        .dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowUp', bubbles: true}))""")
    assert (await _points(page))[1][1] == 51
    assert await page.evaluate("() => card.shadowRoot.querySelector('.charts.disabled')") is None
    assert "applies in Auto" in (await _status(page))["text"]


async def test_b46_cancelled_drag_ends_cleanly(page):
    await _set_hass(page, "auto")
    original = await page.evaluate("() => card._points[3].b")
    await page.evaluate("""() => { const h = card.shadowRoot.querySelector('#handles-b .handle[data-idx="3"]');
        h.setPointerCapture = () => {};  // synthetic pointer: capture would throw
        const r = h.getBoundingClientRect();
        h.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, composed: true, pointerId: 7, clientX: r.x + 5, clientY: r.y + 5}));
        h.dispatchEvent(new PointerEvent('pointermove', {bubbles: true, composed: true, pointerId: 7, clientX: r.x + 5, clientY: r.y + 40}));
        h.dispatchEvent(new PointerEvent('pointercancel', {bubbles: true, composed: true, pointerId: 7})); }""")
    moved = await page.evaluate("() => card._points[3].b")
    assert moved != original  # the drag really started
    # listeners are gone: further moves change nothing
    await page.evaluate("() => window.dispatchEvent(new PointerEvent('pointermove', {pointerId: 7, clientX: 10, clientY: 10}))")
    assert await page.evaluate("() => card._points[3].b") == moved
    # server updates are processed again
    other = [dict(p) for p in POINTS]
    other[0]["b"] = 33
    await page.evaluate("() => card._undoLast()")
    await _set_points(page, other)
    assert await page.evaluate("() => card._points[0].b") == 33


async def test_b47_narrow_cards_do_not_cut_off_content(page):
    for width in (240, 288):
        await page.evaluate("(w) => { card.style.display = 'block'; card.style.width = w + 'px'; }", width)
        await _set_hass(page, "auto")
        await page.wait_for_timeout(200)
        right = await page.evaluate("""() => { const host = card.getBoundingClientRect(); let maxR = 0;
            card.shadowRoot.querySelectorAll('ha-card *').forEach(e => { const r = e.getBoundingClientRect();
              if (r.width && !e.classList.contains('handle') && !e.closest('.handle')) maxR = Math.max(maxR, r.right); });
            return [host.width, Math.round(maxR - host.left)]; }""")
        assert right[1] <= right[0], (width, right)


async def test_b48_each_chart_has_its_own_time_axis(page):
    await _set_hass(page, "auto")
    axes = await page.evaluate("""() => [card._chartB, card._chartK].map(c =>
        [c.options.scales.x.display, c.scales.x.ticks.map(t => t.label).filter(Boolean)])""")
    for display, labels in axes:
        assert display is True
        assert labels == ["00:00", "06:00", "12:00", "18:00", "24:00"]
    assert await page.evaluate("() => card.shadowRoot.querySelector('.axis-labels')") is None


async def test_b49_now_shows_the_active_setpoint(page):
    extra = {"scenarios": {"focus": {"b": 80, "k": 5000}},
             "target_brightness_entity_id": "sensor.tb", "target_color_temp_entity_id": "sensor.tk"}
    h = _hass("focus", extra=extra)
    h["states"]["sensor.tb"] = {"state": "80", "attributes": {}}
    h["states"]["sensor.tk"] = {"state": "5000", "attributes": {}}
    await page.evaluate("(h) => { h.callService = () => 0; card.hass = h; }", h)
    await page.wait_for_timeout(150)
    info = await page.evaluate("() => card.shadowRoot.getElementById('now-info').textContent")
    assert "Focus" in info and "80 %" in info and "5,000 K" in info
    await _set_hass(page, "guest", extra=extra)
    assert "HCL sends no values" in await page.evaluate("() => card.shadowRoot.getElementById('now-info').textContent")
    # a draft is shown separately
    await _set_hass(page, "auto")
    await page.evaluate("() => { card._points.forEach(p => p.b = 5); card._markChanged(); }")
    assert (await page.evaluate("() => card.shadowRoot.getElementById('draft-info').textContent")).startswith("Draft")


async def test_b50_night_warning_times_are_valid_clock_times(page):
    await _set_hass(page, "auto", extra={"sleep_time": "22:00", "wake_time": "07:00"})
    msgs = await page.evaluate("() => card._validationResult.warnings.filter(w => w.type === 'night').map(w => w.msg)")
    assert len(msgs) == 1 and "24:" not in msgs[0] and "22:15–07:00" in msgs[0]
    await page.evaluate("() => card._applyPreset('default_night')")
    assert await _night_warnings(page) == []


async def test_b51_foreign_chart_js_is_not_used(browser_page_factory):
    page, requests = await browser_page_factory(foreign_chart=True)
    assert await page.evaluate("() => card._Chart && card._Chart.version") == "4.5.1"
    assert await page.evaluate("() => window.Chart.version") == "2.9.4"  # restored for the other card
    assert any("/hcl_lighting_static/chart.js?v=9.9.9" in r for r in requests)
    assert page.errors == []


async def test_b53_card_removed_while_loading_does_not_initialise(browser_page_factory):
    page, _requests = await browser_page_factory(foreign_chart=False, delay_chart=True, attach=False)
    await page.evaluate("""() => { window.card = document.createElement('hcl-curve-card');
        card.setConfig({entity: 'sensor.hcl_curve_data'}); document.body.appendChild(card); card.remove(); }""")
    await page.wait_for_timeout(1500)
    assert await page.evaluate("() => [card._initialized, card._chartB, card._nowTimer]") == [False, None, None]
    await page.evaluate("() => document.body.appendChild(card)")
    await page.wait_for_timeout(500)
    assert await page.evaluate("() => card._initialized && !!card._chartB") is True
    assert page.errors == []


async def test_k5_semantics_keyboard_and_formats(page):
    h = _hass("relax")
    h["locale"] = {"language": "en", "time_format": "12", "number_format": "decimal_comma"}
    await page.evaluate("(h) => { h.callService = () => 0; card.hass = h; }", h)
    await page.wait_for_timeout(150)
    pressed = await page.evaluate("() => [...card.shadowRoot.querySelectorAll('.chip')].map(c => [c.dataset.mode, c.getAttribute('aria-pressed')])")
    assert ["relax", "true"] in pressed and ["auto", "false"] in pressed
    assert "Brightness over the day" in await page.evaluate("() => card.shadowRoot.getElementById('chartB').getAttribute('aria-label')")
    handle = "card.shadowRoot.querySelector('#handles-k .handle[data-idx=\"1\"]')"
    assert await page.evaluate(f"() => {handle}.getAttribute('aria-describedby')") == "handle-help"
    await page.evaluate(f"() => {handle}.dispatchEvent(new KeyboardEvent('keydown', {{key: 'End', bubbles: true}}))")
    assert (await _points(page))[1][2] == 7000
    await page.evaluate(f"() => {handle}.dispatchEvent(new KeyboardEvent('keydown', {{key: 'PageDown', bubbles: true}}))")
    assert (await _points(page))[1][2] == 6500
    text = await page.evaluate(f"() => {handle}.getAttribute('aria-valuetext')")
    assert text == "9:00 AM, 6.500 K"
    axis = await page.evaluate("() => card._chartB.scales.x.ticks.map(t => t.label).filter(Boolean)")
    assert axis[0] == "12:00 AM" and axis[2] == "12:00 PM"


async def test_k6_stub_config_and_editor(page):
    stub = await page.evaluate("""() => customElements.get('hcl-curve-card').getStubConfig({states: {
        'sensor.x': {attributes: {}}, 'sensor.wohnen_curve_data': {attributes: {control_points: [], mode_entity_id: 'select.m'}}}})""")
    assert stub == {"entity": "sensor.wohnen_curve_data"}
    changed = await page.evaluate("""() => new Promise(resolve => {
        const ed = customElements.get('hcl-curve-card').getConfigElement();
        document.body.appendChild(ed);
        ed.hass = {language: 'de', states: {
            'sensor.a_curve_data': {attributes: {control_points: [], mode_entity_id: 'select.a', friendly_name: 'A'}},
            'sensor.b_curve_data': {attributes: {control_points: [], mode_entity_id: 'select.b', friendly_name: 'B'}}}};
        ed.setConfig({type: 'custom:hcl-curve-card', entity: 'sensor.a_curve_data'});
        ed.addEventListener('config-changed', (e) => resolve(e.detail.config));
        const sel = ed.shadowRoot.getElementById('entity');
        sel.value = 'sensor.b_curve_data'; sel.dispatchEvent(new Event('change'));
    })""")
    assert changed == {"type": "custom:hcl-curve-card", "entity": "sensor.b_curve_data", "view": "full"}
    assert await page.evaluate("() => card.getGridOptions()") == {"columns": 12, "min_columns": 6}


async def test_k3_compact_view_hides_the_editor_until_opened(page):
    await page.evaluate("() => card.setConfig({entity: 'sensor.hcl_curve_data', view: 'compact'})")
    await _set_hass(page, "auto")
    assert await page.evaluate("() => card.shadowRoot.getElementById('editor-section').hidden") is True
    assert await page.evaluate("() => card.shadowRoot.getElementById('now-info').textContent") != ""
    await page.evaluate("() => card.shadowRoot.getElementById('btn-toggle-editor').click()")
    await page.wait_for_timeout(200)
    assert await page.evaluate("() => card.shadowRoot.getElementById('editor-section').hidden") is False
    assert await page.evaluate("() => card.shadowRoot.querySelectorAll('#handles-b .handle').length") == len(POINTS)


async def test_k7_night_light_chip_and_scaled_effective_curve(page):
    await _set_hass(page, "night_light", extra={"min_brightness": 20, "max_brightness": 60, "brightness_scaling": True})
    assert await _active_chips(page) == ["night_light"]
    effective = await page.evaluate("() => card._chartB.data.datasets[1].data.find(p => p.x === 750).y")
    assert round(effective) == 38  # 20 + (50 - 10) * 40/90, same as the integration
    assert page.errors == []


@pytest.fixture
async def browser_page_factory():
    """Page served from a fake HA origin (module URLs, versioned Chart.js)."""
    async with playwright_api.async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(executable_path=CHROMIUM if Path(CHROMIUM).exists() else None)
        except Exception as err:  # noqa: BLE001
            if os.environ.get("HCL_TEST_REQUIRE_BROWSER") == "1":
                raise
            pytest.skip(f"Chromium not available: {err}")

        async def make(foreign_chart=False, delay_chart=False, attach=True):
            page = await browser.new_page()
            page.errors = []
            page.on("pageerror", lambda e: page.errors.append(str(e)))
            requests: list[str] = []
            page.on("request", lambda r: requests.append(r.url))
            chart = (FRONTEND / "chart.js").read_text(encoding="utf-8")
            card = (FRONTEND / "hcl-curve-card.js").read_text(encoding="utf-8")
            foreign = "<script>window.Chart = {version: '2.9.4'};</script>" if foreign_chart else ""
            html = f"<html><body>{foreign}<script type='module' src='/hcl_lighting_static/hcl-curve-card.js?v=9.9.9'></script></body></html>"

            async def route(r):
                url = r.request.url
                if "chart.js" in url:
                    if delay_chart:
                        await asyncio.sleep(1)
                    await r.fulfill(body=chart, content_type="application/javascript")
                elif "hcl-curve-card.js" in url:
                    await r.fulfill(body=card, content_type="application/javascript")
                else:
                    await r.fulfill(body=html, content_type="text/html")

            await page.route("http://hcl.test/**", route)
            await page.goto("http://hcl.test/lovelace")
            await page.wait_for_function("() => !!customElements.get('hcl-curve-card')")
            if attach:
                await page.evaluate("""(h) => { window.card = document.createElement('hcl-curve-card');
                    card.setConfig({entity: 'sensor.hcl_curve_data'}); document.body.appendChild(card);
                    h.callService = () => 0; card.hass = h; }""", _hass("auto"))
                await page.wait_for_function("() => card._initialized")
            return page, requests

        yield make
        await browser.close()


async def test_b53_card_moved_while_loading_initialises(browser_page_factory):
    """Masonry dashboards detach and re-attach cards while they load."""
    page, _requests = await browser_page_factory(foreign_chart=False, delay_chart=True, attach=False)
    await page.evaluate("""() => { window.card = document.createElement('hcl-curve-card');
        card.setConfig({entity: 'sensor.hcl_curve_data'}); document.body.appendChild(card);
        const column = document.createElement('div'); document.body.appendChild(column);
        card.remove(); column.appendChild(card); }""")
    await page.wait_for_timeout(1800)
    assert await page.evaluate("() => card._initialized && !!card._chartB") is True
    assert page.errors == []


# ---------------------------------------------------------------- 0.7.0b2 (review of v0.7.0b1, R1–R4)
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
    await page.wait_for_timeout(100)


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


def _setpoint_hass(mode: str, tb: str | None, tk: str | None) -> dict:
    extra = {"scenarios": {"focus": {"b": 80, "k": 5000}, "night_light": {"b": 3, "k": 2200}},
             "target_brightness_entity_id": "sensor.tb", "target_color_temp_entity_id": "sensor.tk"}
    h = _hass(mode, extra=extra)
    if tb is not None:
        h["states"]["sensor.tb"] = {"state": tb, "attributes": {}}
    if tk is not None:
        h["states"]["sensor.tk"] = {"state": tk, "attributes": {}}
    return h


async def _now_info(page, h) -> str:
    await page.evaluate("(h) => { h.callService = () => 0; card.hass = h; }", h)
    await page.wait_for_timeout(100)
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


async def test_b55_removed_cards_release_their_charts(page):
    await _set_hass(page, "auto")
    before = await page.evaluate("() => Object.keys(card._Chart.instances).length")
    for _ in range(6):
        await page.evaluate("""() => { window.tmp = document.createElement('hcl-curve-card');
            tmp.setConfig({entity: 'sensor.hcl_curve_data'}); tmp.hass = card._hass; document.body.appendChild(tmp); }""")
        await page.wait_for_function("() => tmp._initialized && !!tmp._chartB")
        await page.evaluate("() => tmp.remove()")
    await page.wait_for_timeout(1500)
    assert await page.evaluate("() => Object.keys(card._Chart.instances).length") == before
    assert page.errors == []


async def test_b55_card_moved_in_the_dashboard_keeps_working(page):
    await _set_hass(page, "auto")
    await page.evaluate("() => { card._pushUndo(); card._points[0].b = 55; card._markChanged(); }")
    # quick move (masonry): charts are kept
    chart = await page.evaluate("() => { window.__c = card._chartB; card.remove(); document.body.appendChild(card); return 1; }")
    await page.wait_for_timeout(1500)
    assert chart == 1 and await page.evaluate("() => card._chartB === window.__c")
    # long detach: charts are released and rebuilt on the next attach, the draft stays
    await page.evaluate("() => card.remove()")
    await page.wait_for_timeout(1500)
    assert await page.evaluate("() => card._chartB === null") is True
    await page.evaluate("() => document.body.appendChild(card)")
    await page.wait_for_function("() => card._initialized && !!card._chartB")
    assert await page.evaluate("() => card._points[0].b") == 55
    assert await page.evaluate("() => card._isDirty") is True
    assert await page.evaluate("() => card.shadowRoot.querySelectorAll('#handles-b .handle').length") == len(POINTS)
    assert page.errors == []
