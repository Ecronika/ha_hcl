"""Browser tests for hcl-curve-card.js (headless Chromium via Playwright).

Run separately from the Home Assistant tests:  pytest tests_frontend
Uses the Chromium given in env HCL_TEST_CHROMIUM (default /opt/pw-browsers/chromium)
or, if that path does not exist, the Chromium installed by `playwright install chromium`.
Skipped automatically when Playwright or Chromium is not available, unless
HCL_TEST_REQUIRE_BROWSER=1 is set (CI), then a missing browser is an error.
"""
from __future__ import annotations

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
        await pg.add_script_tag(content=(FRONTEND / "hcl-curve-card.js").read_text(encoding="utf-8"))
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
    await page.evaluate("() => { card.style.setProperty('--divider-color', 'rgb(1, 2, 3)'); card.style.setProperty('--secondary-text-color', 'rgb(4, 5, 6)'); }")
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
        return {text: s.textContent, shown: s.style.display !== 'none', error: s.classList.contains('error')}; }""")


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
