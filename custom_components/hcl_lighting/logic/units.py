"""Conversions of light values used by the controller and the manual-control
detection (one place, same rounding and limits everywhere, RM-T22)."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from homeassistant.util.color import color_RGB_to_xy, color_temperature_to_rgb


def brightness_pct(brightness: float | None) -> int | None:
    """Brightness 0-255 as percent, rounded and limited (None if unknown)."""
    if brightness is None:
        return None
    return round(min(255, max(0, brightness)) * 100 / 255)


def brightness_byte(pct: float) -> int:
    """Brightness in percent as 0-255."""
    return round(min(100, max(0, pct)) * 255 / 100)


def on_brightness(attrs: Mapping[str, Any]) -> int | None:
    """Brightness 0-255 of a light reported "on" (None: no brightness information).

    "On" with brightness 0 is no state a light can be set to: e.g. a KNX light
    whose brightness status arrives just before or after its switching status
    (RM-B41). It says nothing about the brightness, like a missing value.
    """
    return attrs.get("brightness") or None


def kelvin_to_xy(kelvin: int) -> tuple[float, float]:
    """CIE xy colour of a colour temperature (as HCL sends it to colour lights)."""
    return color_RGB_to_xy(*color_temperature_to_rgb(kelvin))


def xy_distance(xy: Sequence[float] | None, target: Sequence[float] | None) -> float | None:
    """Euclidean distance of two xy colours (None if one is unknown)."""
    if not xy or not target:
        return None
    return ((xy[0] - target[0]) ** 2 + (xy[1] - target[1]) ** 2) ** 0.5
