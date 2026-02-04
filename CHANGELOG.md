# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0-beta1] - 2026-02-04
### Added
- **Scenario Engine**: New `select.hcl_mode` entity allows robust switching between modes.
- **Fixed Scenarios**:
    - **Pro Modes**: Focus (5500K/100%), Relax (2700K/40%), Cleaning (4000K/100%).
    - **Guest Mode**: Pauses HCL updates completely, allowing manual control without fighting back.
    - **Sleep Mode**: Turns lights off, but allows manual override.
- **Frontend Upgrade**: `hcl-curve-card` now features "Chip" selectors for modes and visualizes the active scenario with a horizontal line in the chart.
- **Persistence**: Active mode is saved and restored after Home Assistant restarts.

## [0.4.1] - 2026-02-04
### Changed
- **Manual Preview Mode**: Dragging points in the graph no longer sends immediate updates to lights. This prevents "Time Paradox" flickering and reduces network traffic.
- **Visual Feedback**: The "PREVIEW" button now highlights (Yellow/Asterisk) to indicate unsaved changes.
- **Documentation**: Corrected the description of "Manual Override" behavior in README (it is per-light, not global).

### Fixed
- **Revert Logic**: The "REVERT" button now correctly and immediately resets the curve in the UI to the last saved state.
- **UI Consistency**: Renamed "VORSCHAU" button to "PREVIEW" to match the rest of the interface.

## [0.4.0] - 2026-02-02
### Added
- **Interactive Dashboard Card**: A fully interactive, touch-friendly Lovelace card (`custom:hcl-curve-card`) allowing drag-and-drop adjustment of Brightness and Color Temperature curves.
- **Visual Editor**: Integrated directly into the Dashboard card. Features include:
    - **Presets**: 12-point scientifically inspired profiles (Default, Focus, Relax, Early Bird, Night Owl).
    - **Validation Engine**: Real-time feedback on curve plausibility (e.g., "Night too bright") with visual warning zones.
    - **Live Preview**: "Test" button to temporarily apply the curve to lights without saving.
    - **Undo/Redo**: "Revert" button to discard unsaved changes.
- **Smart Onboarding**: Detects new installations and automatically creates a "Repair Issue" with a one-click guide to add the dashboard card.
- **Localization**: Full English and German translations for Configuration, Options, and Onboarding flows.

### Changed
- **Interpolation Engine**: Upgraded to **PCHIP** (Piecewise Cubic Hermite Interpolating Polynomial) for smoother, overshoot-free transitions between points.
- **Performance**:
    - **Smart Traffic Control**: Reduced Zigbee/Z-Wave traffic by ~90% via intelligent debouncing and delta-checks.
    - **Frontend Optimization**: Hardware-accelerated rendering and efficient state synchronization to prevent UI lag.
- **Theming & Accessibility**:
    - **Light & Dark Mode**: Full support for Home Assistant themes with correct contrast handling.
    - **Accessibility**: High-contrast chart elements and full keyboard navigation (Arrow keys) with ARIA support.

### Fixed
- **Stability**: Resolved multiple race conditions during Home Assistant startup and dashboard navigation.
- **Memory**: Backend logic includes automated zombie-listener cleanup to prevent memory leaks after reload.
- **Smart Override**: Improved detection of manual light changes to effectively pause HCL when a user intervenes via wall switch or app.

## [0.3.0] - 2026-01-30
### Added
- **User-Customizable Schedule**:
    - **Dynamic Anchors**: Define your own `Wake Time`, `Midday (Dip)`, and `Sleep Time`.
    - **Shift Work Support**: Handles schedules that wrap around midnight seamlessly.
    - **Elastic Intervals**: Intelligent math prevents "impossible" curves.
- **Custom Instance Naming**: Assign unique names during setup.
- **Translations**: Added full English and German translations for all new configuration options.

### Changed
- **Refined Default Curve**: Tuned default generation to match the natural profile of v0.2.1 (Centered Midday Dip, Simpler Phases).
- **Math**: Improved Midnight wrapping logic to effectively handle day crossings.

### Fixed
- **Stability**: Fixed "Brightness Ping-Pong" where brightness would oscillate by ±1%.
- **Isolation**: Critical fix ensuring multiple HCL instances do not leak curve data to each other.
- **Null Safety**: Hardened `OverrideManager` against startup race conditions.


## [0.2.1] - 2026-01-28
### Added
- **Smart Override 2.0**:
    - **Divergence Detection**: Distinguishes between natural HCL transitions and manual interventions.
    - **Color Support**: Detects manual color changes via XY/RGB divergence check.
    - **Steep Slope Tolerance**: Intelligent logic prevents false positives during the aggressive 12:15 PM HCL dip.
- **Instant-On Performance**:
    - **Fast-Path HCL**: Lights receive settings *immediately* upon turning on, bypassing "Color Flash".
    - **Zero Latency**: Optimization of task scheduling ensures commands hit the network instantly.
- **Smart Traffic Control**:
    - **Dynamic Thresholds**: Updates are only sent if values change significantly (>100K or >2%).
    - **Timezone Awareness**: Calculations now strictly follow Local Time.

### Changed
- **Architecture**: Split monolithic code into modules (`hcl_math`, `light_controller`, `override_manager`).
- **Resilient Update Loop**: Parallel execution (asyncio) ensures one failing light doesn't block others.
- **Capabilities**: Enhanced auto-detection of light capabilities (XY vs CT) with safe caching.

### Fixed
- **Group Safety**: Automatic filtering of Zigbee/Hue groups to prevent "Double Control" conflicts.
- **Zombie Cleanup**: Strict timer management prevents ghost updates after reloads.
- **Memory Safety**: Automated cache pruning prevents long-term memory leaks.


## [0.1.0] - 2026-01-24
### Added
- Initial release of HCL Lighting integration.
- Automatic brightness and color temperature adjustment based on time of day.
- Cubic Hermite spline interpolation for smooth, natural transitions.
- Support for DIN SPEC 67600 inspired HCL curve (Morning, Midday, Evening).
- Flexible targeting system (Entities, Devices, Areas, Groups).
- Automatic light capability detection and Extended Warm White simulation (XY).
- Optional "Smart Transition" mode.
- Configurable brightness limits (min/max).
- Instant HCL application when lights turn on.
- State restoration after Home Assistant restart.
- Full UI configuration (no YAML required).
- German and English translations.

[0.4.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0
[0.3.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.3.0
[0.2.1]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.2.1
[0.2.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.2.0
[0.1.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.1.0
