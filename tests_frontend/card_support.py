"""Shared helpers of the browser tests of hcl-curve-card.js: the hass object
the card gets, waiting for rendering and reading the card state (T25)."""
from __future__ import annotations

# HCL_RELEASE_DELAY of the card (1000 ms) plus a margin: a check that nothing happens
RELEASE_WAIT_MS = 1500


POINTS = [
    {"t": 420, "k": 2700, "b": 30}, {"t": 540, "k": 4500, "b": 50}, {"t": 570, "k": 5500, "b": 75},
    {"t": 600, "k": 6500, "b": 100}, {"t": 720, "k": 6500, "b": 100}, {"t": 750, "k": 4000, "b": 50},
    {"t": 780, "k": 4000, "b": 50}, {"t": 810, "k": 6000, "b": 75}, {"t": 840, "k": 6000, "b": 75},
    {"t": 960, "k": 4000, "b": 50}, {"t": 1080, "k": 2700, "b": 30}, {"t": 1320, "k": 2200, "b": 10},
]


# Default curve of the integration for 07:00 / 22:00 (pinned in the backend
# test test_b08_valid_default_anchors_unchanged), as the sensor provides it
DEFAULT_POINTS = [
    {"t": 420, "k": 3000, "b": 30}, {"t": 440, "k": 4500, "b": 90}, {"t": 480, "k": 5000, "b": 100},
    {"t": 720, "k": 6000, "b": 100}, {"t": 1080, "k": 5000, "b": 100}, {"t": 1140, "k": 5000, "b": 100},
    {"t": 1320, "k": 2200, "b": 10}, {"t": 1335, "k": 2200, "b": 5}, {"t": 419, "k": 2200, "b": 5},
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
                    "default_points": DEFAULT_POINTS,
                    "mode_entity_id": "select.mode",
                    "min_brightness": 10,
                    "max_brightness": 100,
                    **(extra or {}),
                },
            },
            "select.mode": {"state": mode, "attributes": {}},
        }
    }


async def frames(page, count: int = 2) -> None:
    """Wait until the card has rendered: set hass renders at once, theme,
    charts and resize handling follow in the next animation frames (T25:
    instead of fixed waits)."""
    await page.evaluate(
        "(n) => new Promise(done => { const tick = k => k ? requestAnimationFrame(() => tick(k - 1)) : done(); tick(n); })",
        count,
    )


async def _set_hass(page, mode: str, **kwargs) -> None:
    await page.evaluate(
        "(h) => { h.callService = (...a) => window.__calls.push(a); card.hass = h; }",
        _hass(mode, **kwargs),
    )
    await frames(page)


async def _active_chips(page) -> list[str]:
    return await page.evaluate("() => [...card.shadowRoot.querySelectorAll('.chip.active')].map(c => c.dataset.mode)")


async def _points(page):
    return await page.evaluate("() => card._points.map(p => [p.t, p.b, p.k])")


async def _status(page):
    return await page.evaluate("""() => { const s = card.shadowRoot.getElementById('status');
        return {text: s.textContent, shown: s.textContent.trim() !== '', error: s.classList.contains('error')}; }""")


async def _night_warnings(page):
    return await page.evaluate("""() => card._validationResult.warnings
        .filter(w => w.type === 'night').map(w => [w.xMin, w.xMax])""")


async def _set_points(page, points, **kwargs):
    await page.evaluate(
        "(h) => { h.callService = card._hass.callService; card.hass = h; }",
        _hass("auto", extra={"control_points": points, **kwargs.pop("extra", {})}, **kwargs),
    )
    await frames(page)


def _setpoint_hass(mode: str, tb: str | None, tk: str | None) -> dict:
    extra = {"scenarios": {"focus": {"b": 80, "k": 5000}, "night_light": {"b": 3, "k": 2200}},
             "target_brightness_entity_id": "sensor.tb", "target_color_temp_entity_id": "sensor.tk"}
    h = _hass(mode, extra=extra)
    if tb is not None:
        h["states"]["sensor.tb"] = {"state": tb, "attributes": {}}
    if tk is not None:
        h["states"]["sensor.tk"] = {"state": tk, "attributes": {}}
    return h


# Home Assistant sets hass on every state change of any entity: a new hass and
# a new states map, unchanged state objects keep their identity.
async def _ha_like(page, h: dict) -> None:
    await page.evaluate(
        """(h) => {
            h.callService = () => 0;
            window.h = h;
            card.hass = h;
            // next hass: only 'sensor.power' changed (or the given states)
            window.next = (states = {}) => {
                const n = {...window.h, states: {...window.h.states,
                    'sensor.power': {state: String(Math.random()), attributes: {}}, ...states}};
                window.h = n;
                card.hass = n;
            };
            window.record = () => {
                window.__mutations = 0;
                window.__formats = 0;
                window.__mo = new MutationObserver(list => { window.__mutations += list.length; });
                window.__mo.observe(card.shadowRoot, {subtree: true, childList: true, attributes: true, characterData: true});
                const Real = Intl.NumberFormat;
                if (!window.__RealNumberFormat) window.__RealNumberFormat = Real;
                Intl.NumberFormat = function (...a) { window.__formats += 1; return new window.__RealNumberFormat(...a); };
            };
            window.stop = async () => {
                await new Promise(r => setTimeout(r, 50));
                window.__mo.disconnect();
                Intl.NumberFormat = window.__RealNumberFormat;
                return {mutations: window.__mutations, formats: window.__formats};
            };
        }""",
        h,
    )
    await frames(page)


def _until_hass(mode: str, hours: float | None, language: str = "en") -> dict:
    h = _setpoint_hass(mode, "3", "2200")
    h["config"] = {"time_zone": "Europe/Berlin"}
    h["language"] = language
    h["locale"] = {"language": language, "time_format": "24"}
    h["states"]["select.mode"]["attributes"] = {"__hours": hours}
    return h


async def _show(page, h: dict) -> str:
    """Set hass; the select gets until = now + __hours (ISO, like the integration)."""
    await page.evaluate(
        """(h) => {
            const sel = h.states['select.mode'];
            const hours = sel.attributes.__hours;
            sel.attributes = {until: hours === null ? null : new Date(Date.now() + hours * 3600e3).toISOString()};
            h.callService = () => 0;
            window.h = h;
            card.hass = h;
        }""",
        h,
    )
    return await page.evaluate("() => card.shadowRoot.getElementById('now-info').textContent")
