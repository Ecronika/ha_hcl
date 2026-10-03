"""0.7.0b11: RM-F05 of the roadmap (card title from the instance; backend part)."""
from __future__ import annotations

from .helpers import CT_ATTRS, set_light, setup_entry

SENSOR = "sensor.hcl_curve_data"


async def test_rm_f05_curve_sensor_names_its_instance(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    await setup_entry(hass, ["light.a"])
    state = hass.states.get(SENSOR)
    assert state.attributes["instance"] == "HCL"
    # live value for the card, not stored in the history database
    assert "instance" in state.state_info["unrecorded_attributes"]


async def test_rm_f05_instance_follows_a_renamed_entry(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    hass.config_entries.async_update_entry(entry, title="Küche")
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).attributes["instance"] == "Küche"
