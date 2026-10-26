"""Browser tests for hcl-curve-card.js (headless Chromium via Playwright).

Run separately from the Home Assistant tests:  pytest tests_frontend
Uses the Chromium given in env HCL_TEST_CHROMIUM (default /opt/pw-browsers/chromium)
or, if that path does not exist, the Chromium installed by `playwright install chromium`.
Skipped automatically when Playwright or Chromium is not available, unless
HCL_TEST_REQUIRE_BROWSER=1 is set (CI), then a missing browser is an error.

The tests share one Chromium (session fixture), so they share its event loop
(T25). A failed test leaves a Playwright trace when HCL_TEST_TRACE_DIR is set
(CI uploads it; T26).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
import pytest_asyncio

from card_support import _hass, frames

if os.environ.get("HCL_TEST_REQUIRE_BROWSER") == "1":
    import playwright.async_api as playwright_api
else:
    playwright_api = pytest.importorskip("playwright.async_api")

FRONTEND = Path(__file__).parents[1] / "custom_components" / "hcl_lighting" / "frontend"
CHROMIUM = os.environ.get("HCL_TEST_CHROMIUM", "/opt/pw-browsers/chromium")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    marker = pytest.mark.asyncio(loop_scope="session")
    for item in items:
        item.add_marker(marker, append=False)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    report = yield
    if report.when == "call":
        item.failed_call = report.failed
    return report


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def browser():
    """One Chromium for all tests (a start costs seconds); every test gets its
    own browser context (T25)."""
    async with playwright_api.async_playwright() as pw:
        try:
            chromium = await pw.chromium.launch(executable_path=CHROMIUM if Path(CHROMIUM).exists() else None)
        except Exception as err:  # noqa: BLE001 - no browser installed
            if os.environ.get("HCL_TEST_REQUIRE_BROWSER") == "1":
                raise
            pytest.skip(f"Chromium not available: {err}")
        yield chromium
        await chromium.close()


TRACE_DIR = os.environ.get("HCL_TEST_TRACE_DIR")


@pytest_asyncio.fixture(loop_scope="session")
async def context(browser, request):
    ctx = await browser.new_context(viewport={"width": 900, "height": 900})
    if TRACE_DIR:
        await ctx.tracing.start(screenshots=True, snapshots=True, sources=False)
    yield ctx
    if TRACE_DIR:
        # keep the trace of a failed test only (T26)
        failed = getattr(request.node, "failed_call", False)
        name = "".join(c if c.isalnum() or c in "-_" else "_" for c in request.node.name)
        if failed:
            Path(TRACE_DIR).mkdir(parents=True, exist_ok=True)
        await ctx.tracing.stop(path=Path(TRACE_DIR) / f"{name}.zip" if failed else None)
    await ctx.close()


@pytest_asyncio.fixture(loop_scope="session")
async def page(context):
    pg = await context.new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    # Standards mode like Home Assistant (quirks mode resolves percentage heights differently)
    await pg.set_content("<!DOCTYPE html><html><body></body></html>")
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
    await pg.wait_for_function("() => card._initialized")
    await frames(pg)
    pg.errors = errors
    yield pg


@pytest_asyncio.fixture(loop_scope="session")
async def browser_page_factory(context):
    """Page served from a fake HA origin (module URLs, versioned Chart.js)."""
    async def make(foreign_chart=False, delay_chart=False, attach=True):
        page = await context.new_page()
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
