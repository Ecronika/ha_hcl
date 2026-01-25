# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
