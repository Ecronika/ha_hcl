"""Browser tests share one Chromium (session fixture), so they share its event
loop (T25). A failed test leaves a Playwright trace when HCL_TEST_TRACE_DIR is
set (CI uploads it; T26)."""
from __future__ import annotations

import pytest


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
