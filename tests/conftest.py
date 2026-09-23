"""Shared fixtures for HCL Lighting tests (pytest-homeassistant-custom-component)."""
from unittest.mock import patch

import pytest

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
