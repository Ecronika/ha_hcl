# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0-beta3] (Cozy Evening Optimization)
- **Feature**: Refined Evening Curve with a new "Social Evening" phase (-4h before sleep @ 3800K/60%) for a warmer atmosphere.
- **Logic**: Adjusted "Wind-Down" phase (-2h before sleep) to be cozier (2700K/30%).

## [0.3.0-beta2] (Stable Dynamic Curves)
- **Fix**: Added missing translations for configuration options.
- **Fix**: Implemented "Elastic Interval" logic to prevent overlapped curve sectors and corrected midnight wrapping.

## [0.3.0-beta1] (Dynamic Curves)
- **Feature**: User-Customizable Curve! You can now define your `Wake Time`, `Social Midday`, and `Sleep Time` in the configuration.
- **Logic**: The HCL curve is no longer static. It dynamically generates tailored phases (Warm-up, Focus, Dip, Wind-down) based on your schedule.

## [0.2.1] - 2026-01-28
### "Architecture & Intelligence" Release

This major release marks the transition from MVP to a production-grade HCL system. It introduces a modular architecture, an intelligent "Manual Override" detection system, and "Instant-On" low-latency performance.

### 🌟 Major Features
- **Smart Override 2.0**: The system detects when you manually adjust lights and automatically releases control.
    - **Divergence Detection**: Distinguishes between natural HCL transitions and manual interventions (trajectory analysis).
    - **Color Support**: Now detects manual color changes (e.g., Blue, Red) via XY/RGB divergence check.
    - **Steep Slope Tolerance**: Intelligent logic prevents false positives during the aggressive 12:15 PM HCL dip.
- **"Instant-On" Performance**:
    - **Fast-Path HCL**: Lights receive their correct HCL settings *immediately* upon turning on, bypassing the "Color Flash" artifact.
    - **Zero Latency**: Optimization of task scheduling ensures commands hit the network instantly.
- **Smart Traffic Control**:
    - **Dynamic Thresholds**: Updates are only sent if values change significantly (>100K or >2%), reducing Zigbee/WiFi traffic by ~90%.
    - **Timezone Awareness**: All calculations now strictly follow Local Time to prevent circadian drift.

### 🏗️ Architecture & Internal
- **Modular Codebase**: Split monolithic code into specialized logic modules (`hcl_math`, `light_controller`, `override_manager`).
- **Resilient Update Loop**: Parallel execution (asyncio) ensures one failing light doesn't block others.
- **Memory Safety**: Automated cache pruning prevents long-term memory leaks.
- **Concurrency**: Guarded update loops prevent race conditions during rapid state changes.

### 🐛 Bug Fixes & Polish
- **Group Safety**: Automatic filtering of Zigbee/Hue groups to prevent "Double Control" conflicts.
- **Zombie Cleanup**: Strict timer management prevents ghost updates after reloads.
- **Capability 2.0**: Enhanced auto-detection of light capabilities (XY vs CT) with safe caching.

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
