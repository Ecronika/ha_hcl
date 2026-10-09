"""Config entry version 1.2 (0.8.0): all settings in the options, removed
settings dropped (RM-R07, RM-R10, RM-R11), the old minimum brightness kept
(RM-R06)."""
from __future__ import annotations

import pytest

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hcl_lighting.const import DOMAIN

from .support.curves import CUSTOM_POINTS
from .support.entries import CT_ATTRS, DIM, core, set_light, setup_entry, switch_entity


async def _setup_old(hass, data, options=None, version=1, minor_version=1):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = MockConfigEntry(
        domain=DOMAIN, title="HCL", data=data, options=options or {},
        version=version, minor_version=minor_version,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_data_moves_to_the_options(hass, no_frontend_registration):
    entry = await _setup_old(hass, {
        "name": "HCL", "target": {"entity_id": ["light.a"]},
        "wake_time": "06:30:00", "midday_time": "12:30:00", "sleep_time": "23:00:00",
    })
    assert entry.state is ConfigEntryState.LOADED
    assert (entry.version, entry.minor_version) == (1, 2)
    assert entry.data == {}
    assert entry.options == {
        "target": {"entity_id": ["light.a"]}, "wake_time": "06:30:00", "sleep_time": "23:00:00",
        "min_brightness": 10,  # the default up to 0.7 is kept (new instances: 3 %)
    }
    assert core(hass, entry)["controller"].brightness_limits() == (10, 100)
    # default curve of 0.8.0 from the anchor times
    assert {"t": 390, "b": 30, "k": 3000} in core(hass, entry)["calculator"].active_curve


async def test_options_win_over_the_setup_data(hass, no_frontend_registration):
    entry = await _setup_old(
        hass,
        {"name": "HCL", "target": {"entity_id": ["light.old"]}, "wake_time": "06:00:00"},
        {"target": {"entity_id": ["light.a"]}, "wake_time": "07:15:00", "min_brightness": 15},
    )
    assert entry.options["target"] == {"entity_id": ["light.a"]}
    assert entry.options["wake_time"] == "07:15:00"
    assert entry.options["min_brightness"] == 15


async def test_removed_settings_are_dropped_and_timing_is_limited(hass, no_frontend_registration):
    entry = await _setup_old(
        hass,
        {"name": "HCL", "target": {"entity_id": ["light.a"]}},
        {
            "midday_time": "13:00:00", "turn_on_transition": 15, "brightness_scaling": True,
            "scenario_limits": False, "night_end_at_wake": True,
            "update_interval": 600, "transition": 300, "scenario_transition": 300,
            "curve_config": {"points": CUSTOM_POINTS, "version": 2},
        },
    )
    options = entry.options
    for key in ("midday_time", "turn_on_transition", "brightness_scaling", "scenario_limits", "night_end_at_wake"):
        assert key not in options
    assert options["update_interval"] == 300  # 15-300 s (RM-R11)
    assert options["transition"] == 299  # shorter than the interval
    assert options["scenario_transition"] == 300  # may be longer than the interval
    # a saved curve stays as it is
    assert options["curve_config"]["points"] == CUSTOM_POINTS
    assert core(hass, entry)["calculator"].active_curve == sorted(CUSTOM_POINTS, key=lambda p: p["t"])


@pytest.mark.parametrize(("interval", "transition", "expected"), [(10, 5, (15, 5)), (10, 10, (15, 10)), (27, 20, (27, 20))])
async def test_short_interval_is_raised(hass, no_frontend_registration, interval, transition, expected):
    entry = await _setup_old(
        hass, {"name": "HCL", "target": {"entity_id": ["light.a"]}},
        {"update_interval": interval, "transition": transition},
    )
    assert (entry.options["update_interval"], entry.options["transition"]) == expected


async def test_entry_of_a_newer_version_is_not_loaded(hass, no_frontend_registration):
    entry = await _setup_old(hass, {}, {"target": {"entity_id": ["light.a"]}}, version=2, minor_version=1)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


async def test_current_entry_is_not_changed(hass, no_frontend_registration):
    options = {"target": {"entity_id": ["light.a"]}, "update_interval": 27}
    entry = await _setup_old(hass, {}, options, minor_version=2)
    assert entry.state is ConfigEntryState.LOADED
    assert dict(entry.options) == options  # no minimum brightness added: the default (3 %) applies
    assert core(hass, entry)["controller"].brightness_limits() == (3, 100)


# ---------------------------------------------------------------- RM-B35
async def test_rm_b35_options_without_target_use_the_setup(hass, no_frontend_registration):
    """An entry of version 1.1 with the target only in the setup data: the
    migration moves it to the options."""
    set_light(hass, "light.a", "on", **DIM)
    entry = await setup_entry(hass, ["light.a"], options={"transition": 5})
    assert switch_entity(hass).controlled_lights() == {"light.a"}
    assert entry.options["target"] == {"entity_id": ["light.a"]} and entry.data == {}
