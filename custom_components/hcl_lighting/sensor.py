"""Sensor platform for HCL Lighting (Source of Truth)."""
from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN,
    ATTR_CURVE_VERSION,
    ATTR_SAMPLE_COUNT,
    ATTR_SAMPLES,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_MAX_BRIGHTNESS,
    CONF_MIN_BRIGHTNESS,
    CONF_MAX_BRIGHTNESS
)
from .logic.hcl_math import HCLCalculator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    """Set up the HCL Sensor."""
    
    logic_core = hass.data[DOMAIN][entry.entry_id]
    hcl_calc: HCLCalculator = logic_core["calculator"]
    
    sensor = HCLLightingCurveSensor(hass, entry, hcl_calc)
    
    async_add_entities([sensor])


class HCLLightingCurveSensor(SensorEntity):
    """Sensor that exposes the full HCL Curve state."""

    _attr_has_entity_name = True
    _attr_name = "Curve Data"
    _attr_translation_key = "hcl_curve_sensor"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False # Event driven
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, hcl_calc: HCLCalculator) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._entry = entry
        self._hcl_calc = hcl_calc
        self._attr_unique_id = f"{entry.entry_id}_curve"
        self._attr_native_value = datetime.now().isoformat() # Initial state
        
    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        
        # Resolve Select Entity ID for Frontend
        ent_reg = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(ent_reg, self._entry.entry_id)
        self._mode_entity_id = None
        for e in entries:
            if e.domain == "select":
                self._mode_entity_id = e.entity_id
                break
        
        # Subscribe to updates from Switch/Service
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, 
                f"{DOMAIN}_{self._entry.entry_id}_update",
                self._handle_update
            )
        )
        
        # Initial Update
        self._update_attributes()

    @callback
    def _handle_update(self):
        """Handle signal from switch/service."""
        # Retry finding Mode Entity if logic failed during startup (Race Condition)
        if not self._mode_entity_id:
             ent_reg = er.async_get(self.hass)
             entries = er.async_entries_for_config_entry(ent_reg, self._entry.entry_id)
             for e in entries:
                if e.domain == "select":
                    self._mode_entity_id = e.entity_id
                    break
        
        self._update_attributes()
        # Update state to trigger push
        self._attr_native_value = dt_util.now().isoformat()
        self.async_write_ha_state()


    def _update_attributes(self):
        """Regenerate attributes from hcl_calc."""
        points = self._hcl_calc.active_curve
        
        # Generate 97 samples (00:00 to 24:00 every 15m)
        samples = []
        
        # Mock a datetime for get_hcl_values logic
        # We need a date, time is variable
        base_date = dt_util.now()
        
        min_b = self._entry.options.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS)
        max_b = self._entry.options.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS)
        
        for i in range(97): # 0 to 96
            minutes = i * 15
            if minutes > 1440: minutes = 1440
            
            # Construct time object
            h = minutes // 60
            m = minutes % 60
            if h == 24: h = 0 # wrap for datetime construction, but logic handles 1440 logic if needed
            
            t_obj = base_date.replace(hour=h, minute=m, second=0, microsecond=0)
            
            b, k = self._hcl_calc.get_hcl_values(t_obj, min_b, max_b)
            samples.append([minutes, int(k), int(b)])

        self._attr_extra_state_attributes = {
            ATTR_SAMPLE_COUNT: len(samples),
            "control_points": points, # The explicit list
            ATTR_SAMPLES: samples,    # The interpolated curve
            ATTR_CURVE_VERSION: 2,
            "mode_entity_id": getattr(self, "_mode_entity_id", None)
        }

    @property
    def device_info(self):
        """Return device info."""
        from homeassistant.helpers.entity import DeviceInfo
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="HCL Integration",
            model="HCL Controller",
        )
