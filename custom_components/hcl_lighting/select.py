"""Select platform for HCL Lighting."""
from __future__ import annotations

import logging
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN, HCL_MODES, MODE_AUTO
from .logic.light_controller import HCLLightController

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the HCL Select entity."""
    logic_core = hass.data[DOMAIN][entry.entry_id]
    controller: HCLLightController = logic_core["controller"]
    
    async_add_entities([HCLModeSelect(entry, controller)])

class HCLModeSelect(SelectEntity, RestoreEntity):
    """Select entity for HCL Mode."""

    _attr_has_entity_name = True
    _attr_name = "Mode"
    _attr_translation_key = "hcl_mode"
    _attr_icon = "mdi:theme-light-dark"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, controller: HCLLightController) -> None:
        """Initialize."""
        self._entry = entry
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_mode"
        self._attr_options = HCL_MODES
        self._attr_current_option = controller.active_mode

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        
        # Restore State
        if last_state := await self.async_get_last_state():
            if last_state.state in HCL_MODES:
                self._attr_current_option = last_state.state
                # Sync logic core
                self._controller.set_active_mode(last_state.state)
                _LOGGER.debug(f"Restored HCL Mode to {last_state.state}")


    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self._controller.set_active_mode(option)
        self._attr_current_option = option
        self.async_write_ha_state()
        
        # Trigger global update to apply the new mode immediately
        # We find the switch entity for this entry and ask it to update?
        # Or better, we define a signal in const.
        # But for now, let's rely on the switch's periodic update OR trigger a generic update via service?
        
        # Optimization: Trigger update_curve service call (preview) or just let the user see it next cycle?
        # User Expectation: Immediate change.
        # The light controller sets active mode, but doesn't push to lights unless `update_hcl` runs.
        # Calling the controller directly won't work because `switch.py` owns the loop/timer.
        
        # We can fire the update signal that switch listens to!
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        async_dispatcher_send(self.hass, f"{DOMAIN}_{self._entry.entry_id}_update")
