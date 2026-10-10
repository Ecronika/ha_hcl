"""Controller for interacting with Light entities."""
from __future__ import annotations

import logging
import asyncio
import itertools
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, NamedTuple

import time

from homeassistant.core import Context, HomeAssistant
from homeassistant.components.light import (
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_COLOR_TEMP_KELVIN,
    ColorMode
)
from homeassistant.util.color import (
    color_xy_to_temperature,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_ON,
)

from ..const import (
    CONF_SMART_TRANSITION,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    REENGAGE_TRANSITION_SECONDS,
    BRIGHTNESS_THRESHOLD,
    KELVIN_THRESHOLD,
    XY_COLOR_SENSITIVITY,
    KELVIN_RANGE,
    MODE_AUTO,
    MODE_GUEST,
    MODE_SLEEP,
    SCENARIO_DEFAULTS,
    CONF_MIN_BRIGHTNESS,
    CONF_MAX_BRIGHTNESS,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_MAX_BRIGHTNESS,
    XY_COLOR_DISTANCE_THRESHOLD,
    CONFIGURABLE_SCENARIOS,
    LIMITABLE_SCENARIOS,
    OWN_CONTEXT_SECONDS,
    COMMAND_TIMEOUT_SECONDS,
    IGNORE_WINDOW_SECONDS,
    DOMAIN,
    scenario_option_keys,
)

from ..logic.hcl_math import HCLCalculator

from .daylight_compensation import DAYLIGHT_KEY
from .environmental_controller import EnvironmentalContext, EnvironmentalController, EnvironmentalResult, HCLSetpoint
from .override_manager import OverrideManager, Tracking
from .targets import resolve_lights
from .units import brightness_byte, brightness_pct, kelvin_to_xy, xy_distance

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class BatchResult:
    """Result of apply_batch.

    updated: lights whose command succeeded (fast mode: whose command was sent).
    failed: lights whose command raised an error, with the error.
    pending: lights without an answer - the command did not finish within
    COMMAND_TIMEOUT_SECONDS (it keeps running) or an earlier one is still
    running (no second command is sent).
    Lights without a command (already at the values) are in none of them.
    """

    updated: list[str] = field(default_factory=list)
    failed: dict[str, BaseException] = field(default_factory=dict)
    pending: list[str] = field(default_factory=list)

class CommandTracker:
    """Light commands of one HCL instance; kept across reloads of the entry.

    A command can outlive the controller that sent it (it may answer only
    after COMMAND_TIMEOUT_SECONDS, see apply_batch, and a reload creates a new
    controller). Its context must still be recognised as HCL's own, the light
    must not get a second command while it runs, and a late failure must not
    roll back tracking values a newer command has set since.
    """

    def __init__(self) -> None:
        # Contexts of the commands ({context_id: monotonic time}) and the same
        # contexts oldest first, so expired ones are removed from the front
        self.contexts: dict[str, float] = {}
        self.context_order: deque[tuple[float, str]] = deque()
        # Lights with a command still running
        self.in_flight: set[str] = set()
        # Lights whose last command failed (logged once until they answer
        # again, RM-B39)
        self.failing: set[str] = set()
        # Lights whose two-step command (compatibility mode) failed and got
        # the values without transition (logged once per streak, RM-B47)
        self.smart_fallback: set[str] = set()
        # Number of the command that last set the tracking values of a light
        self._latest: dict[str, int] = {}
        self._numbers = itertools.count(1)

    def claim(self, entity_id: str) -> int:
        """A command sets the tracking values of a light; returns its number."""
        number = next(self._numbers)
        self._latest[entity_id] = number
        return number

    def is_latest(self, entity_id: str, number: int) -> bool:
        """True if no newer command has set the tracking values of the light."""
        return self._latest.get(entity_id) == number

    def prune(self, valid_entity_ids: set[str]) -> None:
        """Forget lights that are no longer controlled."""
        for entity_id in [eid for eid in self._latest if eid not in valid_entity_ids]:
            del self._latest[entity_id]
        self.failing &= valid_entity_ids
        self.smart_fallback &= valid_entity_ids


# Colour modes HCL drives through the XY simulation (Home Assistant converts
# xy_color to the light's own mode, including RGBW and RGBWW)
_COLOR_MODES = (ColorMode.XY, ColorMode.HS, ColorMode.RGB, ColorMode.RGBW, ColorMode.RGBWW)

# How a light is driven: native colour temperature, colour through the XY
# simulation, brightness only, on/off only
Capability = Literal["ct", "xy_sim", "dim", "onoff"]


class _CachedCapability(NamedTuple):
    signature: tuple[Any, Any, Any]  # supported colour modes, min/max kelvin
    type: Capability


def _native_capability(state) -> Capability:
    """Native capability of a light from its attributes (ct, xy_sim, dim, onoff)."""
    modes = state.attributes.get(ATTR_SUPPORTED_COLOR_MODES)
    if not isinstance(modes, (list, tuple)) or not modes:
        modes = ()
    supports_color = any(mode in modes for mode in _COLOR_MODES)
    if ColorMode.COLOR_TEMP in modes:
        cap_type = "ct"
    elif supports_color:
        cap_type = "xy_sim"
    elif ColorMode.BRIGHTNESS in modes or (modes and ColorMode.ONOFF not in modes):
        cap_type = "dim"
    else:
        cap_type = "onoff"
    return cap_type


class HCLLightController:
    """Controller for applying HCL settings to lights."""

    def __init__(
        self,
        hass: HomeAssistant,
        override_manager: OverrideManager,
        hcl_calc: HCLCalculator,
        config_entry,
        commands: CommandTracker | None = None,
    ):
        self.hass = hass
        self.override_manager = override_manager
        self.hcl_calc = hcl_calc
        self.config_entry = config_entry
        self._capability_cache: dict[str, _CachedCapability] = {}
        
        # State Machine
        self.active_mode = MODE_AUTO
        # Set when the scenario changed; the next update uses the scenario transition
        self._mode_change_pending = False

        # Adaptation switches (brightness / colour temperature)
        self._adapt_brightness = True
        self._adapt_color = True

        # Commands of this instance, shared with the controllers of earlier
        # setups of the entry (a command may outlive a reload)
        self.commands = commands if commands is not None else CommandTracker()
        # Contexts of the service calls HCL sends ({context_id: monotonic time})
        # and the same contexts oldest first (see CommandTracker)
        self._own_contexts = self.commands.contexts
        self._own_context_order = self.commands.context_order
        # Lights with a command still running (a light that does not answer
        # gets no second command until the first one has finished)
        self._in_flight = self.commands.in_flight

        # Environmental features (RM-E01): base -> effective setpoint. Without
        # a configured feature the effective setpoint is the base.
        self.environment = EnvironmentalController()
        self.daylight_store = None  # DaylightCapStore when the daylight compensation is on
        self.environment_sensor: str | None = None  # lux sensor of the daylight compensation
        # Whether HCL is active (main switch on): no environmental step while off
        self.hcl_active = False
        # light counts of the last cycle: peek() shows the same hold as the cycle
        self._cycle_lights: dict[str, Any] = {}

    @property
    def adapt_brightness(self) -> bool:
        """Whether HCL controls the brightness."""
        return self._adapt_brightness

    @adapt_brightness.setter
    def adapt_brightness(self, value: bool) -> None:
        self._adapt_brightness = bool(value)
        self.override_manager.track_brightness = self._adapt_brightness

    @property
    def adapt_color(self) -> bool:
        """Whether HCL controls the colour temperature."""
        return self._adapt_color

    @adapt_color.setter
    def adapt_color(self, value: bool) -> None:
        self._adapt_color = bool(value)
        self.override_manager.track_color = self._adapt_color

    def is_own_context(self, context: Context | None) -> bool:
        """Return True if a context belongs to a service call sent by HCL."""
        if context is None:
            return False
        return context.id in self._own_contexts or (
            context.parent_id is not None and context.parent_id in self._own_contexts
        )

    def _new_context(self, parent: Context | None = None) -> Context:
        """New context for an HCL command.

        parent: context of the request that caused the command (service call,
        scenario change). It is linked as parent_id, like automations and
        scripts do, so logbook and traces show the origin. The user of that
        request is kept (user_id): the command runs with the user's
        permissions, as Home Assistant's own actions do. Commands of the
        periodic updates have no parent and no user.
        """
        now = time.monotonic()
        # Contexts are only needed while the resulting state changes arrive
        order = self._own_context_order
        while order and now - order[0][0] > OWN_CONTEXT_SECONDS:
            del self._own_contexts[order.popleft()[1]]
        if parent is None:
            context = Context()
        else:
            context = Context(user_id=parent.user_id, parent_id=parent.id)
        self._own_contexts[context.id] = now
        order.append((now, context.id))
        return context

    _BRIGHTNESS_KEYS = ("brightness_pct",)
    _COLOR_KEYS = ("color_temp_kelvin", "xy_color")

    def _filter_service_data(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Drop the attributes HCL must not adapt; None if nothing is left to send.

        Brightness 0 (Sleep mode switches lights off) is always kept.
        """
        data = dict(data)
        if not self._adapt_brightness and data.get("brightness_pct") != 0:
            for key in self._BRIGHTNESS_KEYS:
                data.pop(key, None)
        if not self._adapt_color:
            for key in self._COLOR_KEYS:
                data.pop(key, None)
        if not any(key in data for key in self._BRIGHTNESS_KEYS + self._COLOR_KEYS):
            return None
        return data

    async def _async_call(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
        blocking: bool = False,
        parent: Context | None = None,
    ) -> bool:
        """Send a light command with an HCL context (only the adapted attributes).

        Returns True when a command was sent, False when nothing was left to
        send. Errors of the command are raised to the caller.
        """
        data = self._filter_service_data(data)
        if data is None:
            return False
        entities = data.get("entity_id")
        if isinstance(entities, list) and len(entities) == 1:
            entities = entities[0]
        if isinstance(entities, str) and "color_temp_kelvin" in data:
            # proof for RM-B43: this light gets colour temperature (restored with
            # the tracking if the command fails, RM-B46)
            self.override_manager.mark_ct_sent(entities, data["color_temp_kelvin"])
        await self.hass.services.async_call(
            domain, service, data, blocking=blocking, context=self._new_context(parent)
        )
        return True
        
    def set_active_mode(self, mode: str, announce: bool = True) -> None:
        """Set the active scenario mode.

        announce=False (restore at startup/reload): the next update is not
        treated as a scenario change (normal transition).
        """
        if self.active_mode == mode:
            return
            
        self.active_mode = mode
        if announce:
            self._mode_change_pending = True
        _LOGGER.debug("HCL Mode changed to: %s", mode)
        # The caller (scenario select, set_scenario) requests the update

    def calculate_target_values(self, now) -> tuple[int | None, int | None]:
        """The effective setpoint now (brightness %, kelvin): the base of the
        curve or scenario with the environmental features of the last update
        cycle (peek: nothing is advanced, RM-E01). Used by apply, Fast-HCL,
        the target sensors and the diagnostics."""
        result = self.target_result(now)
        if result is None:
            return self.calculate_base_values(now)
        return result.effective.brightness, result.effective.kelvin

    def target_result(self, now) -> EnvironmentalResult | None:
        """Environmental snapshot for now (peek); None without a feature or in Guest."""
        brightness, kelvin = self.calculate_base_values(now)
        if not self.environment.enabled or brightness is None:
            return None
        lights = {k: v for k, v in self._cycle_lights.items() if k != "seed_brightness"}
        return self.environment.peek(now, HCLSetpoint(brightness, kelvin), self.environment_context(**lights))

    def step_target_values(self, now, **lights: Any) -> tuple[int | None, int | None]:
        """The effective setpoint of a regular update cycle: the environmental
        features are advanced once (step, under the update lock, RM-E01).
        lights: light counts and seed of the cycle (see EnvironmentalContext)."""
        brightness, kelvin = self.calculate_base_values(now)
        self._cycle_lights = dict(lights)
        if not self.environment.enabled or brightness is None:
            return brightness, kelvin
        result = self.environment.step(now, HCLSetpoint(brightness, kelvin), self.environment_context(**lights))
        if self.daylight_store is not None:
            snapshot = result.modifier(DAYLIGHT_KEY)
            if snapshot is not None:
                self.daylight_store.note(self.environment.state(DAYLIGHT_KEY), snapshot.status, now)
        return result.effective.brightness, result.effective.kelvin

    def environment_context(self, **lights: Any) -> EnvironmentalContext:
        """What the environmental features know about this instance now."""
        min_b, max_b = self.brightness_limits()
        options = self.config_entry.options
        return EnvironmentalContext(
            mode=self.active_mode,
            hcl_active=self.hcl_active,
            adapt_brightness=self._adapt_brightness,
            adapt_color=self._adapt_color,
            update_interval=float(options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)),
            min_brightness=int(min_b),
            max_brightness=int(max_b),
            **lights,
        )

    def command_source(self) -> str:
        """Source of the values of the current mode: the Auto path or a scenario."""
        return "auto" if self.active_mode == MODE_AUTO else "scenario"

    def calculate_base_values(self, now) -> tuple[int | None, int | None]:
        """
        Base setpoint (Brightness, Kelvin) based on Priority Stack.
        User Intent > Curve.
        """
        
        # 1. GUEST MODE (Freeze)
        if self.active_mode == MODE_GUEST:
            return None, None

        # 2. FIXED SCENARIOS
        if self.active_mode in SCENARIO_DEFAULTS:
            # Special Handling: Sleep (Off)
            if self.active_mode == MODE_SLEEP:
                return 0, 2000 # Off, but pre-heat to 2000K
                
            return self.scenario_setpoint(self.active_mode)

        # 3. AUTO MODE (Curve)
        if self.active_mode == MODE_AUTO:
            min_b, max_b = self.brightness_limits()
            return self.hcl_calc.get_hcl_values(now, min_b, max_b)
            
        # Fallback
        return None, None

    def consume_mode_change(self) -> bool:
        """True once after a scenario change (for the scenario transition)."""
        pending = self._mode_change_pending
        self._mode_change_pending = False
        return pending

    def scenario_setpoint(self, mode: str) -> tuple[int, int]:
        """Brightness and colour temperature of a fixed scenario (options, limits)."""
        settings = SCENARIO_DEFAULTS[mode]
        options = self.config_entry.options
        brightness, kelvin = settings["brightness"], settings["kelvin"]
        if mode in CONFIGURABLE_SCENARIOS:
            key_b, key_k = scenario_option_keys(mode)
            brightness = int(options.get(key_b, brightness))
            kelvin = int(options.get(key_k, kelvin))
        # Focus/Relax/Cleaning stay within the min/max brightness (the night
        # modes are meant to be darker than any daytime minimum)
        if mode in LIMITABLE_SCENARIOS:
            min_b, max_b = self.brightness_limits()
            brightness = max(min_b, min(max_b, brightness))
        return brightness, kelvin

    def scenario_values(self) -> dict[str, dict[str, int]]:
        """Values of all scenarios with fixed values (for the card)."""
        return {
            mode: dict(zip(("b", "k"), self.scenario_setpoint(mode)))
            for mode, settings in SCENARIO_DEFAULTS.items()
            if settings["brightness"] is not None
        }

    def brightness_limits(self) -> tuple[int, int]:
        """Configured min/max brightness of the curve."""
        options = self.config_entry.options
        return (
            options.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS),
            options.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS),
        )

    def prune_cache(self, valid_entity_ids: set[str]) -> None:
        """Prune capability cache of invalid/removed entities."""
        # Prune main cache
        to_remove = [eid for eid in self._capability_cache if eid not in valid_entity_ids]
        for eid in to_remove:
            del self._capability_cache[eid]
        self.commands.prune(valid_entity_ids)

            
        if to_remove:
            _LOGGER.debug("Pruned %d stale entities from capability cache", len(to_remove))

    async def apply_batch(
        self,
        lights: list[str],
        brightness: int,
        kelvin: int,
        transition: float | None = None,
        fast_mode: bool = False,
        parent: Context | None = None,
        on_failure: Callable[[list[str]], None] | None = None,
        source: str | None = None,
    ) -> BatchResult:
        """Apply settings to a batch of lights (one command per light, in parallel).

        Each light gets its own command: Home Assistant runs a command for
        several lights for all of them and raises the first error afterwards,
        so the lights of a shared command could not be told apart.

        A light whose command failed (or was not sent) gets its previous
        tracking values and ignore window back, so the manual-control
        detection does not use values the light never received.

        fast_mode: the commands run in the background (the caller does not
        wait); result.updated holds the lights a command was sent to, and
        on_failure is called with the lights whose command failed later.
        """
        result = BatchResult()
        if not lights:
            return result

        transition_val = 0 if transition is None else transition
        smart_transition = self.config_entry.options.get(CONF_SMART_TRANSITION, False)
        bulk = transition_val == 0 or not smart_transition
        xy = kelvin_to_xy(kelvin)

        # tracking before the command and the number of the command
        previous: dict[str, tuple[Tracking, int]] = {}
        # (light, command)
        jobs: list[tuple[str, Awaitable[bool]]] = []

        for entity_id in lights:
            if entity_id in self._in_flight:
                result.pending.append(entity_id)
                continue
            # Check thresholds to avoid redundant traffic
            if not self._needs_update(entity_id, brightness, kelvin):
                continue
            cap_type = self._get_capability(entity_id)
            data: dict[str, Any] = {"entity_id": [entity_id], "brightness_pct": brightness, "transition": transition_val}
            if cap_type == "ct":
                # Native colour temperature: the value the light can reach
                tracked_kelvin = self.reachable_kelvin(entity_id, kelvin)
                data["color_temp_kelvin"] = tracked_kelvin
                job = (
                    self._async_call("light", "turn_on", data, blocking=True, parent=parent)
                    if bulk else self._apply_smart_ct_single(entity_id, tracked_kelvin, brightness, transition_val, parent)
                )
            elif cap_type == "xy_sim":
                tracked_kelvin = kelvin
                data["xy_color"] = xy
                job = (
                    self._async_call("light", "turn_on", data, blocking=True, parent=parent)
                    if bulk else self._apply_smart_xy_single(entity_id, xy[0], xy[1], brightness, transition_val, parent)
                )
            elif cap_type == "dim":
                tracked_kelvin = kelvin
                job = self._async_call("light", "turn_on", data, blocking=True, parent=parent)
            else:
                continue
            # Tracking is set before sending (state reports may arrive at once);
            # a failed command restores it.
            previous[entity_id] = (
                self.override_manager.tracking_snapshot(entity_id),
                self.commands.claim(entity_id),
            )
            self.override_manager.set_last_set_values(
                entity_id, brightness, tracked_kelvin, start=self.hass.states.get(entity_id),
                source=source or self.command_source(),
            )
            self.override_manager.set_ignore_window(entity_id, transition_val)
            jobs.append((entity_id, job))

        if not jobs:
            return result

        if fast_mode:
            for entity_id, job in jobs:
                # Background task (like the other commands): a light that
                # hangs does not hold Home Assistant's own waiting for tasks
                task = self.hass.async_create_background_task(job, f"{DOMAIN} light command {entity_id}")
                self._track_in_flight(task, entity_id)
                task.add_done_callback(
                    lambda t, eid=entity_id: self._background_result(t, eid, previous[eid], on_failure)
                )
                result.updated.append(entity_id)
            return result

        # The caller holds the update lock: wait at most COMMAND_TIMEOUT_SECONDS.
        # Commands are not cancelled (an interrupted turn_on of an integration
        # is worse than a late one); a late one is handled like a fast-mode
        # command. Background tasks: a light that hangs does not block
        # Home Assistant's own waiting for tasks (e.g. at startup).
        tasks: dict[asyncio.Task, str] = {}
        for entity_id, job in jobs:
            # Not started eagerly: all commands start together, as before
            task = self.hass.async_create_background_task(
                job, f"{DOMAIN} light command {entity_id}", eager_start=False
            )
            self._track_in_flight(task, entity_id)
            tasks[task] = entity_id
        try:
            done, late = await asyncio.wait(tasks, timeout=COMMAND_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            # The update itself is cancelled (unload, shutdown): the commands
            # finish on their own, their results are handled like fast mode
            for task, entity_id in tasks.items():
                task.add_done_callback(
                    lambda t, eid=entity_id: self._background_result(t, eid, previous[eid], on_failure)
                )
            raise
        for task in done:
            entity_id = tasks[task]
            error = task.exception() if not task.cancelled() else asyncio.CancelledError()
            if error is None and task.result() is True:
                result.updated.append(entity_id)
                self._report_success(entity_id)
                continue
            if error is not None:
                self._report_failure(entity_id, error)
                result.failed[entity_id] = error
            self._restore_tracking(entity_id, previous[entity_id])
        for task in late:
            entity_id = tasks[task]
            _LOGGER.warning(
                "Light %s did not answer within %s s; HCL goes on without waiting "
                "(no further command to it until this one has finished)",
                entity_id, COMMAND_TIMEOUT_SECONDS,
            )
            # The values may still arrive: tracking and context stay. A late
            # error restores the tracking like a failed fast-mode command.
            task.add_done_callback(
                lambda t, eid=entity_id: self._background_result(t, eid, previous[eid], on_failure)
            )
            result.pending.append(entity_id)
        return result

    def _report_failure(self, entity_id: str, error: BaseException) -> None:
        """Log a failed light command: once as a warning, repeats at debug level (RM-B39).

        A light that keeps failing is tried again every update; the log gets
        one entry when it starts failing and one when it answers again.
        """
        if entity_id not in self.commands.failing:
            self.commands.failing.add(entity_id)
            _LOGGER.warning(
                "Light update for %s failed: %s (repeated failures are logged at debug "
                "level until the light accepts commands again)", entity_id, error,
            )
        _LOGGER.debug("Light update for %s failed", entity_id, exc_info=error)

    def _report_success(self, entity_id: str) -> None:
        """A light accepted a command: end of a failure streak (RM-B39)."""
        if entity_id in self.commands.failing:
            self.commands.failing.discard(entity_id)
            _LOGGER.info("Light %s accepts HCL commands again", entity_id)

    def _track_in_flight(self, task: asyncio.Task, entity_id: str) -> None:
        """Remember a running command until it has finished."""
        self._in_flight.add(entity_id)
        task.add_done_callback(lambda _t, eid=entity_id: self._in_flight.discard(eid))

    def _restore_tracking(self, entity_id: str, previous: tuple[Tracking, int]) -> bool:
        """Roll back the tracking of a command that was not sent or failed.

        Only if no newer command (also of a controller set up after a reload)
        has set the tracking values since: those belong to the newer command.
        Returns True if rolled back.
        """
        snapshot, number = previous
        if not self.commands.is_latest(entity_id, number):
            _LOGGER.debug("Tracking of %s kept: a newer command has set it", entity_id)
            return False
        self.override_manager.restore_tracking(entity_id, snapshot)
        return True

    def _background_result(
        self,
        task: asyncio.Task,
        entity_id: str,
        previous: tuple[Tracking, int],
        on_failure: Callable[[list[str]], None] | None,
    ) -> None:
        """Result of a command HCL did not wait for (fast mode, late or cancelled)."""
        if task.cancelled():
            # Home Assistant stops: no error message
            error: BaseException | None = None
        else:
            error = task.exception()
            if error is None and task.result() is True:
                self._report_success(entity_id)
                return
        if error is not None:
            self._report_failure(entity_id, error)
        # A newer command owns the light: its tracking and protection stay
        if self._restore_tracking(entity_id, previous) and on_failure is not None:
            on_failure([entity_id])

    async def apply_fast(
        self,
        entity_id: str,
        brightness: int,
        kelvin: int,
        state_obj=None,
    ) -> bool:
        """Fast-HCL for a light that was switched on (True if a command was started).

        The values are sent without transition (RM-R10). The tracking values
        and the ignore window are set before the command starts (so the first
        state report of the light is not taken for manual control). The
        command runs in the background like all other light commands
        (RM-T17): Home Assistant does not wait for it, the light gets no
        second command while it runs, and a failure restores the tracking
        (unless a newer command has set it since). A light with a command
        still running gets no Fast-HCL command.
        """
        _LOGGER.debug("Applying Fast-HCL to %s (B:%s%%, K:%sK)", entity_id, brightness, kelvin)

        # Use passed state object or fallback to lookup (performance optimization)
        state = state_obj or self.hass.states.get(entity_id)
        if state is None:
            return False
        if self._is_group(entity_id, state):
            _LOGGER.debug("Ignoring Fast-HCL for Group/Hue Group: %s", entity_id)
            return False
        if entity_id in self._in_flight:
            _LOGGER.debug("No Fast-HCL for %s: a command to it is still running", entity_id)
            return False

        cap_type = self._get_capability(entity_id, state)
        service_data = {"entity_id": entity_id, "brightness_pct": brightness, "transition": 0}
        tracked_kelvin = kelvin
        if cap_type == "ct":
            tracked_kelvin = self.reachable_kelvin(entity_id, kelvin, state)
            service_data["color_temp_kelvin"] = tracked_kelvin
        elif cap_type == "xy_sim":
            service_data["xy_color"] = kelvin_to_xy(kelvin)
        elif cap_type != "dim":
            return False  # onoff or unknown
        if self._filter_service_data(service_data) is None:
            return False  # nothing HCL adapts

        previous = (self.override_manager.tracking_snapshot(entity_id), self.commands.claim(entity_id))
        self.override_manager.set_last_set_values(
            entity_id, brightness, tracked_kelvin, start=state, source=self.command_source()
        )
        self.override_manager.set_ignore_window(entity_id, IGNORE_WINDOW_SECONDS)
        task = self.hass.async_create_background_task(
            self._async_call("light", "turn_on", service_data, blocking=True),
            f"{DOMAIN} light command {entity_id}",
        )
        if task.done():
            # finished while starting (eager start): result at once
            self._background_result(task, entity_id, previous, None)
        else:
            self._track_in_flight(task, entity_id)
            task.add_done_callback(
                lambda t: self._background_result(t, entity_id, previous, None)
            )
        return True

    async def reengage_light(
        self, entity_id: str, target_brightness: int, target_kelvin: int, parent: Context | None = None
    ) -> None:
        """Bring a light back to HCL with one long transition (REENGAGE_TRANSITION_SECONDS).

        The tracking values are set to the target before sending and the
        ignore window covers the transition, so its intermediate values are
        not taken for manual control; the update cycles leave the light alone
        until the transition has ended (set_reengaging).
        """
        _LOGGER.debug("Re-engaging %s (Smooth Transition)", entity_id)
        duration = REENGAGE_TRANSITION_SECONDS

        def _failed(eids: list[str]) -> None:
            # The command failed: the normal updates take the light back
            for eid in eids:
                self.override_manager.end_reengaging(eid)

        result = await self.apply_batch(
            [entity_id], 
            target_brightness, 
            target_kelvin, 
            transition=duration,
            fast_mode=True,  # Don't block main loop
            parent=parent,
            on_failure=_failed,
        )
        # Normal update cycles must not cut the smooth transition short
        if entity_id in result.updated:
            self.override_manager.set_reengaging(entity_id, duration)

    def capability_for(self, entity_id: str) -> Capability:
        """How a light is driven (ct, xy_sim, dim, onoff)."""
        return self._get_capability(entity_id)

    def _get_capability(self, entity_id: str, state_obj=None) -> Capability:
        """Determine how a light is driven.

        The native capability of a light that is on is cached together with
        the attributes it is based on and evaluated again as soon as the light
        reports other ones (e.g. capabilities reported late, RM-B36). A light
        that is off or unavailable uses the cache, without one its current
        attributes. A light with colour temperature is always driven by it,
        limited to its range; only lights without colour temperature get the
        XY simulation (RM-R09: no colour jump at the range limit, no RGB white).
        """
        state = state_obj or self.hass.states.get(entity_id)
        cached = self._capability_cache.get(entity_id)
        if state is not None and state.state == STATE_ON:
            attrs = state.attributes
            modes = attrs.get(ATTR_SUPPORTED_COLOR_MODES)
            signature = (
                tuple(modes) if isinstance(modes, (list, tuple)) else modes,
                attrs.get("min_color_temp_kelvin"),
                attrs.get("max_color_temp_kelvin"),
            )
            if cached is None or cached.signature != signature:
                cached = _CachedCapability(signature, _native_capability(state))
                self._capability_cache[entity_id] = cached
                _LOGGER.debug("Capability of %s: %s (modes=%s)", entity_id, cached.type, modes)
        elif cached is None:
            if state is None:
                return "onoff"  # not loaded yet
            return _native_capability(state)

        return cached.type

    def _needs_update(self, entity_id: str, target_b: int, target_k: int) -> bool:
        """Check if an update is needed based on thresholds."""
        state = self.hass.states.get(entity_id)
        if not state:
            return True

        # Current State
        curr_b = state.attributes.get("brightness")
        # Use ROUND instead of INT truncation to prevent off-by-one ping-pong loops
        # e.g. 50% = 127.5 -> round(128) vs int(127).
        # Fix verified: One single source of truth for brightness percentage.
        curr_b_pct = brightness_pct(curr_b)
        curr_k = state.attributes.get(ATTR_COLOR_TEMP_KELVIN)
        
        # Safety Check: Ignore Groups (Hue Groups or HA Groups)
        # Groups shouldn't be in the list, but if they sneak in (e.g. startup race),
        # we strictly ignore them here to avoid "Double Control".
        if self._is_group(entity_id):
            return False

        # Only the adapted attributes count (brightness 0 = Sleep switches off)
        check_b = self._adapt_brightness or target_b == 0
        check_k = self._adapt_color
        if not check_b and not check_k:
            return False

        # Check Brightness
        delta_b = 0
        if not check_b:
            pass
        elif curr_b is not None:
             delta_b = abs(curr_b_pct - target_b)
        else:
            # Unknown brightness, assume update needed
            return True
            
        # Check Kelvin (if supported)
        delta_k = 0
        if not check_k:
            pass
        elif curr_k is not None:
             # Compare with what the light can reach: a CT light clamps the
             # target to its own range and reports the clamped value.
             delta_k = abs(curr_k - self.reachable_kelvin(entity_id, target_k, state))
        elif (capability := self._get_capability(entity_id)) in ("ct", "xy_sim"):
             # Light is in a colour mode (no colour_temp is reported).
             expected_k = self.reachable_kelvin(entity_id, target_k, state)
             if capability == "ct" and not self._sent_kelvin(entity_id, expected_k):
                 # A light with colour temperature is driven by it (RM-R09):
                 # bring it back from a colour mode (e.g. the XY simulation of
                 # 0.7), once per value - a light that keeps reporting a colour
                 # mode afterwards is compared by its XY colour (RM-B43).
                 return True
             curr_xy = state.attributes.get("xy_color")
             if not curr_xy:
                 return True
             target_x, target_y = kelvin_to_xy(expected_k)
             dist_xy = xy_distance(curr_xy, (target_x, target_y))
             if dist_xy > XY_COLOR_DISTANCE_THRESHOLD:
                 return True
             delta_k = abs(
                 color_xy_to_temperature(curr_xy[0], curr_xy[1])
                 - color_xy_to_temperature(target_x, target_y)
             )
        
        if delta_b <= BRIGHTNESS_THRESHOLD and (delta_k <= KELVIN_THRESHOLD if target_k else True):
             # Logs demoted to TRACE (level 5) to avoid spam
             _LOGGER.log(5, "Skipping update for %s: Change too small (Delta B=%s%%, K=%sK)", entity_id, delta_b, delta_k if target_k else "N/A")
             return False
        
        return True

    def _sent_kelvin(self, entity_id: str, kelvin: int) -> bool:
        """Whether HCL has sent this colour temperature to the light (RM-B46: the
        values a command aims for are not proof, it may carry no colour)."""
        return self.override_manager.ct_sent(entity_id) == kelvin

    def reachable_kelvin(self, entity_id: str, kelvin: int, state_obj=None) -> int:
        """Return the colour temperature a CT light actually shows for a target.

        Lights controlled via native colour temperature clamp the target to
        their min/max range. Lights simulated via XY get the target unchanged.
        """
        state = state_obj or self.hass.states.get(entity_id)
        if state is None or self._get_capability(entity_id, state) != "ct":
            return kelvin
        min_k = state.attributes.get("min_color_temp_kelvin")
        max_k = state.attributes.get("max_color_temp_kelvin")
        if min_k is not None and kelvin < min_k:
            return min_k
        if max_k is not None and kelvin > max_k:
            return max_k
        return kelvin

    def resolve_targets(self, target_config: dict[str, Any], groups: set[str] | None = None) -> set[str]:
        """Light entity IDs of a target (see targets.resolve_lights)."""
        return resolve_lights(self.hass, target_config, groups)

    async def _send_steps(self, entity_id: str, steps: list[dict[str, Any]], parent: Context | None) -> bool:
        """Send the parts of a compatibility-mode command one after the other.

        Each part waits for the device. A later part is only sent if the light
        still wants it: switched off, changed by hand meanwhile (manual
        control) - the user's decision wins over the rest of the command
        (RM-B48). Returns True if a part was sent.
        """
        sent = faded = False
        for number, data in enumerate(steps):
            if number and not self._still_wanted(entity_id):
                _LOGGER.debug("Rest of the command to %s dropped: switched off or changed meanwhile", entity_id)
                break
            if await self._async_call("light", "turn_on", data, blocking=True, parent=parent):
                sent = True
                faded |= bool(data.get("transition"))
        # a part with a transition was accepted: the two-step command works again
        if faded and entity_id in self.commands.smart_fallback:
            self.commands.smart_fallback.discard(entity_id)
            _LOGGER.debug("Smart transition for %s works again", entity_id)
        return sent

    def _still_wanted(self, entity_id: str) -> bool:
        """Whether a further part of a command may go to the light (RM-B48)."""
        state = self.hass.states.get(entity_id)
        return (
            state is not None and state.state == STATE_ON
            and not self.override_manager.is_overridden(entity_id)
        )

    def _report_smart_failure(self, entity_id: str, error: BaseException) -> None:
        """The two-step command failed: logged once per streak (RM-B47); the
        fallback without transition follows (a final failure: RM-B39)."""
        if entity_id in self.commands.smart_fallback:
            _LOGGER.debug("Smart transition for %s failed again (%s)", entity_id, error)
            return
        self.commands.smart_fallback.add(entity_id)
        _LOGGER.warning(
            "Smart transition for %s failed (%s); sending the values without transition "
            "(repeated failures are logged at debug level until it works again)", entity_id, error,
        )

    async def _apply_smart_xy_single(
        self, entity_id, x, y, brightness, transition, parent: Context | None = None
    ) -> bool:
        """Colour and brightness in two steps; the larger change gets the transition.

        If the two-step command fails, the values are sent once without
        transition. If that fails too, the error is raised to apply_batch.
        """
        state = self.hass.states.get(entity_id)
        if not state:
            return False
        try:
            curr_bri = state.attributes.get("brightness") or 0
            curr_xy = state.attributes.get("xy_color") or (x, y)
            target_bri_byte = brightness_byte(brightness)
            delta_b = abs(curr_bri - target_bri_byte) / 255.0
            delta_c = xy_distance(curr_xy, (x, y)) * XY_COLOR_SENSITIVITY

            if delta_c > delta_b:
                steps = [
                    {"entity_id": entity_id, "brightness_pct": brightness, "transition": 0},
                    {"entity_id": entity_id, "xy_color": (x, y), "transition": transition},
                ]
            else:
                steps = [
                    {"entity_id": entity_id, "xy_color": (x, y), "transition": 0},
                    {"entity_id": entity_id, "brightness_pct": brightness, "transition": transition},
                ]
            return await self._send_steps(entity_id, steps, parent)
        except Exception as err:  # noqa: BLE001 - the fallback below reports a final failure
            self._report_smart_failure(entity_id, err)
        if not self._still_wanted(entity_id):
            return False
        return await self._async_call(
            "light", "turn_on",
            {"entity_id": entity_id, "brightness_pct": brightness, "xy_color": (x, y), "transition": 0},
            blocking=True, parent=parent,
        )

    async def _apply_smart_ct_single(
        self, entity_id, kelvin, brightness, transition, parent: Context | None = None
    ) -> bool:
        """Colour temperature without transition, brightness with it (IKEA-safe).

        "Without transition" is sent as transition 0: a command without it gets
        a default transition (light profile, setting of the integration) and
        the colour would fade after all (RM-B42).
        kelvin is already limited to the light's range. If the command fails,
        the values are sent once without transition; if that fails too, the
        error is raised to apply_batch.
        """
        state = self.hass.states.get(entity_id)
        if not state:
            return False
        try:
            curr_bri = state.attributes.get("brightness") or 0
            # No colour temperature reported: the light is in a colour mode and
            # gets colour temperature in any case (RM-B46, not "2700 K measured")
            reported_kelvin = state.attributes.get("color_temp_kelvin")
            curr_kelvin = kelvin if reported_kelvin is None else reported_kelvin
            target_bri_byte = brightness_byte(brightness)
            delta_b = abs(curr_bri - target_bri_byte) / 255.0
            delta_k = abs(curr_kelvin - kelvin) / KELVIN_RANGE
            colour = {"entity_id": entity_id, "color_temp_kelvin": kelvin, "transition": 0}
            steps = []
            if delta_k > delta_b:
                # Check if brightness change is significant enough to warrant a snap
                if abs(curr_bri - target_bri_byte) > (BRIGHTNESS_THRESHOLD / 100.0 * 255):
                    steps.append({"entity_id": entity_id, "brightness_pct": brightness, "transition": 0})
                # Send color without transition to avoid glitches on IKEA bulbs
                steps.append(colour)
            else:
                # Only snap color if delta is significant; colour temperature never fades (transition 0).
                if reported_kelvin is None or abs(curr_kelvin - kelvin) > KELVIN_THRESHOLD:
                    steps.append(colour)
                steps.append({"entity_id": entity_id, "brightness_pct": brightness, "transition": transition})
            return await self._send_steps(entity_id, steps, parent)
        except Exception as err:  # noqa: BLE001 - the fallback below reports a final failure
            self._report_smart_failure(entity_id, err)
        if not self._still_wanted(entity_id):
            return False
        # Fallback: send everything, no transition (safest)
        return await self._async_call(
            "light", "turn_on",
            {"entity_id": entity_id, "brightness_pct": brightness, "color_temp_kelvin": kelvin, "transition": 0},
            blocking=True, parent=parent,
        )

    def _is_group(self, entity_id: str, state_obj=None) -> bool:
        """Check if entity is a group."""
        state = state_obj or self.hass.states.get(entity_id)
        if not state:
            return False
        return (state.attributes.get("is_hue_group") or 
                state.attributes.get("hue_type") or 
                isinstance(state.attributes.get(ATTR_ENTITY_ID), (list, tuple)))
