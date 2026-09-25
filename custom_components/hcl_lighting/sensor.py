"""Sensor platform for HCL Lighting (Source of Truth)."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from datetime import timedelta

from .const import (
    DOMAIN,
    ATTR_CURVE_VERSION,
    ATTR_SAMPLE_COUNT,
    ATTR_SAMPLES,
    CONF_WAKE_TIME,
    CONF_SLEEP_TIME,
    DEFAULT_WAKE_TIME,
    DEFAULT_SLEEP_TIME,
    CONF_BRIGHTNESS_SCALING,
    DEFAULT_BRIGHTNESS_SCALING,
)
from .logic.hcl_math import HCLCalculator

_LOGGER = logging.getLogger(__name__)

# The setpoint sensors are recalculated once a minute (values change slowly)
SETPOINT_UPDATE_INTERVAL = timedelta(seconds=60)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    """Set up the HCL Sensor."""
    
    logic_core = hass.data[DOMAIN][entry.entry_id]
    hcl_calc: HCLCalculator = logic_core["calculator"]
    
    controller = logic_core["controller"]
    sensor = HCLLightingCurveSensor(hass, entry, hcl_calc, controller)

    async_add_entities([
        sensor,
        HCLSetpointSensor(entry, controller, "brightness"),
        HCLSetpointSensor(entry, controller, "color_temp"),
    ])


class HCLLightingCurveSensor(SensorEntity):
    """Sensor that exposes the full HCL Curve state."""

    _attr_has_entity_name = True
    _attr_name = "Curve Data"
    _attr_translation_key = "hcl_curve_sensor"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False # Event driven
    # State: time of the last curve/mode update
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    # The curve data is only needed live by the card, not in the history database
    _unrecorded_attributes = frozenset({ATTR_SAMPLES, "control_points", "scenarios"})
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, hcl_calc: HCLCalculator, controller) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._entry = entry
        self._hcl_calc = hcl_calc
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_curve"
        self._attr_native_value = dt_util.utcnow()
        
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
        
        # The mode select can be registered after this sensor (new entry) or be
        # renamed later; keep mode_entity_id (used by the card) in sync.
        self.async_on_remove(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._handle_registry_update
            )
        )

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
    def _handle_registry_update(self, event) -> None:
        """Re-resolve the mode select when a select entity is added, renamed or removed."""
        if not str(event.data.get("entity_id", "")).startswith("select."):
            return
        mode_entity_id = er.async_get(self.hass).async_get_entity_id(
            "select", DOMAIN, f"{self._entry.entry_id}_mode"
        )
        if mode_entity_id != self._mode_entity_id:
            self._mode_entity_id = mode_entity_id
            self._update_attributes()
            self.async_write_ha_state()

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
        self._attr_native_value = dt_util.utcnow()
        self.async_write_ha_state()


    def _update_attributes(self):
        """Regenerate attributes from hcl_calc."""
        points = self._hcl_calc.active_curve
        
        # Generate 97 samples (00:00 to 24:00 every 15m)
        samples = []
        
        # Mock a datetime for get_hcl_values logic
        # We need a date, time is variable
        base_date = dt_util.now()
        
        min_b, max_b = self._controller.brightness_limits()
        scale = bool(self._entry.options.get(CONF_BRIGHTNESS_SCALING, DEFAULT_BRIGHTNESS_SCALING))
        
        for i in range(97): # 0 to 96
            minutes = i * 15
            if minutes > 1440: minutes = 1440
            
            # Construct time object
            h = minutes // 60
            m = minutes % 60
            if h == 24: h = 0 # wrap for datetime construction, but logic handles 1440 logic if needed
            
            t_obj = base_date.replace(hour=h, minute=m, second=0, microsecond=0)
            
            b, k = self._hcl_calc.get_hcl_values(t_obj, min_b, max_b, scale=scale)
            samples.append([minutes, int(k), int(b)])

        self._attr_extra_state_attributes = {
            ATTR_SAMPLE_COUNT: len(samples),
            "control_points": points, # The explicit list
            ATTR_SAMPLES: samples,    # The interpolated curve
            ATTR_CURVE_VERSION: 2,
            "mode_entity_id": getattr(self, "_mode_entity_id", None),
            # Brightness limits, shaded in the dashboard card
            "min_brightness": min_b,
            "max_brightness": max_b,
            # Fixed values of the scenarios (drawn as lines in the card)
            "scenarios": self._controller.scenario_values(),
            # Min/max maps the curve range 10–100 % instead of clipping it
            "brightness_scaling": scale,
            # Setpoint sensors (the card shows the active values from them)
            "target_brightness_entity_id": self._related_entity_id("target_brightness"),
            "target_color_temp_entity_id": self._related_entity_id("target_color_temp"),
            # Anchor times (HH:MM); the card's night checks use sleep → wake
            "wake_time": self._anchor(CONF_WAKE_TIME, DEFAULT_WAKE_TIME),
            "sleep_time": self._anchor(CONF_SLEEP_TIME, DEFAULT_SLEEP_TIME),
            # The lights follow unsaved points (preview) until save, revert or reload
            "preview_active": bool(self._hcl_calc.preview_active),
        }

    def _anchor(self, key: str, default: str) -> str:
        value = self._entry.options.get(key) or self._entry.data.get(key) or default
        return str(value)[:5]

    def _related_entity_id(self, key: str) -> str | None:
        return er.async_get(self.hass).async_get_entity_id(
            "sensor", DOMAIN, f"{self._entry.entry_id}_{key}"
        )

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


class HCLSetpointSensor(SensorEntity):
    """Brightness or colour temperature HCL is currently aiming for.

    The value HCL sends to the lights now (curve or scenario, min/max and
    scaling applied), independent of the adapt switches, so it can also be
    passed on to other systems (e.g. KNX/DALI gateways). Unknown in Guest mode.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_suggested_display_precision = 0

    def __init__(self, entry: ConfigEntry, controller, kind: str) -> None:
        self._entry = entry
        self._controller = controller
        self._kind = kind
        key = "target_brightness" if kind == "brightness" else "target_color_temp"
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_native_unit_of_measurement = "%" if kind == "brightness" else "K"
        self._attr_icon = "mdi:brightness-percent" if kind == "brightness" else "mdi:thermometer"

    @property
    def device_info(self):
        """Same HCL device as the other entities."""
        from homeassistant.helpers.entity import DeviceInfo
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="HCL Integration",
            model="HCL Controller",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{DOMAIN}_{self._entry.entry_id}_update", self._handle_update
            )
        )
        self.async_on_remove(
            async_track_time_interval(self.hass, self._handle_update, SETPOINT_UPDATE_INTERVAL)
        )
        self._refresh()

    @callback
    def _handle_update(self, *_args) -> None:
        self._refresh()
        self.async_write_ha_state()

    def _refresh(self) -> None:
        brightness, kelvin = self._controller.calculate_target_values(dt_util.now())
        self._attr_native_value = brightness if self._kind == "brightness" else kelvin
