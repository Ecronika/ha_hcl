"""Test helpers for HCL Lighting."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hcl_lighting.const import DOMAIN

CT_ATTRS = {
    "supported_color_modes": ["color_temp"],
    "color_mode": "color_temp",
    "min_color_temp_kelvin": 2000,
    "max_color_temp_kelvin": 6500,
}


def set_light(hass: HomeAssistant, entity_id: str, state: str = "on", **attrs) -> None:
    """Set a fake light state (no real light platform needed)."""
    hass.states.async_set(entity_id, state, attrs)


async def setup_entry(hass: HomeAssistant, lights: list[str], options: dict | None = None) -> MockConfigEntry:
    """Create and set up an HCL config entry controlling the given lights."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HCL",
        data={"name": "HCL", "target": {"entity_id": lights}},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def core(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    """Return the logic core of an entry."""
    return hass.data[DOMAIN][entry.entry_id]


def switch_entity(hass: HomeAssistant):
    """Return the HCL switch entity object."""
    comp = hass.data["entity_components"]["switch"]
    return next(iter(comp.entities))
