"""Base class of the HCL entities (RM-T21)."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN


class HCLEntity(Entity):
    """Entity of an HCL instance: one device per instance, names and icons from
    the translations (strings.json, icons.json)."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, unique_suffix: str | None) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}" if unique_suffix else entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="HCL Integration",
            model="HCL Controller",
        )
