"""Resolution of the light target of an instance (RM-T08: separate from the
light commands). Home Assistant's own target resolution is used; its home and
signature changed between the supported versions (see
extract_referenced_entities)."""
from __future__ import annotations

from typing import Any

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall

# Home Assistant's target resolution changed its home (see
# extract_referenced_entities); which one exists is decided once at import.
try:  # 2025.8+
    from homeassistant.helpers import target as _ha_target
except ImportError:  # up to 2025.7
    _ha_target = None
try:  # up to 2025.12 (removed later)
    from homeassistant.helpers.service import async_extract_referenced_entity_ids as _service_extract
except ImportError:
    _service_extract = None


def extract_referenced_entities(hass: HomeAssistant, target_config: dict[str, Any]):
    """Home Assistant's own resolution of a target (entities, devices, areas,
    floors, labels) for the running version.

    2026.1+: helpers.target with TargetSelection; 2025.8–2025.12: with
    TargetSelectorData; up to 2025.7: helpers.service with a service call
    (its constructor changed in 2025.1, see _service_call).
    Groups are not expanded here (HCL expands light groups itself).
    """
    config = {
        key: target_config[key]
        for key in ("entity_id", "device_id", "area_id", "floor_id", "label_id")
        if target_config.get(key)
    }
    if _ha_target is not None and hasattr(_ha_target, "async_extract_referenced_entity_ids"):
        selection = getattr(_ha_target, "TargetSelection", None) or _ha_target.TargetSelectorData
        return _ha_target.async_extract_referenced_entity_ids(hass, selection(config), expand_group=False)
    return _service_extract(hass, _service_call(hass, config), expand_group=False)


def _service_call(hass: HomeAssistant, data: dict[str, Any]):
    """ServiceCall for the target helper of Home Assistant up to 2025.7.

    2025.1 added hass as first parameter; a positional call with the old
    signature would silently put the target into the wrong field (no target
    at all), so the parameters are passed by name.
    """
    try:
        return ServiceCall(hass=hass, domain="light", service="turn_on", data=data)
    except TypeError:  # up to 2024.12: no hass parameter
        return ServiceCall(domain="light", service="turn_on", data=data)


def resolve_lights(hass: HomeAssistant, target_config: dict[str, Any], groups: set[str] | None = None) -> set[str]:
    """Light entity IDs of a target.

    Entities, devices, areas, floors and labels are resolved by Home
    Assistant's own target resolution of the running version (the same one
    light actions use): hidden and configuration/diagnostic lights reached
    indirectly are skipped, a light with its own area belongs to that area,
    disabled lights are not included, and on versions with child/composite
    devices a device includes them. Lights given directly are always used.
    Light groups are expanded afterwards; raw Hue groups are skipped.

    groups (optional) collects the light groups that were expanded, so the
    caller can watch their member lists.
    """
    selected = extract_referenced_entities(hass, target_config)
    to_process = [
        eid for eid in selected.referenced | selected.indirectly_referenced if eid.startswith("light.")
    ]
    lights: set[str] = set()
    processed: set[str] = set()
    while to_process:
        eid = to_process.pop()
        if eid in processed:
            continue
        processed.add(eid)
        state = hass.states.get(eid)
        if not state:
            if eid.startswith("light."):
                lights.add(eid)
            continue
        members = state.attributes.get(ATTR_ENTITY_ID)
        if members and isinstance(members, (list, tuple, set)):
            to_process.extend(members)
            if groups is not None:
                groups.add(eid)
        elif state.attributes.get("is_hue_group") or state.attributes.get("lights") or state.attributes.get("hue_type"):
            continue
        elif eid.startswith("light."):
            lights.add(eid)
    return lights
