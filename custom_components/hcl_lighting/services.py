"""Services of HCL Lighting besides update_curve (F-02)."""
from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

import voluptuous as vol

from homeassistant.auth.permissions.const import POLICY_CONTROL, POLICY_READ
from homeassistant.core import Context, HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError, Unauthorized, UnknownUser
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import CONTEXT_RECENT_TIME_SECONDS, Entity

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
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_hcl_entity",
            translation_placeholders={"entity_id": entity_id},
        )
    if entry.config_entry_id not in (hass.data.get(DOMAIN) or {}):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="instance_not_loaded",
            translation_placeholders={"entity_id": entity_id},
        )
    return entry.config_entry_id


def _core(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    return hass.data[DOMAIN][resolve_entry_id(hass, call.data["entity_id"])]


def _running_core(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    """Core of an instance whose main switch is added (not disabled, RM-B38)."""
    core = _core(hass, call)
    switch = core.get("switch")
    if switch is None or not switch.is_added:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="main_switch_disabled")
    return core


async def async_check_permissions(
    hass: HomeAssistant, call: ServiceCall, entity_ids: list[str | None], policy: str = POLICY_CONTROL
) -> None:
    """Check that the user who called the action may use these entities."""
    await async_check_context_permissions(hass, call.context, entity_ids, policy)


async def async_check_context_permissions(
    hass: HomeAssistant, context: Context | None, entity_ids: Iterable[str | None], policy: str = POLICY_CONTROL
) -> None:
    """Check that the user of a context may use these entities.

    Actions without a user (automations, scripts, Home Assistant itself) are
    allowed, as for Home Assistant's own entity actions. Admins may do all.
    """
    user_id = context.user_id if context is not None else None
    if user_id is None:
        return
    user = await hass.auth.async_get_user(user_id)
    if user is None:
        raise UnknownUser(context=context, permission=policy, user_id=user_id)
    for entity_id in dict.fromkeys(e for e in entity_ids if e):
        if not user.permissions.check_entity(entity_id, policy):
            raise Unauthorized(context=context, entity_id=entity_id, permission=policy)


def action_context(entity: Entity) -> Context | None:
    """Context of the action an entity is handling right now, else None.

    Home Assistant sets it before calling the entity (async_set_context) and
    stops using it for state writes after CONTEXT_RECENT_TIME_SECONDS; a
    context older than that belongs to an earlier action (e.g. the user who
    chose a scenario, not its automatic end).
    """
    context = entity._context  # set by Home Assistant for the current action
    set_at = entity._context_set
    if context is None or set_at is None or time.time() - set_at > CONTEXT_RECENT_TIME_SECONDS:
        return None
    return context


async def async_check_lights(hass: HomeAssistant, context: Context | None, core: dict[str, Any]) -> None:
    """An action of a user that makes HCL send light commands needs control
    of every light of the instance, as if the user switched them directly
    (like Home Assistant's own light actions on an area or a group)."""
    switch = core.get("switch")
    if switch is not None and context is not None and context.user_id is not None:
        await async_check_context_permissions(hass, context, sorted(switch.controlled_lights()))


def _entity_id_of(core: dict[str, Any], key: str) -> str | None:
    entity = core.get(key)
    return getattr(entity, "entity_id", None) if entity is not None else None


async def async_check_write_permissions(
    hass: HomeAssistant, call: ServiceCall, core: dict[str, Any], extra: list[str] | None = None
) -> None:
    """A writing action needs control of the given HCL entity, the HCL switch
    of the instance (it controls the lights) and the lights given explicitly."""
    await async_check_permissions(
        hass, call, [call.data.get("entity_id"), _entity_id_of(core, "switch"), *(extra or [])]
    )


def async_register_services(hass: HomeAssistant) -> None:
    """Register apply, set_manual_control, set_scenario and get_curve."""

    async def _apply(call: ServiceCall) -> None:
        core = _running_core(hass, call)
        await async_check_write_permissions(hass, call, core, call.data.get(ATTR_LIGHTS))
        if not call.data.get(ATTR_LIGHTS):
            await async_check_lights(hass, call.context, core)
        await core["switch"].async_apply(
            call.data.get(ATTR_LIGHTS),
            call.data.get("transition"),
            call.data["release_manual_control"],
            context=call.context,
        )

    async def _set_manual_control(call: ServiceCall) -> None:
        core = _running_core(hass, call)
        await async_check_write_permissions(hass, call, core, call.data.get(ATTR_LIGHTS))
        if not call.data["manual_control"]:
            # handing lights back runs an update of the instance at once
            await async_check_lights(hass, call.context, core)
        await core["switch"].async_set_manual_control(
            call.data.get(ATTR_LIGHTS), call.data["manual_control"], context=call.context
        )

    async def _set_scenario(call: ServiceCall) -> None:
        core = _running_core(hass, call)
        select = core.get("mode_select")
        if select is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="scenario_unavailable")
        await async_check_write_permissions(hass, call, core, [select.entity_id])
        await async_check_lights(hass, call.context, core)
        # The scenario change and the light commands it causes belong to this call
        select.async_set_context(call.context)
        await select.async_select_option(call.data["scenario"], duration=call.data.get("duration"))

    async def _get_curve(call: ServiceCall) -> ServiceResponse:
        entry_id = resolve_entry_id(hass, call.data["entity_id"])
        await async_check_permissions(hass, call, [call.data["entity_id"]], POLICY_READ)
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
