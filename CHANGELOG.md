# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0-beta16] (Bug Fixes & Revert)
- **Fix**: Resolved `ReferenceError` preventing Drag & Drop of points.
- **Feat**: Added **REVERT** button to discard unsaved changes and reload from disk.
- **Feat**: Added `mode: revert` to `update_curve` service.

## [0.4.0-beta15] (Feature Complete UI)
- **Feat**: **Presets**! Added drop-down with "Night Owl", "Early Bird", "Cozy", and "Default" profiles.
- **Feat**: **Visual Feedback**: Added Color Bar (Gradient) showing resulting Kelvin color below charts.
- **Feat**: **Clamped Shading**: Areas outside configured Brightness Min/Max are now shaded grey.
- **Feat**: **Test Button**: Added "TEST" button to apply curve to lights *without* saving to disk.
- **UX**: **Drag Constraints**: Points can no longer cross each other (min 15 min distance enforced).

## [0.4.0-beta14] (Frontend Polish & Accessibility)
- **Feat**: Added full Keyboard Navigation (Arrow Keys) for handles.
- **Feat**: Added ARIA labels/attributes for screen readers (Accessibility).
- **Fix**: Added `touch-action: none` to prevent page scrolling while dragging handles on mobile.
- **Fix**: Wrapped external Chart.js import in try/catch for offline robustness.
- **Perf**: Optimized `set hass` to avoid unnecessary JSON parsing.

## [0.4.0-beta13] (Final Layout Fix)
- **Fix**: Forces Chart resize in observer and adds fallback timeout (300ms) to guarantee Chart initialization before positioning handles.

## [0.4.0-beta12] (Robust Layout Fix)
- **Fix**: Implemented `ResizeObserver` in Frontend Card. Handles now correctly reposition when the card resizes or loads in a dynamic dashboard (fixing the "0,0" bug robustly).

## [0.4.0-beta11] (Save & Render Fixes)
- **Fix**: Removed invalid `await` from `async_update_entry` which caused "bool object not awaitable" errors during Save.
- **Fix**: Frontend now waits for layout (requestAnimationFrame) before calculating initial handle positions, fixing handles appearing at (0,0).

## [0.4.0-beta10] (Stability Hardening)
- **Fix**: Prevents "ZeroDivisionError" crash in PCHIP if fewer than 2 control points exist.
- **Fix**: Resolves critical "Dispatcher Leak" causing multiple redundant update cycles per save.
- **Fix**: Ensures "Update Curve" service raises visible errors in UI if Entity/Config is invalid.
- **Improved**: Hardened `light_controller` against invalid `supported_color_modes` (NoneType).

## [0.4.0-beta9] (Release Candidate Fixes)
- **Fix**: Backend now stores Control Points as Dicts (not Tuples), fixing "Points at 0,0" bug in Frontend.
- **Fix**: Corrected API call `hass.helpers.entity_registry.async_get` -> `er.async_get` in Service.

## [0.4.0-beta8] (Hotfix: Service Resolution)
- **Fix**: Card now sends `entity_id` to `update_curve` service.
- **Fix**: Service `update_curve` is now a Global Service (accepting Switch or Sensor entity) to resolve the correct config entry.
- **Improved**: Switch properly subscribes to "Apply" signals from the Card.

## [0.4.0-beta7] (Hotfix: Lovelace Deprecation)
- **Fix**: Use `lovelace_data.resources` (attribute) instead of `.get("resources")` to avoid future breaking change warning.

## [0.4.0-beta6] (Hotfix: Services)
- **Fix**: Added missing `services.yaml` definition for `update_curve`. Fixing `Failed to load services.yaml` error.

## [0.4.0-beta5] (Hotfix: Static Path)
- **Fix**: Use `async_register_static_paths` instead of deprecated default method. Fixes setup error.

## [0.4.0-beta4] (Self-Contained)
- **Refactor**: Frontend assets now served internally via `/hcl_lighting_static/`.
- **UX**: No longer requires manual file copying to `www/`. Fully self-contained integration.

## [0.4.0-beta3] (Auto-Registration)
- **Feature**: Auto-register `hcl-curve-card.js` as Lovelace Resource on startup.
- **UX**: Eliminates manual installation step for Dashboard Card.

## [0.4.0-beta2] (Frontend Alpha)
- **Feature**: `custom:hcl-curve-card` Lovelace Card.
- **Frontend**: Full PCHIP Interpolation logic in JS.
- **Frontend**: Interactive Drag & Drop UI (Glassmorphism).
- **Frontend**: Integrated `preview` (live update) and `save` actions.

## [0.4.0-beta1] (Interactive Backend)
- **Feature**: "Free-hand" Curve Logic (Arbitrary Control Points).
- **Feature**: `CurveConfig` data structure for explicit point storage.
- **Feature**: `hcl_lighting.update_curve` service for Preview/Apply/Save.
- **Feature**: `sensor.hcl_lighting_curve` (Source of Truth) for frontend synchronization.
- **Logic**: Migrated Interpolation to **PCHIP (Monotone Cubic Spline)**. Matches Professional Design Tools & Dashboard (WYSIWYG).
- **Migration**: Automatic migration of v0.3.0 settings to v0.2.1-replica point list.

## [0.3.0] - 2026-01-30
### "Dynamic & Customizable" Release

This major release empowers users to tailor the HCL curve to their specific daily schedule while improving stability and supporting multiple independent instances.

### 🌟 Major Features
- **User-Customizable Schedule**:
    - **Dynamic Anchors**: Define your own `Wake Time`, `Midday (Dip)`, and `Sleep Time`. The curve automatically stretches and adapts to your rhythm.
    - **Shift Work Support**: Handles schedules that wrap around midnight (e.g., Sleep at 01:00 AM) seamlessly.
    - **Elastic Intervals**: Intelligent math prevents "impossible" curves if times are set too close together.
- **Custom Instance Naming**:
    - Assign unique names (e.g., "HCL Living Room", "HCL Kids") during setup for easier identification in the Device Registry.
- **Refined Default Curve**:
    - Tuned the default generation logic to match the popular, natural profile of **v0.2.1**:
        - **Centered Midday Dip**: The configured "Midday" time is now the lowest point of the dip (4000K).
        - **Simpler Phases**: Removed complex "Social Evening" offsets in favor of a smooth, linear wind-down.

### 🛠️ Improvements & Fixes
- **Stability**:
    - **Brightness Ping-Pong**: Fixed a rounding issue where brightness would oscillate by ±1%.
    - **Shared State Isolation**: Critical fix ensuring multiple HCL instances do not leak curve data to each other.
    - **Null Safety**: Hardened `OverrideManager` against startup race conditions.
- **Translations**: Added full English and German translations for all new configuration options.
- **Math**: Improved Midnight wrapping logic to effectively handle day crossings.

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
