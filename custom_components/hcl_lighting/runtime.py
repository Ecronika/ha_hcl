"""Runtime data of an HCL instance (entry.runtime_data, RM-T01/RM-T02)."""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

if TYPE_CHECKING:
    from .logic.environmental_controller import EnvironmentalController
    from .logic.hcl_math import HCLCalculator
    from .logic.light_controller import HCLLightController
    from .logic.override_manager import OverrideManager
    from .select import HCLModeSelect
    from .switch import HCLSwitch


@dataclass(frozen=True, slots=True)
class AppliedConfig:
    """What a setup reads from its entry (see update_listener): a change of
    anything but the curve reloads the entry."""

    title: str
    data: dict[str, Any]
    options: dict[str, Any]
    curve: dict[str, Any] | None


@dataclass(slots=True)
class HCLRuntimeData:
    """The logic of a loaded instance, shared by its entities and actions."""

    calculator: HCLCalculator
    controller: HCLLightController
    override_manager: OverrideManager
    applied_config: AppliedConfig
    environment: EnvironmentalController  # RM-E01 (also controller.environment)
    # set by the platforms (also for a disabled entity: see HCLSwitch.is_added, RM-B38)
    switch: HCLSwitch | None = None
    mode_select: HCLModeSelect | None = None


type HCLConfigEntry = ConfigEntry[HCLRuntimeData]


def loaded_runtime(hass: HomeAssistant, entry_id: str | None) -> HCLRuntimeData | None:
    """Runtime data of a loaded instance, else None (unknown, not loaded, unloaded)."""
    entry = hass.config_entries.async_get_entry(entry_id) if entry_id else None
    if entry is None or entry.domain != DOMAIN:
        return None
    runtime = getattr(entry, "runtime_data", None)
    return runtime if isinstance(runtime, HCLRuntimeData) else None


def loaded_runtimes(hass: HomeAssistant) -> Iterator[HCLRuntimeData]:
    """Runtime data of all loaded instances."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime = getattr(entry, "runtime_data", None)
        if isinstance(runtime, HCLRuntimeData):
            yield runtime
