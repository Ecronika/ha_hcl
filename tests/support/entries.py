"""Config entries, entity ids and helpers of an HCL instance in tests."""
from __future__ import annotations

import asyncio

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
    """Return the main HCL switch entity object (not the adapt switches)."""
    from custom_components.hcl_lighting.switch import HCLSwitch

    comp = hass.data["entity_components"]["switch"]
    return next(e for e in comp.entities if isinstance(e, HCLSwitch))


# Entity ids of an instance named "HCL"
SWITCH = "switch.hcl_hcl_active"
SELECT = "select.hcl_scenario"
SENSOR = "sensor.hcl_curve_data"
ADAPT = "switch.hcl_adapt_brightness"

COLOR_ATTRS = {"supported_color_modes": ["xy"], "color_mode": "xy"}
WARM_CT = {**CT_ATTRS, "min_color_temp_kelvin": 2200, "max_color_temp_kelvin": 4000}
DIM = {"brightness": 3, "color_temp_kelvin": 2000, **CT_ATTRS}


def calls_for(calls, entity_id: str) -> list:
    """Recorded light calls (async_mock_service) that include the light."""
    out = []
    for call in calls:
        ids = call.data.get("entity_id")
        ids = [ids] if isinstance(ids, str) else list(ids or [])
        if entity_id in ids:
            out.append(call)
    return out


async def settle(rounds: int = 100) -> None:
    """Let waiting tasks run (asyncio.sleep(0) works with a frozen clock)."""
    for _ in range(rounds):
        await asyncio.sleep(0)


async def hcl_on(hass: HomeAssistant) -> None:
    await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    await hass.async_block_till_done()


async def select_scenario(hass: HomeAssistant, option: str) -> None:
    await hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": option}, blocking=True)
    await hass.async_block_till_done()


def start_select(hass: HomeAssistant, option: str) -> asyncio.Task:
    """Scenario change as a task (the caller decides when it may finish)."""
    return hass.async_create_task(
        hass.services.async_call("select", "select_option", {"entity_id": SELECT, "option": option}, blocking=True)
    )


async def setup_two_dim_lights(hass: HomeAssistant):
    """Two dim lights on (light.a, light.b), HCL on; the setup commands are cleared."""
    from .lights import FakeLights  # noqa: PLC0415 - entries does not depend on the double otherwise

    lights = FakeLights(hass)
    for eid in ("light.a", "light.b"):
        set_light(hass, eid, "on", **DIM)
    entry = await setup_entry(hass, ["light.a", "light.b"])
    await hcl_on(hass)
    lights.calls.clear()
    return lights, entry
