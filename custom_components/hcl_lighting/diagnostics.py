"""Diagnostics for HCL Lighting (Settings → Devices & services → Download diagnostics)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import REDACTED
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CONF_CURVE_CONFIG, CONF_TARGET, DOMAIN

# Target keys and the prefix of their pseudonyms (entity IDs keep their domain)
_TARGET_KEYS = {"entity_id": None, "device_id": "device", "area_id": "area", "floor_id": "floor", "label_id": "label"}


class _Pseudonyms:
    """Same ID → same pseudonym everywhere in one download (light.redacted_1 …)."""

    def __init__(self) -> None:
        self._names: dict[tuple[str, str], str] = {}
        self._counts: dict[str, int] = {}

    def __call__(self, value: str, kind: str | None = None) -> str:
        prefix = kind or (value.split(".", 1)[0] if "." in value else "entity")
        key = (prefix, value)
        if key not in self._names:
            self._counts[prefix] = self._counts.get(prefix, 0) + 1
            number = self._counts[prefix]
            self._names[key] = f"{prefix}.redacted_{number}" if kind is None else f"{prefix}_{number}"
        return self._names[key]

    def target(self, target: Any) -> Any:
        """A target selection with pseudonyms instead of IDs."""
        if not isinstance(target, dict):
            return target
        out: dict[str, Any] = {}
        for key, value in target.items():
            if key not in _TARGET_KEYS:
                out[key] = value
                continue
            values = [value] if isinstance(value, str) else list(value or [])
            out[key] = [self(str(v), _TARGET_KEYS[key]) for v in values]
        return out


def _settings(values: dict[str, Any], pseudo: _Pseudonyms) -> dict[str, Any]:
    """Entry data or options without name and with pseudonymous targets."""
    out = {k: v for k, v in values.items() if k != CONF_CURVE_CONFIG}
    if CONF_NAME in out:
        out[CONF_NAME] = REDACTED
    if CONF_TARGET in out:
        out[CONF_TARGET] = pseudo.target(out[CONF_TARGET])
    return out


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Options, targets, light capabilities, manual control and curve of an instance.

    Without personal data: the name of the instance is removed, entity, device,
    area, floor and label IDs (room names) are replaced by pseudonyms that are
    the same in all parts of the download, and manual control is given as its
    age in minutes instead of a time. Curve and anchor times stay (needed to
    understand the behaviour).
    """
    pseudo = _Pseudonyms()
    core = (hass.data.get(DOMAIN) or {}).get(entry.entry_id)
    switch = core.get("switch") if core else None
    targets = sorted(switch.resolved_targets) if switch else []
    for eid in targets:  # numbered in a stable order
        pseudo(eid)
    data: dict[str, Any] = {
        "title": REDACTED,
        "data": _settings(dict(entry.data), pseudo),
        "options": _settings(dict(entry.options), pseudo),
        "saved_curve": (entry.options.get(CONF_CURVE_CONFIG) or {}).get("points"),
        "loaded": core is not None,
    }
    if not core:
        return data

    controller = core["controller"]
    manager = core["override_manager"]
    calculator = core["calculator"]
    now = dt_util.now()
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
            "targets": [pseudo(eid) for eid in targets],
            "lights": {
                pseudo(eid): {
                    "state": (st := hass.states.get(eid)) and st.state,
                    "supported_color_modes": st and st.attributes.get("supported_color_modes"),
                    "color_mode": st and st.attributes.get("color_mode"),
                    "min_color_temp_kelvin": st and st.attributes.get("min_color_temp_kelvin"),
                    "max_color_temp_kelvin": st and st.attributes.get("max_color_temp_kelvin"),
                    "capability": controller.capability_for(eid),
                    "manual_control": manager.is_overridden(eid),
                    "returning_to_hcl": manager.is_reengaging(eid),
                }
                for eid in targets
            },
            # minutes since manual control began (no time of day)
            "manual_control_minutes": {
                pseudo(eid): _minutes_since(iso, now)
                for eid, iso in sorted(manager.export_overrides().items())
            },
        }
    )
    return data


def _minutes_since(iso: str, now) -> int | None:
    when = dt_util.parse_datetime(iso)
    return None if when is None else max(0, int((now - when).total_seconds() // 60))
