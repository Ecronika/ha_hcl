"""Basic setup test: entry loads, entities exist, switching on sends an update."""
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_mock_service

from .helpers import CT_ATTRS, set_light, setup_entry, switch_entity


async def test_setup_and_turn_on(hass: HomeAssistant, no_frontend_registration) -> None:
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=10, color_temp_kelvin=2700, **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    for entity_id in ("switch.hcl_hcl_mode", "sensor.hcl_curve_data", "select.hcl_mode"):
        assert hass.states.get(entity_id) is not None, entity_id
    await switch_entity(hass).async_turn_on()
    await hass.async_block_till_done()
    assert calls, "HCL should have sent an update"
