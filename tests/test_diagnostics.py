"""Diagnostics download."""
from __future__ import annotations

import json
import pytest

from datetime import timedelta
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.hcl_lighting.const import DOMAIN

from .support.entries import CT_ATTRS, DIM, core, hcl_on, set_light, setup_entry, switch_entity
from .support.lights import FakeLights


async def _light_on(hass, options=None):
    calls = async_mock_service(hass, "light", "turn_on")
    set_light(hass, "light.a", "on", brightness=255, color_temp_kelvin=6500, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"], options=options)
    await hcl_on(hass)
    return calls, entry


# ---------------------------------------------------------------- F-07 event, logbook, diagnostics
@pytest.mark.usefixtures("evening")
async def test_f07_diagnostics(hass, no_frontend_registration):
    from custom_components.hcl_lighting.diagnostics import async_get_config_entry_diagnostics

    _calls, entry = await _light_on(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["targets"] == ["light.redacted_1"]  # 0.7.0b12: pseudonyms (RM-B32)
    assert diag["lights"]["light.redacted_1"]["capability"] == "ct"
    target_b, _k = core(hass, entry)["controller"].calculate_target_values(dt_util.now())
    assert diag["setpoint"]["brightness"] == target_b and diag["scenario"] == "auto"


# ---------------------------------------------------------------- RM-B32
async def test_rm_b32_diagnostics_without_names_ids_and_times(hass, no_frontend_registration, freezer):
    from homeassistant.helpers import area_registry as ar
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.hcl_lighting.diagnostics import async_get_config_entry_diagnostics

    FakeLights(hass)
    area = ar.async_get(hass).async_create("Schlafzimmer Tobias")
    for eid in ("light.schlafzimmer_decke", "light.bad_spiegel"):
        set_light(hass, eid, "on", **DIM)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Schlafzimmer Tobias",
        data={"name": "Schlafzimmer Tobias", "target": {"entity_id": ["light.bad_spiegel"]}},
        options={
            "target": {"entity_id": ["light.schlafzimmer_decke", "light.bad_spiegel"], "area_id": [area.id]},
            "wake_time": "06:15",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await switch_entity(hass).async_turn_on()
    await hass.async_block_till_done()
    core(hass, entry)["override_manager"].set_override("light.schlafzimmer_decke")
    freezer.tick(timedelta(minutes=7))

    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(diag, default=str)
    for private in ("Tobias", "schlafzimmer", "bad_spiegel", area.id):
        assert private not in text
    # one light, one pseudonym in every part
    lights = diag["targets"]
    assert lights == ["light.redacted_1", "light.redacted_2"]
    decke = next(p for p in lights if diag["lights"][p]["manual_control"])
    assert diag["manual_control_minutes"] == {decke: 7}
    spiegel = next(p for p in lights if p != decke)
    assert diag["options"]["target"]["entity_id"] == [decke, spiegel]
    assert diag["options"]["target"]["area_id"] == ["area_1"]
    # since entry version 1.2 everything is in the options (the name is the title)
    assert diag["data"] == {}
    assert diag["title"] == "**REDACTED**"
    # what is needed to understand the behaviour stays
    assert diag["lights"][spiegel]["capability"] == "ct"
    assert diag["scenario"] == "auto" and diag["active_curve"]
    assert diag["options"]["wake_time"] == "06:15"
