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


def _hass(mode: str) -> dict:
    return {
        "states": {
            "sensor.hcl_curve_data": {
                "state": "x",
                "attributes": {
                    "control_points": POINTS,
                    "mode_entity_id": "select.mode",
                    "min_brightness": 10,
                    "max_brightness": 100,
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


async def _set_hass(page, mode: str) -> None:
    await page.evaluate(
        "(h) => { h.callService = (...a) => window.__calls.push(a); card.hass = h; }",
        _hass(mode),
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
    radius = await page.evaluate("() => getComputedStyle(card.shadowRoot.querySelector('ha-card')).borderTopLeftRadius")
    assert radius == "24px"
    accent = await page.evaluate("() => getComputedStyle(card).getPropertyValue('--accent-gold').trim()")
    assert accent.upper() == "#FFD700"


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
