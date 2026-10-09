"""Config flow and options flow: fields, validation, sections."""
from __future__ import annotations

import pytest

from homeassistant.util import dt as dt_util
from unittest.mock import patch

from custom_components.hcl_lighting.const import DOMAIN

from .support.entries import CT_ATTRS, core, set_light, setup_entry


ANCHORS = {"wake_time": "07:00:00", "sleep_time": "22:00:00"}


OLD_OPTIONS = ("brightness_scaling", "scenario_limits", "night_end_at_wake")


@pytest.fixture
def _at_sleep_time(freezer):
    """22:00 (sleep time): the default curve asks for 10 %."""
    freezer.move_to(dt_util.now().replace(hour=22, minute=0, second=0, microsecond=0))


# ------------------------------------------------------------------ Ä-11
async def test_a11_options_flow_validation_and_steps(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    base = {"target": {"entity_id": ["light.a"]}, "wake_time": "07:00:00",
            "sleep_time": "22:00:00", "smart_transition": False, "min_brightness": 10, "max_brightness": 100}
    result = await hass.config_entries.options.async_configure(flow["flow_id"], base)
    assert result["step_id"] == "behavior"
    bad = {"override_timeout": 240, "override_reset_on_off": True, "persist_overrides": False,
           "respect_turn_on_values": False, "advanced": {"update_interval": 20, "transition": 20}}
    result = await hass.config_entries.options.async_configure(flow["flow_id"], bad)
    assert result["errors"] == {"base": "transition_too_long"}
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {**bad, "advanced": {"update_interval": 20, "transition": 10}}
    )
    assert result["step_id"] == "scenarios"
    result = await hass.config_entries.options.async_configure(flow["flow_id"], {"focus_brightness": 90})
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert entry.options["transition"] == 10 and entry.options["focus_brightness"] == 90
    assert entry.options["relax_kelvin"] == 2700  # defaults filled in


# ------------------------------------------------------------------ Ä-12
async def test_a12_setup_with_anchor_times(hass, no_frontend_registration):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    fields = {str(k) for k in result["data_schema"].schema}
    assert {"wake_time", "sleep_time"} <= fields and "midday_time" not in fields  # RM-R07
    data = {"name": "Büro", "target": {"entity_id": ["light.a"]},
            "wake_time": "06:00:00", "sleep_time": "09:00:00"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
    assert result["errors"] == {"base": "active_span_too_short"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**data, "sleep_time": "21:00:00"})
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    entry = result["result"]
    # curve from the setup anchors
    assert {"t": 360, "b": 30, "k": 3000} in core(hass, entry).calculator.active_curve
    # all settings in the options (entry version 1.2); a new instance has min 3 % (RM-R06)
    assert entry.data == {} and entry.minor_version == 2
    assert entry.options["target"] == {"entity_id": ["light.a"]} and entry.options["wake_time"] == "06:00:00"
    assert core(hass, entry).controller.brightness_limits() == (3, 100)


# ---------------------------------------------------------------- RM-B35
async def test_rm_b35_empty_target_is_rejected_in_the_options(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {"target": {"entity_id": []}, **ANCHORS, "smart_transition": False, "min_brightness": 10, "max_brightness": 100},
    )
    assert result["type"] == "form"
    assert result["errors"] == {"target": "no_lights"}


async def test_rm_b35_empty_target_is_rejected_at_setup(hass, no_frontend_registration):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "HCL", "target": {}, **ANCHORS}
    )
    assert result["type"] == "form"
    assert result["errors"] == {"target": "no_lights"}


# ---------------------------------------------------------------- RM-B11
async def test_rm_b11_options_form_errors_are_not_hidden(hass, no_frontend_registration):
    set_light(hass, "light.a", "on", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    from custom_components.hcl_lighting.config_flow import OptionsFlowHandler

    with patch.object(OptionsFlowHandler, "add_suggested_values_to_schema", side_effect=KeyError("bug")):
        with pytest.raises(KeyError):
            await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] == "form"


# ---------------------------------------------------------------- options flow
@pytest.mark.usefixtures("_at_sleep_time")
async def test_rm_r01_r03_options_gone_from_the_flow_and_the_entry(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(
        hass, ["light.a"], options={"brightness_scaling": True, "scenario_limits": False, "night_end_at_wake": True}
    )
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    fields = {str(k) for k in flow["data_schema"].schema}
    base = {"target": {"entity_id": ["light.a"]}, "wake_time": "07:00:00",
            "sleep_time": "22:00:00", "smart_transition": False, "min_brightness": 10, "max_brightness": 100}
    result = await hass.config_entries.options.async_configure(flow["flow_id"], base)
    fields |= {str(k) for k in result["data_schema"].schema}
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {"override_timeout": 240, "override_reset_on_off": True, "persist_overrides": False,
         "respect_turn_on_values": False, "advanced": {"update_interval": 27, "transition": 20}},
    )
    fields |= {str(k) for k in result["data_schema"].schema}
    assert not fields & set(OLD_OPTIONS)
    result = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert not set(entry.options) & set(OLD_OPTIONS)


# ---------------------------------------------------------------- RM-R11
async def test_rm_r11_timing_options_in_a_collapsed_section(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {"target": {"entity_id": ["light.a"]}, "wake_time": "07:00:00", "sleep_time": "22:00:00",
         "smart_transition": False, "min_brightness": 10, "max_brightness": 100},
    )
    assert result["step_id"] == "behavior"
    schema = {str(k): v for k, v in result["data_schema"].schema.items()}
    assert not {"update_interval", "transition", "scenario_transition", "turn_on_transition"} & set(schema)
    section = schema["advanced"]
    assert section.options["collapsed"] is True
    inner = {str(k): v for k, v in section.schema.schema.items()}
    assert set(inner) == {"update_interval", "transition", "scenario_transition"}
    interval = inner["update_interval"].config
    assert (interval["min"], interval["max"]) == (15, 300)
    # shown again with the error: the section is open
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {"override_timeout": 240, "override_reset_on_off": True, "persist_overrides": False,
         "respect_turn_on_values": False, "advanced": {"update_interval": 30, "transition": 30}},
    )
    assert result["errors"] == {"base": "transition_too_long"}
    schema = {str(k): v for k, v in result["data_schema"].schema.items()}
    assert schema["advanced"].options["collapsed"] is False
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {"override_timeout": 240, "override_reset_on_off": True, "persist_overrides": False,
         "respect_turn_on_values": False, "advanced": {"update_interval": 30, "transition": 25}},
    )
    result = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    await hass.async_block_till_done()
    assert (entry.options["update_interval"], entry.options["transition"]) == (30, 25)
    assert "advanced" not in entry.options  # stored flat, as before
