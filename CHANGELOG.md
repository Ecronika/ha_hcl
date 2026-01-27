# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1-beta8] (Crash Guard & Race Fixes)
- **Critical Fix**: Resolved Startup Crash (Missing Imports & Class Names).
- **Critical Fix**: Fixed Capability Detection Crash (`TypeError` on `None` attributes).
- **Fix**: Memory Leak in Override Manager (Pruning stale entities).
- **Fix**: Race Condition during Config Updates (Removed redundant listener).
- **Fix**: Event Listener reliability (Crash Protection).
- **Fix**: UTC/Local Time logic verified (using `dt_util.now()`).

## [0.2.1-beta7] (Timing & Loop Fixes)
- **Critical Fix**: Resolved concurrency race condition in Update Loop (Switch Reentrancy).
- **Critical Fix**: Reduced Transition Time (20s) to guarantee completion before next update cycle (27s).
- **Fix**: Math Rounding Logic (switched to `round()`) to prevent infinite 1% ping-pong loops.
- **Fix**: Switch UI State Consistency (force write state on toggle).
- **Fix**: Override Detection reliability (added Reference Fallback).
- **Hardening**: Config Type Coercion and DivisionByZero guards.

## [0.2.1-beta6] (Edge Case Polish)
- **Fix**: Override Logic refined (Ignore Window only set if update actually queued).
- **Fix**: Logic Fallback Safety (Prevent invalid `supported_color_modes` types).
- **Fix**: Config Flow Robustness (Safe handling of empty target defaults).
- **Refactor**: Code Quality improvements (Constants usage, Type hints).

## [0.2.1-beta5] (Final Polish)
- **Fix**: Critical Config Flow Syntax Error that prevented loading on some setups.
- **Fix**: Added logical validation for Brightness Bounds (prevents min > max).
- **Fix**: Reduced log noise (missing capabilities warning downgraded to debug).
- **Fix**: Improved batch update exception logging (includes stacktraces).

## [0.2.1-beta4] (Production Stability)
- **Fix**: Critical Bug where integration failed to work on fresh installs (Target Resolution priority).
- **Fix**: Critical Override Logic Flaw (Ignore Window now only set on active updates).
- **Fix**: Zombie Timers (Idempotent `turn_on`).
- **Fix**: Group Expansion Efficiency ($O(n)$ Stack) & filtering non-light entities.
- **Fix**: Exception Logging now includes stacktraces in update loop.
- **Fix**: Config Flow compatibility with older HA versions.

## [0.2.1-beta3] (Cleanup & Validation)
- **Fix**: Memory Leak in Capability Cache (Automatic Pruning).
- **Fix**: Defensive Input Validation in Math Logic (Min/Max Brightness clamping).

## [0.2.1-beta2] (Stability Hardening)
- **Fix**: Critical Race Condition in Fast-Path logic (Fixed spurious override detection).
- **Fix**: Resilient Batch Updates (One failing light no longer blocks others).
- **Fix**: Added Exception Handling to Main Update Loop.

## [0.2.1-beta1] (Capability Fix)
- **Fix**: Prevent caching capabilities for Unavailable/Unknown/OFF entities.
- **Fix**: Force re-calculation of capabilities if `supported_color_modes` was empty previously.
- **Improved**: Safe caching logic with versioning (v2) to automatically fix legacy cache issues.
- **Refactor**: Improved debug logging for capability detection.

## [0.2.0-beta4] (Release Candidate)
- **Fix**: Code Hygiene in `override_manager.py` (Indentation/Imports).
- **Cleanup**: Removed redundant update listener in `switch.py` (Architecture).
- **Cleanup**: Configuration flow comments.

## [0.2.0-beta3] (Review Fixes)
- **Fix**: Critical Race Condition in Fast-Path logic (synchronous state tracking).
- **Fix**: Zombie Timer prevention on integration reload.
- **Fix**: Validation logic for Overrides (bounds check).
- **Optimization**: Cached target resolution (CPU reduction).
- **Refactoring**: Deduplicated group detection and cleanup of magic numbers.

## [0.2.0-beta2] (Hotfix)

## [0.2.0-beta1] - 2026-01-25

### Added
- **Manual Override Detection**: Triggers if brightness changes >5% or Kelvin >200K. Auto-resets on light OFF.
- **Fast-Path HCL**: Instantly applies calculated values when a light turns ON (bypassing restore state).
- **Thresholds**: Updates are only sent if brightness changes >1% or Kelvin >50K (reduces network traffic).
- **Timezone Awareness**: Fixed calculation drift by enforcing local time for all curve calculations.
- **Zombie Cleanup**: Added explicit timer cancellation on unload to prevent duplicate/ghost updates after reloading.

### Changed
- **Update Interval**: Increased frequency to 27 seconds for smoother transitions (was 5 minutes).
- **Refactoring**: Split monolithic code into modular logic (`hcl_math`, `light_controller`, `override_manager`).
- **Performance**: Parallel execution of light updates (asyncio.gather) and capability caching.
- **Validation**: Strict "state == ON" check to prevent accidental turn-ons of offline lights.
- **Group Safety**: Added Just-in-Time filtering to ignore Zigbee/Hue Groups (even if they sneak into target lists) to prevent "Double Control" of lights.

### Fixed
- **Ghost Updates**: Fixed issue where old timer instances ("zombies") caused fluctuating light levels.
- **Calculation Drift**: Fixed discrepancy between Fast-Path (Local Time) and Periodic Update (UTC), eliminating 5% brightness jumps.
- **Documentation**: Corrected README to match actual HCL curve points (09:30, 13:00, 14:00).

## [0.1.0] - 2026-01-24

### Added
- Initial release of HCL Lighting integration
- Automatic brightness and color temperature adjustment based on time of day
- Cubic Hermite spline interpolation for smooth, natural transitions
- Support for DIN SPEC 67600 inspired HCL curve with key phases:
  - Morning activation (warm-up to 6500K)
  - Midday regeneration dip (12:30 PM)
  - Afternoon re-activation
  - Evening wind-down
- Flexible targeting system:
  - Individual entities
  - Devices
  - Areas
  - Groups (with automatic expansion)
- Smart compatibility features:
  - Automatic light capability detection
  - Extended warm white simulation using XY color for low Kelvin values
  - Optional "Smart Transition" mode for incompatible lights
- Configurable brightness limits (min/max)
- Instant HCL application when lights turn on (prevents color flash)
- Periodic updates every 5 minutes with smart delta detection
- State restoration after Home Assistant restart
- Full UI configuration (no YAML required)
- German and English translations

### Technical Details
- Update interval: 5 minutes
- Default transition duration: 60 seconds
- Delta thresholds: 2% brightness, 50K color temperature
- Interpolation: Cubic Hermite splines with periodic boundary conditions

[0.2.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.2.0
[0.1.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.1.0
