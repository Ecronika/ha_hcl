"""Shared fixtures for HCL Lighting tests (pytest-homeassistant-custom-component)."""
from unittest.mock import patch

import pytest
from homeassistant.util import dt as dt_util

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom_components/hcl_lighting."""
    yield


@pytest.fixture
def no_frontend_registration():
    """Skip static path / Lovelace resource registration (needs a running http server)."""
    with patch(
        "custom_components.hcl_lighting._async_register_lovelace_resource",
        return_value=None,
    ):
        yield


@pytest.fixture
def evening(freezer):
    """20:00 local time: the evening decline of the default curve (not 100 %)."""
    freezer.move_to(dt_util.now().replace(hour=20, minute=0, second=0, microsecond=0))
