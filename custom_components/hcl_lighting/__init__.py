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
    
    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    return True

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
