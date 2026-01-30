"""The HCL Lighting integration."""
from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    CONF_WAKE_TIME,
    CONF_MIDDAY_TIME,
    CONF_SLEEP_TIME,
    DEFAULT_WAKE_TIME,
    DEFAULT_MIDDAY_TIME,
    DEFAULT_SLEEP_TIME,
    CONF_CURVE_CONFIG
)
from .logic.hcl_math import HCLCalculator

_LOGGER = logging.getLogger(__name__)

# List of platforms to support.
PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.SENSOR]

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
    hass.data[DOMAIN][entry.entry_id] = hcl_calc

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Auto-register Lovelace Resource
    await _async_register_lovelace_resource(hass)
    
    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    # Register Global Service
    async def async_update_curve_service(call):
        """Handle global update_curve service."""
        _LOGGER.debug(f"Service update_curve called (data={call.data})")
        points = call.data.get("points")
        mode = call.data.get("mode", "preview")
        entity_id = call.data.get("entity_id")
        
        if not entity_id:
            _LOGGER.error("update_curve called without entity_id")
            return
            
        # Resolve Entry ID from Entity ID
        # Support both switch.hcl_lighting and sensor.hcl_lighting_curve
        ent_reg = hass.helpers.entity_registry.async_get(hass)
        entity_entry = ent_reg.async_get(entity_id)
        
        if not entity_entry:
             # Fallback: Try to find config entry if only one exists?
             # But entity_id is provided by UI
             _LOGGER.error(f"Entity not found: {entity_id}")
             return
             
        entry_id = entity_entry.config_entry_id
        if not entry_id or entry_id not in hass.data[DOMAIN]:
             _LOGGER.error(f"Config Entry not found for entity: {entity_id}")
             return
        
        hcl_calc: HCLCalculator = hass.data[DOMAIN][entry_id]
        
        # 1. Update In-Memory Calculator
        if points:
            hcl_calc.calculate_curve_from_points(points)
            
        # 2. Handle Save
        if mode == "save":
            config_entry = hass.config_entries.async_get_entry(entry_id)
            new_options = {**config_entry.options}
            new_options[CONF_CURVE_CONFIG] = {"points": points, "version": 2}
            await hass.config_entries.async_update_entry(config_entry, options=new_options)
            return

        # 3. Notify Updates (Preview/Apply)
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_update")
        
        # Trigger Switch Update if 'apply'
        if mode == "apply":
            # We need to find the switch entity for this entry to trigger logic
            # Or just signal the switch to update?
            # switch listens to the dispatcher? No, switch usually just runs loop or listens to state.
            # But we can dispatch a "force_update" signal.
            pass # Currently implemented in switch.py as dispatcher listener? No.
            # Ideally the switch should subscribe to this update too.

    hass.services.async_register(DOMAIN, "update_curve", async_update_curve_service)

    return True

from homeassistant.components.http import StaticPathConfig

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
    
    URL = "/hcl_lighting_static/hcl-curve-card.js"
    
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

    # Check if exists
    for resource in resources.async_items():
        if resource["url"] == URL:
            return
            
    # Clean up old /local/ path if it exists
    OLD_URL = "/local/hcl_lighting/hcl-curve-card.js"
    for resource in resources.async_items():
        if resource["url"] == OLD_URL:
            _LOGGER.info("Removing old HCL Curve Card resource: %s", OLD_URL)
            await resources.async_delete_item(resource["id"])

    _LOGGER.info("Auto-registering HCL Curve Card resource: %s", URL)
    try:
        await resources.async_create_item({"res_type": "module", "url": URL})
    except Exception as e:
        _LOGGER.warning("Failed to auto-register HCL Curve Card: %s", e)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
