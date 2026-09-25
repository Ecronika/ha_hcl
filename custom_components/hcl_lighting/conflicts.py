"""Detect lights that are controlled by more than one HCL instance (F-08)."""
from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

DATA_CONFLICT_ISSUES = f"{DOMAIN}_conflict_issues"
ISSUE_PREFIX = "light_in_multiple_instances_"


@callback
def async_check_conflicts(hass: HomeAssistant) -> None:
    """Create or remove repair issues for lights in several HCL instances.

    A light counts as a conflict only if at least two active instances (HCL
    switch on) adapt the same attribute (brightness or colour temperature).
    Using one instance for brightness and another for colour is allowed.
    """
    users: dict[str, list[tuple[str, bool, bool]]] = {}
    for core in (hass.data.get(DOMAIN) or {}).values():
        switch = core.get("switch") if isinstance(core, dict) else None
        if switch is None or not switch.is_on:
            continue
        controller = core["controller"]
        for light in switch.resolved_targets:
            users.setdefault(light, []).append(
                (switch.instance_name, controller.adapt_brightness, controller.adapt_color)
            )

    wanted: dict[str, list[str]] = {}
    for light, entries in users.items():
        if len(entries) < 2:
            continue
        brightness = sum(1 for _name, b, _c in entries if b)
        color = sum(1 for _name, _b, c in entries if c)
        if brightness > 1 or color > 1:
            wanted[light] = sorted(name for name, _b, _c in entries)

    known: set[str] = hass.data.setdefault(DATA_CONFLICT_ISSUES, set())
    for light, names in wanted.items():
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"{ISSUE_PREFIX}{light}",
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="light_in_multiple_instances",
            translation_placeholders={"light": light, "instances": ", ".join(names)},
        )
    for light in known - set(wanted):
        ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_PREFIX}{light}")
    known.clear()
    known.update(wanted)
