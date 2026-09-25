"""Services of HCL Lighting besides update_curve (F-02)."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_CURVE_CONFIG,
    CONF_MIDDAY_TIME,
    CONF_SLEEP_TIME,
    CONF_WAKE_TIME,
    DEFAULT_MIDDAY_TIME,
    DEFAULT_SLEEP_TIME,
    DEFAULT_WAKE_TIME,
    DOMAIN,
    HCL_MODES,
)

ATTR_LIGHTS = "lights"

APPLY_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional(ATTR_LIGHTS): cv.entity_ids,
        vol.Optional("transition"): vol.All(vol.Coerce(float), vol.Range(min=0, max=300)),
        vol.Optional("release_manual_control", default=False): cv.boolean,
    }
)
SET_MANUAL_CONTROL_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional(ATTR_LIGHTS): cv.entity_ids,
        vol.Optional("manual_control", default=True): cv.boolean,
    }
)
SET_SCENARIO_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("scenario"): vol.In(HCL_MODES),
        vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(min=0, max=1440)),
    }
)
GET_CURVE_SCHEMA = vol.Schema({vol.Required("entity_id"): cv.entity_id})


def resolve_entry_id(hass: HomeAssistant, entity_id: str) -> str:
    """Config entry of an HCL entity (switch, sensor or select) that is loaded."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != DOMAIN or not entry.config_entry_id:
        raise ServiceValidationError(f"{entity_id} is not an HCL Lighting entity")
    if entry.config_entry_id not in (hass.data.get(DOMAIN) or {}):
        raise ServiceValidationError(f"The HCL instance of {entity_id} is not loaded")
    return entry.config_entry_id


def _core(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    return hass.data[DOMAIN][resolve_entry_id(hass, call.data["entity_id"])]


def async_register_services(hass: HomeAssistant) -> None:
    """Register apply, set_manual_control, set_scenario and get_curve."""

    async def _apply(call: ServiceCall) -> None:
        switch = _core(hass, call)["switch"]
        await switch.async_apply(
            call.data.get(ATTR_LIGHTS), call.data.get("transition"), call.data["release_manual_control"]
        )

    async def _set_manual_control(call: ServiceCall) -> None:
        switch = _core(hass, call)["switch"]
        await switch.async_set_manual_control(call.data.get(ATTR_LIGHTS), call.data["manual_control"])

    async def _set_scenario(call: ServiceCall) -> None:
        select = _core(hass, call).get("mode_select")
        if select is None:
            raise ServiceValidationError("The scenario of this HCL instance is not available")
        await select.async_select_option(call.data["scenario"], duration=call.data.get("duration"))

    async def _get_curve(call: ServiceCall) -> ServiceResponse:
        entry_id = resolve_entry_id(hass, call.data["entity_id"])
        core = hass.data[DOMAIN][entry_id]
        entry = hass.config_entries.async_get_entry(entry_id)
        saved = (entry.options.get(CONF_CURVE_CONFIG) or {}).get("points")

        def anchor(key: str, default: str) -> str:
            return str(entry.options.get(key) or entry.data.get(key) or default)[:5]

        return {
            "points": [dict(p) for p in core["calculator"].active_curve],
            "saved_points": [dict(p) for p in saved] if saved else None,
            "preview_active": bool(core["calculator"].preview_active),
            "wake_time": anchor(CONF_WAKE_TIME, DEFAULT_WAKE_TIME),
            "midday_time": anchor(CONF_MIDDAY_TIME, DEFAULT_MIDDAY_TIME),
            "sleep_time": anchor(CONF_SLEEP_TIME, DEFAULT_SLEEP_TIME),
        }

    hass.services.async_register(DOMAIN, "apply", _apply, schema=APPLY_SCHEMA)
    hass.services.async_register(
        DOMAIN, "set_manual_control", _set_manual_control, schema=SET_MANUAL_CONTROL_SCHEMA
    )
    hass.services.async_register(DOMAIN, "set_scenario", _set_scenario, schema=SET_SCENARIO_SCHEMA)
    hass.services.async_register(
        DOMAIN, "get_curve", _get_curve, schema=GET_CURVE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
