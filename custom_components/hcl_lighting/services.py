"""Services of HCL Lighting (F-02; update_curve RM-T36)."""
from __future__ import annotations

import dataclasses
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.auth.permissions.const import POLICY_CONTROL, POLICY_READ
from homeassistant.core import Context, HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError, Unauthorized, UnknownUser
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_CURVE_CONFIG,
    CONF_SLEEP_TIME,
    CONF_WAKE_TIME,
    anchor_time,
    DOMAIN,
    HCL_MODES,
    SERVICE_UPDATE_CURVE,
    signal_update,
)
from .runtime import loaded_runtime

if TYPE_CHECKING:
    from .runtime import HCLRuntimeData
    from .switch import HCLSwitch

_LOGGER = logging.getLogger(__name__)

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
_POINT_SCHEMA = vol.Schema(
    {
        vol.Required("t"): vol.All(vol.Coerce(int), vol.Range(min=0, max=1440)),
        vol.Required("b"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Required("k"): vol.All(vol.Coerce(int), vol.Range(min=2000, max=7000)),
    },
    # other keys are dropped: only t, b, k are stored (RM-B40)
    extra=vol.REMOVE_EXTRA,
)


def _validate_update_curve(data: dict) -> dict:
    """Points are required (at least two) for every mode except 'revert'."""
    if data["mode"] != "revert" and len(data.get("points") or []) < 2:
        raise vol.Invalid("points (at least 2) are required for mode " + data["mode"])
    points = data.get("points") or []
    times = [point["t"] for point in points]
    duplicates = sorted({t for t in times if times.count(t) > 1})
    if duplicates:
        raise vol.Invalid(
            "points must have different times; duplicate t (minutes): "
            + ", ".join(str(t) for t in duplicates)
        )
    # 00:00 (t=0) and 24:00 (t=1440) are the same moment of the daily curve
    at_midnight = {(p["b"], p["k"]) for p in points if p["t"] in (0, 1440)}
    if len(at_midnight) > 1:
        raise vol.Invalid(
            "points at 00:00 (t=0) and 24:00 (t=1440) are the same moment and must have the same values"
        )
    return data


UPDATE_CURVE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("entity_id"): cv.entity_id,
            vol.Optional("mode", default="preview"): vol.In(["preview", "apply", "save", "revert"]),
            vol.Optional("points"): [_POINT_SCHEMA],
        }
    ),
    _validate_update_curve,
)


def resolve_entry_id(hass: HomeAssistant, entity_id: str) -> str:
    """Config entry of an HCL entity (switch, sensor or select) that is loaded."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != DOMAIN or not entry.config_entry_id:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_hcl_entity",
            translation_placeholders={"entity_id": entity_id},
        )
    if loaded_runtime(hass, entry.config_entry_id) is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="instance_not_loaded",
            translation_placeholders={"entity_id": entity_id},
        )
    return entry.config_entry_id


def _runtime(hass: HomeAssistant, call: ServiceCall) -> HCLRuntimeData:
    runtime = loaded_runtime(hass, resolve_entry_id(hass, call.data["entity_id"]))
    assert runtime is not None  # checked by resolve_entry_id
    return runtime


def _running_runtime(hass: HomeAssistant, call: ServiceCall) -> tuple[HCLRuntimeData, HCLSwitch]:
    """Runtime data and main switch of an instance whose main switch is added
    (not disabled, RM-B38)."""
    runtime = _runtime(hass, call)
    switch = runtime.switch
    if switch is None or not switch.is_added:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="main_switch_disabled")
    return runtime, switch


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


async def async_check_lights(hass: HomeAssistant, context: Context | None, runtime: HCLRuntimeData) -> None:
    """An action of a user that makes HCL send light commands needs control
    of every light of the instance, as if the user switched them directly
    (like Home Assistant's own light actions on an area or a group)."""
    switch = runtime.switch
    if switch is not None and context is not None and context.user_id is not None:
        await async_check_context_permissions(hass, context, sorted(switch.controlled_lights()))


async def async_check_write_permissions(
    hass: HomeAssistant, call: ServiceCall, runtime: HCLRuntimeData, extra: list[str] | None = None
) -> None:
    """A writing action needs control of the given HCL entity, the HCL switch
    of the instance (it controls the lights) and the lights given explicitly."""
    switch_id = runtime.switch.entity_id if runtime.switch is not None else None
    await async_check_permissions(hass, call, [call.data.get("entity_id"), switch_id, *(extra or [])])


def async_register_services(hass: HomeAssistant) -> None:
    """Register all actions (in async_setup, independent of loaded entries)."""

    async def _update_curve(call: ServiceCall) -> None:
        _LOGGER.debug("Service update_curve called (data=%s)", call.data)
        points = call.data.get("points")
        mode = call.data.get("mode", "preview")
        # Same check as the other actions: invalid input is a ServiceValidationError
        entry_id = resolve_entry_id(hass, call.data["entity_id"])
        runtime = loaded_runtime(hass, entry_id)
        # Changing the curve needs control of the given entity, the HCL switch
        # and the lights (they get the new values at once)
        await async_check_write_permissions(hass, call, runtime)
        await async_check_lights(hass, call.context, runtime)
        hcl_calc = runtime.calculator

        # 1. Update the calculator in memory
        if points:
            hcl_calc.calculate_curve_from_points(points)
        # Preview/apply: unsaved points; save/revert: the stored curve applies again
        hcl_calc.preview_active = mode in ("preview", "apply")

        # 2. Save: the points are already active (step 1). Only the curve
        # changes, so the entry is not reloaded (the update listener sees the
        # stored configuration); lights and card get the saved curve via the
        # update signal like after revert.
        if mode == "save":
            config_entry = hass.config_entries.async_get_entry(entry_id)
            new_options = {**config_entry.options}
            new_options[CONF_CURVE_CONFIG] = {"points": points, "version": 2}
            # Only the curve part: another change still waiting for the update
            # listener (e.g. options just saved) must reload as before
            runtime.applied_config = dataclasses.replace(
                runtime.applied_config, curve=new_options[CONF_CURVE_CONFIG]
            )
            hass.config_entries.async_update_entry(config_entry, options=new_options)
            async_dispatcher_send(hass, signal_update(entry_id), call.context)
            return
        # 2b. Revert
        if mode == "revert":
            config_entry = hass.config_entries.async_get_entry(entry_id)
            curve_config = config_entry.options.get(CONF_CURVE_CONFIG)
            if curve_config:
                hcl_calc.generate_curve_from_config(curve_config)
            else:
                # No saved curve: default curve from the anchor times
                hcl_calc.generate_curve(
                    anchor_time(config_entry.options, CONF_WAKE_TIME),
                    anchor_time(config_entry.options, CONF_SLEEP_TIME),
                )
            _LOGGER.debug("Reverted the curve of %s to the saved configuration", entry_id)
            # Notify frontend to refresh
            async_dispatcher_send(hass, signal_update(entry_id), call.context)
            return

        # 3. Preview/apply: lights follow the points until the next reload
        async_dispatcher_send(hass, signal_update(entry_id), call.context)

    async def _apply(call: ServiceCall) -> None:
        runtime, switch = _running_runtime(hass, call)
        await async_check_write_permissions(hass, call, runtime, call.data.get(ATTR_LIGHTS))
        if not call.data.get(ATTR_LIGHTS):
            await async_check_lights(hass, call.context, runtime)
        await switch.async_apply(
            call.data.get(ATTR_LIGHTS),
            call.data.get("transition"),
            call.data["release_manual_control"],
            context=call.context,
        )

    async def _set_manual_control(call: ServiceCall) -> None:
        runtime, switch = _running_runtime(hass, call)
        await async_check_write_permissions(hass, call, runtime, call.data.get(ATTR_LIGHTS))
        if not call.data["manual_control"]:
            # handing lights back runs an update of the instance at once
            await async_check_lights(hass, call.context, runtime)
        await switch.async_set_manual_control(
            call.data.get(ATTR_LIGHTS), call.data["manual_control"], context=call.context
        )

    async def _set_scenario(call: ServiceCall) -> None:
        runtime, _switch = _running_runtime(hass, call)
        select = runtime.mode_select
        if select is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="scenario_unavailable")
        await async_check_write_permissions(hass, call, runtime, [select.entity_id])
        await async_check_lights(hass, call.context, runtime)
        # The scenario change and the light commands it causes belong to this call
        select.async_set_context(call.context)
        await select.async_select_option(call.data["scenario"], duration=call.data.get("duration"))

    async def _get_curve(call: ServiceCall) -> ServiceResponse:
        entry_id = resolve_entry_id(hass, call.data["entity_id"])
        await async_check_permissions(hass, call, [call.data["entity_id"]], POLICY_READ)
        runtime = _runtime(hass, call)
        entry = hass.config_entries.async_get_entry(entry_id)
        saved = (entry.options.get(CONF_CURVE_CONFIG) or {}).get("points")

        def anchor(key: str) -> str:
            return anchor_time(entry.options, key)[:5]

        return {
            "points": [dict(p) for p in runtime.calculator.active_curve],
            "saved_points": [dict(p) for p in saved] if saved else None,
            "preview_active": bool(runtime.calculator.preview_active),
            "wake_time": anchor(CONF_WAKE_TIME),
            "sleep_time": anchor(CONF_SLEEP_TIME),
        }

    hass.services.async_register(DOMAIN, SERVICE_UPDATE_CURVE, _update_curve, schema=UPDATE_CURVE_SCHEMA)
    hass.services.async_register(DOMAIN, "apply", _apply, schema=APPLY_SCHEMA)
    hass.services.async_register(
        DOMAIN, "set_manual_control", _set_manual_control, schema=SET_MANUAL_CONTROL_SCHEMA
    )
    hass.services.async_register(DOMAIN, "set_scenario", _set_scenario, schema=SET_SCENARIO_SCHEMA)
    hass.services.async_register(
        DOMAIN, "get_curve", _get_curve, schema=GET_CURVE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
