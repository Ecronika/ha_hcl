"""Browser tests of hcl-curve-card.js: loading, moving and removing the card, Chart.js, styles and layout, time zone and night window."""
from __future__ import annotations

import pytest

from card_support import RELEASE_WAIT_MS, POINTS, frames, _set_hass, _night_warnings


async def test_b18_card_styles_are_applied(page):
    """The :host rule is parsed (theme-based variables resolve on the card)."""
    b_color = await page.evaluate("() => getComputedStyle(card).getPropertyValue('--hcl-b-color').trim()")
    assert b_color.lower() == "#ffb300"  # fallback without HA theme


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


async def test_b47_narrow_cards_do_not_cut_off_content(page):
    for width in (240, 288):
        await page.evaluate("(w) => { card.style.display = 'block'; card.style.width = w + 'px'; }", width)
        await _set_hass(page, "auto")
        await frames(page, 3)  # resize observer, then a frame for the charts
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


async def test_b50_night_warning_times_are_valid_clock_times(page):
    await _set_hass(page, "auto", extra={"sleep_time": "22:00", "wake_time": "07:00"})
    msgs = await page.evaluate("() => card._validationResult.warnings.filter(w => w.type === 'night').map(w => w.msg)")
    assert len(msgs) == 1 and "24:" not in msgs[0] and "22:15–07:00" in msgs[0]
    await page.evaluate("() => card._loadDefaultCurve()")
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
    await page.wait_for_function("() => card._initPromise === null")  # Chart.js has loaded
    assert await page.evaluate("() => [card._initialized, card._chartB, card._nowTimer]") == [False, None, None]
    await page.evaluate("() => document.body.appendChild(card)")
    await page.wait_for_function("() => card._initialized && !!card._chartB")
    assert await page.evaluate("() => card._initialized && !!card._chartB") is True
    assert page.errors == []


async def test_b53_card_moved_while_loading_initialises(browser_page_factory):
    """Masonry dashboards detach and re-attach cards while they load."""
    page, _requests = await browser_page_factory(foreign_chart=False, delay_chart=True, attach=False)
    await page.evaluate("""() => { window.card = document.createElement('hcl-curve-card');
        card.setConfig({entity: 'sensor.hcl_curve_data'}); document.body.appendChild(card);
        const column = document.createElement('div'); document.body.appendChild(column);
        card.remove(); column.appendChild(card); }""")
    await page.wait_for_function("() => card._initialized && !!card._chartB", timeout=10000)
    assert await page.evaluate("() => card._initialized && !!card._chartB") is True
    assert page.errors == []


async def test_b55_removed_cards_release_their_charts(page):
    await _set_hass(page, "auto")
    before = await page.evaluate("() => Object.keys(card._Chart.instances).length")
    for _ in range(6):
        await page.evaluate("""() => { window.tmp = document.createElement('hcl-curve-card');
            tmp.setConfig({entity: 'sensor.hcl_curve_data'}); tmp.hass = card._hass; document.body.appendChild(tmp); }""")
        await page.wait_for_function("() => tmp._initialized && !!tmp._chartB")
        await page.evaluate("() => tmp.remove()")
    await page.wait_for_function("(n) => Object.keys(card._Chart.instances).length === n", arg=before, timeout=10000)
    assert page.errors == []


async def test_b55_card_moved_in_the_dashboard_keeps_working(page):
    await _set_hass(page, "auto")
    await page.evaluate("() => { card._pushUndo(); card._points[0].b = 55; card._markChanged(); }")
    # quick move (masonry): charts are kept
    chart = await page.evaluate("() => { window.__c = card._chartB; card.remove(); document.body.appendChild(card); return 1; }")
    await page.wait_for_timeout(RELEASE_WAIT_MS)  # nothing may happen: longer than the release delay
    assert chart == 1 and await page.evaluate("() => card._chartB === window.__c")
    # long detach: charts are released and rebuilt on the next attach, the draft stays
    await page.evaluate("() => card.remove()")
    await page.wait_for_function("() => card._chartB === null", timeout=10000)
    await page.evaluate("() => document.body.appendChild(card)")
    await page.wait_for_function("() => card._initialized && !!card._chartB")
    assert await page.evaluate("() => card._points[0].b") == 55
    assert await page.evaluate("() => card._isDirty") is True
    assert await page.evaluate("() => card.shadowRoot.querySelectorAll('#handles-b .handle').length") == len(POINTS)
    assert page.errors == []


async def _in_cell(page, height: str) -> None:
    """Put the card into a grid cell like a Sections view (fixed or auto height) with a card below."""
    await page.evaluate(
        """(height) => {
            const cell = document.createElement('div');
            cell.id = 'cell';
            cell.style.height = height;
            cell.style.width = '420px';
            const below = document.createElement('div');
            below.id = 'below';
            below.style.height = '50px';
            document.body.append(cell, below);
            cell.appendChild(card);
        }""",
        height,
    )
    await frames(page, 3)  # resize observer, then a frame for the charts


@pytest.mark.parametrize("height", ["300px", "auto"])
async def test_rm_b26_card_fills_a_fixed_height_and_scrolls(page, height):
    await _in_cell(page, height)
    await _set_hass(page, "auto")
    m = await page.evaluate("""() => {
        const hc = card.shadowRoot.querySelector('ha-card');
        return {card: card.getBoundingClientRect().bottom, cell: document.getElementById('cell').getBoundingClientRect().bottom,
                below: document.getElementById('below').getBoundingClientRect().top,
                scrollH: hc.scrollHeight, clientH: hc.clientHeight};
    }""")
    assert m["card"] <= m["cell"] + 0.5 and m["card"] <= m["below"] + 0.5  # nothing below is covered
    if height == "auto":
        assert m["scrollH"] <= m["clientH"] + 1  # as tall as the content, no scrolling
    else:
        assert m["scrollH"] > m["clientH"]  # the content scrolls inside the card
    assert page.errors == []
