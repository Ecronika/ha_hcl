"""Scheduling of the update cycles of an HCL instance (RM-T04).

One update at a time: the periodic timer, requested updates (scenario change,
curve preview, release of manual control, HCL switched on) and actions such as
apply share one lock (RM-B01, RM-B02, RM-B20). The timer skips a tick while an
update is running; requests are never dropped - they wait and are combined
into one cycle with the newest values.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

# One cycle: (context of the request that caused it, end running transition
# protections first); the caller holds the lock
CycleRunner = Callable[[Context | None, bool], Awaitable[None]]


class HCLUpdateScheduler:
    """Periodic and requested update cycles, serialised by one lock."""

    def __init__(self, hass: HomeAssistant, interval: float, run_cycle: CycleRunner) -> None:
        self._hass = hass
        self._interval = timedelta(seconds=interval)
        self._run_cycle = run_cycle
        self._lock = asyncio.Lock()
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._requested = False
        self._request_context: Context | None = None
        # New target values (scenario, curve, HCL switched on) end running
        # transition protections - in request order, i.e. only when the
        # requested cycle holds the lock (an older apply or cycle may still
        # set a protection)
        self._end_protection = False
        self.running = False

    @property
    def busy(self) -> bool:
        """Whether a cycle, a waiting request or an action holds the lock."""
        return self._lock.locked()

    def start(self) -> None:
        """Start the periodic cycles (HCL switched on)."""
        self.running = True
        if self._unsub_timer is None:
            self._unsub_timer = async_track_time_interval(self._hass, self.tick, self._interval)

    def stop(self) -> None:
        """Stop the periodic cycles; requests are ignored until started again."""
        self.running = False
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    def end_protections(self) -> None:
        """The next cycle ends running transition protections first."""
        self._end_protection = True

    async def tick(self, _now: datetime | None = None) -> None:
        """Periodic cycle (timer): skipped while an update is running."""
        if not self.running:
            return
        if self._lock.locked():
            _LOGGER.debug("Periodic update skipped: previous update still running")
            return
        async with self._lock:
            await self._cycle()

    async def request(self, context: Context | None = None) -> None:
        """Run a cycle now; waits for a running one, requests are combined."""
        if not self.running:
            return
        self._requested = True
        if context is not None:
            self._request_context = context
        async with self._lock:
            if not self._requested:
                return  # a cycle that started after this request covered it
            await self._cycle()

    @asynccontextmanager
    async def exclusive(self) -> AsyncIterator[None]:
        """Hold the lock for an action (e.g. apply) between the cycles."""
        async with self._lock:
            yield

    async def _cycle(self) -> None:
        self._requested = False
        context, self._request_context = self._request_context, None
        end_protection, self._end_protection = self._end_protection, False
        await self._run_cycle(context, end_protection)
