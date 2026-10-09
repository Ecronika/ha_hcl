"""Test double for light.turn_on: records commands, can block, release and fail."""
from __future__ import annotations

import asyncio

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError


def _entities(call: ServiceCall) -> list[str]:
    ids = call.data.get("entity_id") or []
    return [ids] if isinstance(ids, str) else list(ids)


class FakeLights:
    """Replaces the light.turn_on service.

    - calls / events: every call; ("start" | "error" | "end", data) per call
    - gate: an asyncio.Event the next call waits for (only that call)
    - fail: lights whose commands fail at once
    - hang: per light an asyncio.Event its commands wait for (release())
    - fail_late: hanging lights whose command fails when released
    - applied: lights a command was applied to - like Home Assistant, a
      command for several lights is applied to all lights that do not fail
      and raises the first error afterwards
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.calls: list[ServiceCall] = []
        self.events: list[tuple[str, dict]] = []
        self.gate: asyncio.Event | None = None
        self.fail: set[str] = set()
        self.hang: dict[str, asyncio.Event] = {}
        self.fail_late: set[str] = set()
        self.applied: list[str] = []
        hass.services.async_register("light", "turn_on", self._handle)

    async def _handle(self, call: ServiceCall) -> None:
        self.calls.append(call)
        data = dict(call.data)
        entities = _entities(call)
        self.applied.extend(e for e in entities if e not in self.fail)
        self.events.append(("start", data))
        if self.gate is not None:
            gate, self.gate = self.gate, None  # only the next call waits
            await gate.wait()
        for eid in entities:
            if eid in self.hang:
                await self.hang[eid].wait()
                if eid in self.fail_late:
                    raise HomeAssistantError(f"late device error {eid}")
        if self.fail & set(entities):
            self.events.append(("error", data))
            raise HomeAssistantError(f"device error {sorted(self.fail & set(entities))}")
        self.events.append(("end", data))

    def for_light(self, entity_id: str) -> list[ServiceCall]:
        """Calls that include the light."""
        return [c for c in self.calls if entity_id in _entities(c)]

    def release(self) -> None:
        """Let all hanging commands answer."""
        for event in self.hang.values():
            event.set()

    async def wait_for_calls(self, n: int) -> None:
        for _ in range(1000):
            if len(self.calls) >= n:
                return
            await asyncio.sleep(0)  # independent of the (possibly frozen) clock
        raise AssertionError(f"expected {n} light calls, got {len(self.calls)}")
