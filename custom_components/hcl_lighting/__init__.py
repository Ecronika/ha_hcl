"""The HCL Lighting integration."""
from __future__ import annotations

import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, Platform
from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.restore_state import async_get as async_get_restore_state
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_WAKE_TIME,
    CONF_MIDDAY_TIME,
    CONF_SLEEP_TIME,
    DEFAULT_WAKE_TIME,
    DEFAULT_MIDDAY_TIME,
    DEFAULT_SLEEP_TIME,
    CONF_CURVE_CONFIG,
    CONF_OVERRIDE_TIMEOUT,
    CONF_OVERRIDE_RESET_ON_OFF,
    CONF_PERSIST_OVERRIDES,
    DEFAULT_OVERRIDE_TIMEOUT,
    DEFAULT_OVERRIDE_RESET_ON_OFF,
    DEFAULT_PERSIST_OVERRIDES,
    HCL_MODES,
    MODE_AUTO,
    EVENT_MANUAL_CONTROL,
)
from .conflicts import async_check_conflicts
from .logic.hcl_math import HCLCalculator
from .logic.override_manager import OverrideManager
from .services import async_register_services
from .logic.light_controller import HCLLightController

_LOGGER = logging.getLogger(__name__)

DATA_OVERRIDE_MANAGERS = f"{DOMAIN}_override_managers"
DATA_FRONTEND_REGISTERED = f"{DOMAIN}_frontend_registered"
OVERRIDE_STORE_VERSION = 1


def _override_store(hass: HomeAssistant, entry_id: str) -> Store:
    return Store(hass, OVERRIDE_STORE_VERSION, f"{DOMAIN}.overrides.{entry_id}")


async def _async_setup_override_manager(
    hass: HomeAssistant, entry: ConfigEntry, manager: OverrideManager, first_setup: bool
) -> None:
    """Apply the manual-control options and (optionally) persist the state."""
    options = entry.options
    timeout_min = int(options.get(CONF_OVERRIDE_TIMEOUT, DEFAULT_OVERRIDE_TIMEOUT))
    manager.timeout = timedelta(minutes=timeout_min) if timeout_min > 0 else None
    manager.reset_on_off = bool(options.get(CONF_OVERRIDE_RESET_ON_OFF, DEFAULT_OVERRIDE_RESET_ON_OFF))

    store = _override_store(hass, entry.entry_id)
    persist = bool(options.get(CONF_PERSIST_OVERRIDES, DEFAULT_PERSIST_OVERRIDES))
    if persist and first_setup:
        manager.import_overrides(await store.async_load() or {})
    elif not persist:
        await store.async_remove()

    signal = f"{DOMAIN}_{entry.entry_id}_overrides"
    reported = set(manager.overridden_entities())

    @callback
    def _on_change() -> None:
        if persist:
            store.async_delay_save(manager.export_overrides, 2)
        async_dispatcher_send(hass, signal)
        # Event (and logbook entry) per light whose manual control started/ended
        current = set(manager.overridden_entities())
        for light in sorted(current ^ reported):
            hass.bus.async_fire(
                EVENT_MANUAL_CONTROL,
                {
                    "entity_id": light,
                    "manual_control": light in current,
                    "instance": entry.title,
                    "config_entry_id": entry.entry_id,
                },
            )
        reported.clear()
        reported.update(current)

    manager.on_change = _on_change


def _restored_switch_state(hass: HomeAssistant, entry: ConfigEntry, key: str) -> bool:
    """Last state of an adaptation switch (default on)."""
    entity_id = er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_{key}")
    if entity_id is None:
        return True
    stored = async_get_restore_state(hass).last_states.get(entity_id)
    if stored is None:
        return True
    return stored.state.state != STATE_OFF

def _restored_mode(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Last scenario of the mode select (Auto if unknown or a timed scenario has ended).

    Mirrors HCLModeSelect's own restore so the controller already has the right
    scenario when the HCL switch sends its first update (e.g. no light command
    in Guest mode after a reload).
    """
    entity_id = er.async_get(hass).async_get_entity_id("select", DOMAIN, f"{entry.entry_id}_mode")
    if entity_id is None:
        return MODE_AUTO
    stored = async_get_restore_state(hass).last_states.get(entity_id)
    if stored is None or stored.state.state not in HCL_MODES:
        return MODE_AUTO
    extra = stored.extra_data.as_dict() if stored.extra_data is not None else {}
    until_iso = extra.get("until")
    until = dt_util.parse_datetime(until_iso) if isinstance(until_iso, str) else None
    if until is not None and until <= dt_util.utcnow():
        return MODE_AUTO
    return stored.state.state


_POINT_SCHEMA = vol.Schema(
    {
        vol.Required("t"): vol.All(vol.Coerce(int), vol.Range(min=0, max=1440)),
        vol.Required("b"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Required("k"): vol.All(vol.Coerce(int), vol.Range(min=2000, max=7000)),
    },
    extra=vol.ALLOW_EXTRA,
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

PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.SENSOR, Platform.SELECT]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the integration-wide service (independent of loaded entries)."""

    async def _handle(call: ServiceCall) -> None:
        await _async_update_curve_service(hass, call)

    hass.services.async_register(DOMAIN, "update_curve", _handle, schema=UPDATE_CURVE_SCHEMA)
    async_register_services(hass)
    return True


async def _async_update_curve_service(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle global update_curve service."""
    _LOGGER.debug(f"Service update_curve called (data={call.data})")
    points = call.data.get("points")
    mode = call.data.get("mode", "preview")
    entity_id = call.data.get("entity_id")
    
    if not entity_id:
        raise HomeAssistantError("update_curve called without entity_id")
        
    # Resolve Entry ID from Entity ID
    ent_reg = er.async_get(hass)
    entity_entry = ent_reg.async_get(entity_id)
    
    if not entity_entry:
         raise HomeAssistantError(f"Entity not found: {entity_id}")
    
    # Hardening: Validate Entity Type
    if entity_entry.domain not in ["sensor", "switch"]:
         raise HomeAssistantError(f"Invalid entity '{entity_id}'. Must be an HCL sensor or switch.")
         
    if entity_entry.platform != DOMAIN:
         raise HomeAssistantError(f"Entity '{entity_id}' is not an HCL Lighting entity.")
          
    entry_id = entity_entry.config_entry_id
    if not entry_id:
         raise HomeAssistantError(f"Entity {entity_id} is not linked to a Config Entry.")

    if entry_id not in hass.data.get(DOMAIN, {}):
         raise HomeAssistantError(f"Config Entry {entry_id} not loaded for HCL Lighting.")
    
    logic_core = hass.data[DOMAIN][entry_id]
    hcl_calc: HCLCalculator = logic_core["calculator"]
    
    # 1. Update In-Memory Calculator
    if points:
        hcl_calc.calculate_curve_from_points(points)
    # Preview/apply: unsaved points; save/revert: the stored curve applies again
    hcl_calc.preview_active = mode in ("preview", "apply")
        
    # 2. Handle Save
    if mode == "save":
        config_entry = hass.config_entries.async_get_entry(entry_id)
        new_options = {**config_entry.options}
        new_options[CONF_CURVE_CONFIG] = {"points": points, "version": 2}
        hass.config_entries.async_update_entry(config_entry, options=new_options)
        return
    # 2b. Handle Revert
    if mode == "revert":
        config_entry = hass.config_entries.async_get_entry(entry_id)
        curve_config = config_entry.options.get(CONF_CURVE_CONFIG)
        if curve_config:
             hcl_calc.generate_curve_from_config(curve_config)
        else:
             # No saved curve: default curve from the anchor times
             wake = config_entry.options.get(CONF_WAKE_TIME) or config_entry.data.get(CONF_WAKE_TIME) or DEFAULT_WAKE_TIME
             midday = config_entry.options.get(CONF_MIDDAY_TIME) or config_entry.data.get(CONF_MIDDAY_TIME) or DEFAULT_MIDDAY_TIME
             sleep = config_entry.options.get(CONF_SLEEP_TIME) or config_entry.data.get(CONF_SLEEP_TIME) or DEFAULT_SLEEP_TIME
             hcl_calc.generate_curve(wake, midday, sleep)
        _LOGGER.debug(f"Reverted HCL Curve for {entry_id} from ConfigEntry")
        # Notify frontend to refresh
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_update")
        return

    # 3. Preview/Apply: lights follow the points until the next reload
    from homeassistant.helpers.dispatcher import async_dispatcher_send
    async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_update")



async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HCL Lighting from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    # Initialize Shared Calculator
    hcl_calc = HCLCalculator()
    
    # Load Initial State
    # Check for v0.4.0 Config
    curve_config = entry.options.get(CONF_CURVE_CONFIG)
    
    if curve_config:
        try:
            hcl_calc.generate_curve_from_config(curve_config)
            _LOGGER.debug("Initialized with v0.4.0 CurveConfig")
        except Exception:
             _LOGGER.exception("Failed to load CurveConfig, falling back to Legacy")
             # Fallback logic below
             curve_config = None

    if not curve_config:
        # Legacy / Default Initialization
        wake = entry.options.get(CONF_WAKE_TIME) or entry.data.get(CONF_WAKE_TIME) or DEFAULT_WAKE_TIME
        midday = entry.options.get(CONF_MIDDAY_TIME) or entry.data.get(CONF_MIDDAY_TIME) or DEFAULT_MIDDAY_TIME
        sleep = entry.options.get(CONF_SLEEP_TIME) or entry.data.get(CONF_SLEEP_TIME) or DEFAULT_SLEEP_TIME
        
        hcl_calc.generate_curve(wake, midday, sleep)
        _LOGGER.debug("Initialized with Legacy Config")

    # Store shared instance
    # Initialize Logic Core
    # The override state is kept per entry across reloads (saving the curve or
    # the options reloads the entry) so manually controlled lights stay paused.
    managers = hass.data.setdefault(DATA_OVERRIDE_MANAGERS, {})
    first_setup = entry.entry_id not in managers
    override_manager = managers.setdefault(entry.entry_id, OverrideManager())
    await _async_setup_override_manager(hass, entry, override_manager, first_setup)
    controller = HCLLightController(hass, override_manager, hcl_calc, entry)
    # Restore the adaptation switches before any light command is sent
    controller.adapt_brightness = _restored_switch_state(hass, entry, "adapt_brightness")
    controller.adapt_color = _restored_switch_state(hass, entry, "adapt_color")
    # ... and the scenario (the HCL switch is set up before the mode select)
    controller.set_active_mode(_restored_mode(hass, entry), announce=False)

    # Store shared logic core
    hass.data[DOMAIN][entry.entry_id] = {
        "calculator": hcl_calc,
        "controller": controller,
        "override_manager": override_manager
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Static path and Lovelace resource (retried after startup if not ready)
    if not await _async_register_lovelace_resource(hass):
        async def _retry(_hass: HomeAssistant) -> None:
            await _async_register_lovelace_resource(hass)

        entry.async_on_unload(async_at_started(hass, _retry))
    
    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    # Onboarding: a one-time notification how to add the dashboard card
    await _async_card_hint(hass, entry)

    return True

from homeassistant.components.http import StaticPathConfig
from homeassistant.helpers import entity_registry as er

CARD_BASE_URL = "/hcl_lighting_static/hcl-curve-card.js"
ONBOARDING_STORE_VERSION = 1

_CARD_HINT = {
    "de": (
        "HCL Lighting: Dashboard-Karte hinzufügen",
        "Die Tageskurve von **{title}** bearbeitest du in der Dashboard-Karte: "
        "Dashboard bearbeiten → Karte hinzufügen → „HCL Curve Card“ wählen "
        "(oder manuell `type: custom:hcl-curve-card` mit `entity: {entity_id}`).",
    ),
    "en": (
        "HCL Lighting: add the dashboard card",
        "Edit the daily curve of **{title}** in the dashboard card: "
        "edit dashboard → add card → choose “HCL Curve Card” "
        "(or manually `type: custom:hcl-curve-card` with `entity: {entity_id}`).",
    ),
}


def _onboarding_store(hass: HomeAssistant) -> Store:
    return Store(hass, ONBOARDING_STORE_VERSION, f"{DOMAIN}.onboarding")


async def _async_card_hint(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Show the card hint once per instance as a dismissible notification.

    Up to 0.6 the hint was a repair issue that could not be dismissed; it is
    removed, and instances that already had it do not get the hint again.
    """
    from homeassistant.components import persistent_notification
    from homeassistant.helpers import issue_registry as ir

    store = _onboarding_store(hass)
    data = await store.async_load() or {}
    shown = set(data.get("shown", []))
    issue_id = f"setup_curve_card_{entry.entry_id}"
    had_issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    ir.async_delete_issue(hass, DOMAIN, issue_id)
    if entry.entry_id in shown:
        return
    if not had_issue:
        entity_id = er.async_get(hass).async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_curve"
        ) or "sensor.<name>_curve_data"
        title, message = _CARD_HINT.get((hass.config.language or "en").split("-")[0], _CARD_HINT["en"])
        persistent_notification.async_create(
            hass,
            message.format(title=entry.title, entity_id=entity_id),
            title=title,
            notification_id=f"{DOMAIN}_card_{entry.entry_id}",
        )
    shown.add(entry.entry_id)
    await store.async_save({"shown": sorted(shown)})



async def _async_register_lovelace_resource(hass: HomeAssistant) -> bool:
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

    from homeassistant.components.lovelace.resources import ResourceStorageCollection

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


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
        async_check_conflicts(hass)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up state that outlives reloads when an entry is deleted."""
    hass.data.get(DATA_OVERRIDE_MANAGERS, {}).pop(entry.entry_id, None)
    await _override_store(hass, entry.entry_id).async_remove()
    from homeassistant.components import persistent_notification
    from homeassistant.helpers import issue_registry as ir

    ir.async_delete_issue(hass, DOMAIN, f"setup_curve_card_{entry.entry_id}")
    persistent_notification.async_dismiss(hass, f"{DOMAIN}_card_{entry.entry_id}")
    store = _onboarding_store(hass)
    data = await store.async_load() or {}
    shown = [e for e in data.get("shown", []) if e != entry.entry_id]
    await store.async_save({"shown": shown})


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
