"""Logbook entries for HCL Lighting (why a light is not following the curve)."""
from __future__ import annotations

from collections.abc import Callable

from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN, EVENT_MANUAL_CONTROL

_MESSAGES = {
    "de": ("manuelle Steuerung – HCL pausiert dieses Licht", "folgt wieder HCL"),
    "en": ("manual control – HCL pauses this light", "follows HCL again"),
}


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    """Describe the manual-control events of HCL Lighting."""

    @callback
    def _describe(event: Event) -> dict[str, str]:
        language = (hass.config.language or "en").split("-")[0]
        started, ended = _MESSAGES.get(language, _MESSAGES["en"])
        data = event.data
        return {
            "name": f"HCL {data.get('instance', '')}".strip(),
            "message": started if data.get("manual_control") else ended,
            "entity_id": data.get("entity_id"),
        }

    async_describe_event(DOMAIN, EVENT_MANUAL_CONTROL, _describe)
