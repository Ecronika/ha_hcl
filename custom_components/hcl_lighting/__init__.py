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
from homeassistant.helpers.storage import Store

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
)
from .logic.hcl_math import HCLCalculator
from .logic.override_manager import OverrideManager
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

    @callback
    def _on_change() -> None:
        if persist:
            store.async_delay_save(manager.export_overrides, 2)
        async_dispatcher_send(hass, signal)

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

    # Store shared logic core
    hass.data[DOMAIN][entry.entry_id] = {
        "calculator": hcl_calc,
        "controller": controller,
        "override_manager": override_manager
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Static path and Lovelace resource: once per Home Assistant run
    if not hass.data.get(DATA_FRONTEND_REGISTERED):
        hass.data[DATA_FRONTEND_REGISTERED] = True
        await _async_register_lovelace_resource(hass)
    
    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    # 4. Create Setup Issue (Onboarding)
    # This guides the user to add the dashboard card
    # Lookup the created sensor entity to be helpful
    ent_reg = er.async_get(hass)
    curve_sensor_id = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_curve")
    
    # Fallback if registry lookup fails (though it shouldn't if setup was successful)
    if not curve_sensor_id:
        normalized_name = entry.title.lower().replace(" ", "_").replace("-", "_")
        curve_sensor_id = f"sensor.{normalized_name}_curve_data"

    from homeassistant.helpers import issue_registry as ir
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"setup_curve_card_{entry.entry_id}", # Unique per instance
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="setup_curve_card",
        translation_placeholders={
            "entity_id": curve_sensor_id
        }
    )

    return True

from homeassistant.components.http import StaticPathConfig
from homeassistant.helpers import entity_registry as er

async def _async_register_lovelace_resource(hass: HomeAssistant):
    """Register the Lovelace card resource if not already present."""
    # 1. Register Static Path
    # This maps /hcl_lighting_static/ -> custom_components/hcl_lighting/frontend/
    path = hass.config.path("custom_components/hcl_lighting/frontend")
    
    await hass.http.async_register_static_paths([
        StaticPathConfig(
            url_path="/hcl_lighting_static",
            path=path,
            cache_headers=False
        )
    ])
    
    # 2. Register Lovelace Resource
    from homeassistant.components.lovelace.resources import ResourceStorageCollection
    
    BASE_URL = "/hcl_lighting_static/hcl-curve-card.js"
    # Append version to URL to force cache bust on update
    FULL_URL = f"{BASE_URL}?v=0.6.0"
    
    if "lovelace" not in hass.data:
        return

    lovelace_data = hass.data["lovelace"]
    
    # Handle deprecation: .resources attribute instead of .get("resources")
    if hasattr(lovelace_data, "resources"):
        resources = lovelace_data.resources
    else:
        # Fallback for older versions (though likely dict access)
        resources = lovelace_data.get("resources")

    if not resources:
        return

    # YAML-mode resources are read-only (no create/delete); the user manages
    # them in configuration.yaml.
    if not isinstance(resources, ResourceStorageCollection):
        _LOGGER.info("Lovelace resources are in YAML mode; add %s manually", FULL_URL)
        return

    # Storage-mode resources are loaded lazily. Load them before reading or
    # writing, otherwise existing entries are missed and a write replaces the
    # stored resource list.
    await resources.async_get_info()

    # Check for existing and cleanup old versions
    found = False
    # Collect items to delete to avoid modifying while iterating
    to_delete = []
    
    for resource in resources.async_items():
        if resource["url"].startswith(BASE_URL):
            if resource["url"] == FULL_URL:
                found = True
            else:
                to_delete.append(resource["id"])
                
    # Remove old versions
    for res_id in to_delete:
        _LOGGER.info("Removing old HCL Curve Card resource (cache cleanup): %s", res_id)
        await resources.async_delete_item(res_id)
        
    # Create if not found
    if not found:
        _LOGGER.info("Auto-registering HCL Curve Card resource: %s", FULL_URL)
        try:
            await resources.async_create_item({"res_type": "module", "url": FULL_URL})
        except Exception as e:
            _LOGGER.warning("Failed to auto-register HCL Curve Card: %s", e)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up state that outlives reloads when an entry is deleted."""
    hass.data.get(DATA_OVERRIDE_MANAGERS, {}).pop(entry.entry_id, None)
    await _override_store(hass, entry.entry_id).async_remove()
    from homeassistant.helpers import issue_registry as ir
    ir.async_delete_issue(hass, DOMAIN, f"setup_curve_card_{entry.entry_id}")


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
