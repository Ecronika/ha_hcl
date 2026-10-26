"""Browser tests of hcl-curve-card.js: curve editor: adding, moving and deleting points (pointer, keyboard, numeric input, sliders), texts and the card editor."""
from __future__ import annotations

from card_support import POINTS, DEFAULT_POINTS, _hass, frames, _set_hass, _points, _status, _night_warnings, _set_points


async def test_editor_basics_unchanged(page):
    """Existing behaviour: handles rendered for all points, no JS errors."""
    await _set_hass(page, "auto")
    n = await page.evaluate("() => card.shadowRoot.querySelectorAll('#handles-b .handle').length")
    assert n == len(POINTS)
    assert page.errors == []


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
    await frames(page)
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
        await page.evaluate("""() => card.shadowRoot.querySelector('#handles-b .handle-input[data-idx="1"]')
            .dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true}))""")
    pts = await _points(page)
    assert pts[1][0] == 555 and pts[1][0] < pts[2][0]
    # delete down to two points; the last two cannot be deleted
    for _ in range(20):
        await page.evaluate("""() => { const h = card.shadowRoot.querySelector('#handles-b .handle-input[data-idx="0"]');
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


async def test_rm_r08_default_curve_button_loads_the_curve_of_the_sensor(page):
    """RM-R08: one button loads the default curve for the anchor times of the
    instance (sensor attribute default_points) instead of fixed presets."""
    await _set_hass(page, "auto")
    button = "card.shadowRoot.getElementById('btn-default')"
    assert await page.evaluate(f"() => {button}.disabled") is False
    assert await page.evaluate("() => card.shadowRoot.getElementById('preset-select')") is None
    await page.evaluate(f"() => {button}.click()")
    loaded = await page.evaluate("() => card._points.map(p => [p.t, p.b, p.k])")
    assert loaded == sorted([[p["t"], p["b"], p["k"]] for p in DEFAULT_POINTS])
    assert await page.evaluate("() => card._isDirty") is True  # not saved yet
    assert await _night_warnings(page) == []
    await page.evaluate("() => card._undoLast()")
    assert await page.evaluate("() => card._points.length") == len(POINTS)
    # without the attribute (e.g. a sensor not loaded yet) the button is disabled
    await _set_hass(page, "auto", extra={"default_points": None})
    assert await page.evaluate(f"() => {button}.disabled") is True
    assert page.errors == []


async def test_b41_midnight_24_00_is_the_same_as_00_00(page):
    got = await page.evaluate("""() => {
        const { normalize: hclNormalize, valueAt: hclValueAt } = customElements.get('hcl-curve-card').curve;
        const pts = hclNormalize([{t: 0, b: 10, k: 2200}, {t: 720, b: 50, k: 4000}, {t: 1440, b: 90, k: 6500}]);
        const owl = hclNormalize([{t: 540, b: 20, k: 2700}, {t: 1200, b: 21, k: 2700}, {t: 1440, b: 5, k: 2200}]);
        return [pts.map(p => p.t), hclValueAt(pts, 0).b, owl.map(p => p.t), hclValueAt(owl, 0).b]; }""")
    assert got == [[0, 720], 10, [0, 540, 1200], 5]


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


async def test_k5_semantics_keyboard_and_formats(page):
    h = _hass("relax")
    h["locale"] = {"language": "en", "time_format": "12", "number_format": "decimal_comma"}
    await page.evaluate("(h) => { h.callService = () => 0; card.hass = h; }", h)
    await frames(page)
    pressed = await page.evaluate("() => [...card.shadowRoot.querySelectorAll('.chip')].map(c => [c.dataset.mode, c.getAttribute('aria-pressed')])")
    assert ["relax", "true"] in pressed and ["auto", "false"] in pressed
    assert "Brightness over the day" in await page.evaluate("() => card.shadowRoot.getElementById('chartB').getAttribute('aria-label')")
    handle = "card.shadowRoot.querySelector('#handles-k .handle-input[data-idx=\"1\"]')"
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
    assert await page.evaluate("() => card.getGridOptions()") == {"columns": 12, "rows": "auto", "min_columns": 6}


async def test_k3_compact_view_hides_the_editor_until_opened(page):
    await page.evaluate("() => card.setConfig({entity: 'sensor.hcl_curve_data', view: 'compact'})")
    await _set_hass(page, "auto")
    assert await page.evaluate("() => card.shadowRoot.getElementById('editor-section').hidden") is True
    assert await page.evaluate("() => card.shadowRoot.getElementById('now-info').textContent") != ""
    await page.evaluate("() => card.shadowRoot.getElementById('btn-toggle-editor').click()")
    await frames(page)
    assert await page.evaluate("() => card.shadowRoot.getElementById('editor-section').hidden") is False
    assert await page.evaluate("() => card.shadowRoot.querySelectorAll('#handles-b .handle').length") == len(POINTS)


async def _drag_rows(page, idx: int, steps: int, dy: int, insert_at: int | None = None) -> list[dict]:
    return await page.evaluate(
        """async ([idx, steps, dy, insertAt]) => {
            const sr = card.shadowRoot; const W = ms => new Promise(r => setTimeout(r, ms));
            const handle = () => sr.querySelector(`#handles-b .handle[data-idx="${idx}"]`);
            const layer = () => sr.getElementById('handles-b');
            handle().setPointerCapture = () => {};
            let r = handle().getBoundingClientRect();
            const x = r.x + r.width / 2; let y = r.y + r.height / 2;
            const top0 = layer().getBoundingClientRect().top;
            handle().dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, composed: true, pointerId: 3, clientX: x, clientY: y}));
            const rows = [];
            for (let i = 0; i < steps; i++) {
                if (i === insertAt) {  // something above the charts changes its height
                    const block = document.createElement('div'); block.style.height = '50px'; block.id = 'shift';
                    sr.querySelector('.charts').before(block);
                }
                y += dy;
                window.dispatchEvent(new PointerEvent('pointermove', {pointerId: 3, clientX: x, clientY: y}));
                await W(40);
                const hr = handle().getBoundingClientRect();
                rows.push({off: Math.abs(hr.y + hr.height / 2 - y), top: layer().getBoundingClientRect().top - top0,
                           msgs: sr.getElementById('validation-area').textContent,
                           draft: sr.getElementById('draft-info').textContent.length});
            }
            window.dispatchEvent(new PointerEvent('pointerup', {pointerId: 3, clientX: x, clientY: y}));
            await W(50);
            rows.push({after: true, msgs: sr.getElementById('validation-area').textContent,
                       draft: sr.getElementById('draft-info').textContent.length});
            return rows;
        }""",
        [idx, steps, dy, insert_at],
    )


async def test_rm_b27_charts_do_not_move_while_dragging(page):
    await _set_hass(page, "auto")
    msgs_before = await page.evaluate("() => card.shadowRoot.getElementById('validation-area').textContent")
    # point 1 (09:00, 50 %) down to about 10 %: the curve to 09:30 (75 %) gets steep
    rows = await _drag_rows(page, 1, 6, 14)
    during, after = rows[:-1], rows[-1]
    assert all(r["off"] <= 1 for r in during)  # the point stays under the pointer
    assert all(r["top"] == 0 for r in during)  # the charts do not move
    assert all(r["msgs"] == msgs_before and r["draft"] == 0 for r in during)
    assert after["draft"] > 0  # draft line and messages follow on release
    assert after["msgs"] != msgs_before  # the slope warning appears after release
    assert page.errors == []


async def test_rm_b27_point_follows_the_pointer_after_a_shift(page):
    await _set_hass(page, "auto")
    rows = await _drag_rows(page, 5, 6, 6, insert_at=2)  # 12:30, 50 %: no limit reached
    assert all(r["off"] <= 1 for r in rows[:-1])
    assert page.errors == []


async def test_rm_b27_larger_touch_target(page):
    css = await page.evaluate("() => card.shadowRoot.querySelector('style').textContent")
    assert "@media (pointer: coarse) { .handle::after { inset: -16px; } }" in css  # 12 + 2 × 16 = 44 px


async def test_rm_b28_points_are_native_sliders(page):
    await _set_hass(page, "auto", language="de")
    snap = await page.locator("hcl-curve-card").aria_snapshot()
    assert 'slider "Helligkeitspunkt 1"' in snap and 'slider "Farbtemperaturpunkt 12"' in snap
    info = await page.evaluate("""() => {
        const i = card.shadowRoot.querySelector('#handles-b .handle-input[data-idx="0"]');
        const d = card.shadowRoot.querySelector('#handles-b .handle[data-idx="0"]');
        return {type: i.type, value: i.value, min: i.min, max: i.max, text: i.getAttribute('aria-valuetext'),
                pointHidden: d.getAttribute('aria-hidden'), same: i.style.transform === d.style.transform};
    }""")
    assert info == {"type": "range", "value": "30", "min": "0", "max": "100", "text": "07:00, 30 %",
                    "pointHidden": "true", "same": True}


async def test_rm_b28_screen_reader_adjustment_keeps_the_focus(page):
    await _set_hass(page, "auto")
    result = await page.evaluate("""async () => {
        const sr = card.shadowRoot; const W = ms => new Promise(r => setTimeout(r, ms));
        const input = sr.querySelector('#handles-k .handle-input[data-idx="2"]');
        input.focus();
        // what TalkBack/VoiceOver do: the browser changes the value and fires "input"
        input.value = String(Number(input.value) - 500);
        input.dispatchEvent(new Event('input', {bubbles: true}));
        await W(50);
        card.hass = {...card._hass, states: {...card._hass.states}};  // a hass update
        card._refreshCharts();                                         // and a resize
        await W(50);
        return {k: card._points[2].k, same: sr.activeElement === input, connected: input.isConnected,
                selected: card._selected, dirty: card._isDirty, text: input.getAttribute('aria-valuetext')};
    }""")
    # point 2 (09:30, 5500 K) is now 5000 K; the focused slider was not replaced
    assert result == {"k": 5000, "same": True, "connected": True, "selected": 2, "dirty": True, "text": "09:30, 5,000 K"}
    assert page.errors == []


async def test_rm_f05_title_from_the_instance_or_the_option(page):
    title = lambda: page.evaluate("() => card.shadowRoot.getElementById('card-title').textContent")  # noqa: E731
    await _set_hass(page, "auto", language="de")
    assert await title() == "HCL-Konfigurator"  # older integration: no attribute
    await _set_hass(page, "auto", language="de", extra={"instance": "Küche"})
    assert await title() == "Küche"
    await page.evaluate("() => card.setConfig({entity: 'sensor.hcl_curve_data', title: 'Kochen'})")
    assert await title() == "Kochen"
    await page.evaluate("() => card.setConfig({entity: 'sensor.hcl_curve_data', title: '  '})")
    assert await title() == "Küche"
    assert page.errors == []


async def test_rm_f05_editor_title_field(page):
    configs = await page.evaluate("""() => new Promise(resolve => {
        const out = [];
        const ed = customElements.get('hcl-curve-card').getConfigElement();
        document.body.appendChild(ed);
        ed.hass = {language: 'de', states: {
            'sensor.a_curve_data': {attributes: {control_points: [], mode_entity_id: 'select.a', friendly_name: 'HCL Curve', instance: 'Küche'}}}};
        ed.setConfig({type: 'custom:hcl-curve-card', entity: 'sensor.a_curve_data'});
        ed.addEventListener('config-changed', (e) => { out.push(e.detail.config); ed.setConfig(e.detail.config); });
        const option = ed.shadowRoot.querySelector('#entity option').textContent;
        const label = ed.shadowRoot.getElementById('l-title').textContent;
        let t = ed.shadowRoot.getElementById('title');
        t.value = ' Kochen '; t.dispatchEvent(new Event('change'));
        t = ed.shadowRoot.getElementById('title');
        t.value = ''; t.dispatchEvent(new Event('change'));
        resolve({option, label, out});
    })""")
    assert configs["option"] == "Küche (sensor.a_curve_data)"
    assert configs["label"] == "Titel (leer: Name der Instanz)"
    assert configs["out"][0]["title"] == "Kochen" and "title" not in configs["out"][1]
