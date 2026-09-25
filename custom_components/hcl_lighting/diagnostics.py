"""Diagnostics for HCL Lighting (Settings → Devices & services → Download diagnostics)."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Options, targets, light capabilities, manual control and curve of an instance.

    The data contains no credentials; entity IDs and names are kept because
    they are needed to understand the behaviour.
    """
    data: dict[str, Any] = {
        "title": entry.title,
        "data": dict(entry.data),
        "options": {k: v for k, v in entry.options.items() if k != "curve_config"},
        "saved_curve": (entry.options.get("curve_config") or {}).get("points"),
        "loaded": entry.entry_id in (hass.data.get(DOMAIN) or {}),
    }
    core = (hass.data.get(DOMAIN) or {}).get(entry.entry_id)
    if not core:
        return data

    controller = core["controller"]
    manager = core["override_manager"]
    calculator = core["calculator"]
    switch = core.get("switch")
    now = dt_util.now()
    targets = sorted(switch.resolved_targets) if switch else []
    brightness, kelvin = controller.calculate_target_values(now)
    data.update(
        {
            "hcl_active": bool(switch and switch.is_on),
            "scenario": controller.active_mode,
            "adapt_brightness": controller.adapt_brightness,
            "adapt_color": controller.adapt_color,
            "setpoint": {"time": now.isoformat(), "brightness": brightness, "kelvin": kelvin},
            "active_curve": calculator.active_curve,
            "preview_active": calculator.preview_active,
            "targets": targets,
            "lights": {
                eid: {
                    "state": (st := hass.states.get(eid)) and st.state,
                    "supported_color_modes": st and st.attributes.get("supported_color_modes"),
                    "color_mode": st and st.attributes.get("color_mode"),
                    "min_color_temp_kelvin": st and st.attributes.get("min_color_temp_kelvin"),
                    "max_color_temp_kelvin": st and st.attributes.get("max_color_temp_kelvin"),
                    "capability": controller.capability_for(eid, kelvin or 2700),
                    "manual_control": manager.is_overridden(eid),
                    "returning_to_hcl": manager.is_reengaging(eid),
                }
                for eid in targets
            },
            "manual_control": manager.export_overrides(),
        }
    )
    return data
