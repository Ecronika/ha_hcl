"""Uses of Home Assistant internals that are no public API (RM-T06).

Kept in one module so that a change in Home Assistant affects only this file:
- the Lovelace resource collection (dashboard resource of the card; there is
  no public API to register a resource in storage mode),
- the context of the action an entity is handling (Entity._context and
  _context_set, read to know which user caused a command, RM-B31).
Both are checked by targeted tests against the supported Home Assistant
versions.
"""
from __future__ import annotations

import logging
import time

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers.entity import CONTEXT_RECENT_TIME_SECONDS, Entity
from homeassistant.loader import async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DATA_FRONTEND_REGISTERED = f"{DOMAIN}_frontend_registered"
CARD_BASE_URL = "/hcl_lighting_static/hcl-curve-card.js"


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


async def async_register_lovelace_resource(hass: HomeAssistant) -> bool:
    """Serve the card files and keep the dashboard resource current.

    Two independent, idempotent steps: the static path (once per run) and the
    Lovelace resource (storage mode only; YAML resources are managed by the
    user). Each step is marked as done only after it succeeded, so a later
    entry setup or the retry after startup tries again. Returns True when the
    resource is in place (or managed by the user).
    """
    state = hass.data.setdefault(DATA_FRONTEND_REGISTERED, {})
    if not state.get("static"):
        path = hass.config.path("custom_components/hcl_lighting/frontend")
        await hass.http.async_register_static_paths([
            StaticPathConfig(url_path="/hcl_lighting_static", path=path, cache_headers=False)
        ])
        state["static"] = True
    if state.get("resource"):
        return True

    # The version of the card URL comes from manifest.json (cache busting)
    version = (await async_get_integration(hass, DOMAIN)).version
    full_url = f"{CARD_BASE_URL}?v={version}"

    lovelace_data = hass.data.get("lovelace")
    resources = None
    if lovelace_data is not None:
        resources = getattr(lovelace_data, "resources", None)
        if resources is None and isinstance(lovelace_data, dict):
            resources = lovelace_data.get("resources")
    if resources is None:
        _LOGGER.debug("Lovelace resources not available yet; HCL card registration is retried")
        return False

    # Lovelace internals: imported only when the resources exist
    from homeassistant.components.lovelace.resources import ResourceStorageCollection  # noqa: PLC0415

    # YAML-mode resources are read-only; the user manages them in configuration.yaml
    if not isinstance(resources, ResourceStorageCollection):
        _LOGGER.info("Lovelace resources are in YAML mode; add %s as a module resource", full_url)
        state["resource"] = True
        return True

    try:
        # Storage-mode resources are loaded lazily; load them before reading or
        # writing, otherwise existing entries are missed and a write replaces
        # the stored resource list.
        await resources.async_get_info()
        ours = [r for r in resources.async_items() if str(r.get("url", "")).startswith(CARD_BASE_URL)]
        current = [r for r in ours if r["url"] == full_url]
        if current:
            keep = current[0]
        elif ours:
            # Update the existing entry in place (no gap without a resource)
            keep = ours[0]
            _LOGGER.info("Updating HCL Curve Card resource to %s", full_url)
            await resources.async_update_item(keep["id"], {"res_type": "module", "url": full_url})
        else:
            _LOGGER.info("Registering HCL Curve Card resource %s", full_url)
            keep = await resources.async_create_item({"res_type": "module", "url": full_url})
        for resource in ours:
            if resource["id"] != keep["id"]:
                await resources.async_delete_item(resource["id"])
    except Exception:  # noqa: BLE001 - never break the integration setup
        _LOGGER.warning(
            "Could not register the HCL Curve Card resource; add %s as a module resource "
            "(Settings → Dashboards → Resources) or restart Home Assistant", full_url, exc_info=True,
        )
        return False
    state["resource"] = True
    return True
