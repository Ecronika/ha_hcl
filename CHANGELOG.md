# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0-rc15] - 2026-02-02
### Fixed
- **Network Stability**: Increased preview service debounce to 500ms to prevent flooding Home Assistant with requests during rapid dragging.
- **Performance**: Optimized validation UI rendering to prevent DOM thrashing during animations.
- **Stability**: Added visibility checks (`offsetParent`) to stop rendering loops when the card is in a background tab.
- **Logic**: Improved state synchronization to prevent unnecessary re-renders when receiving data from the backend.

## [0.4.0-rc14] - 2026-02-02
### Fixed
- **Light Theme Support**: Fixed critical UX issue where text was unreadable in Light Themes. The card now uses Home Assistant theme variables (`--primary-text-color`, `--card-background-color`, etc.) with proper fallbacks, ensuring readability in all modes.
- **Performance**: Removed inefficient layout polling (busy wait) in favor of a native `ResizeObserver` approach.
- **Stability**: Removed aggressive DOM cleanup on disconnect to prevent flickering when switching tabs.
- **Accessibility**: Improved keyboard focus restoration logic using `requestAnimationFrame` for robust interactions.

## [0.4.0-rc13] - 2026-02-02
### Fixed
- **Validation UI**: Fixed missing validation highlighting on the Color Temperature (Kelvin) chart. The background plugin was previously only registered for the Brightness chart. All warnings (like "Temp too low") now correctly display an orange overlay on the affected graph area.

## [0.4.0-rc12] - 2026-02-02
### Fixed
- **Accessibility**: Fixed focus loss during keyboard navigation (Arrow Keys). The card now restores focus to the active handle after re-rendering.
- **Stability**: Added proper cleanup for global drag event listeners (`pointermove`, `pointerup`) to prevent memory leaks or "ghost drags" if the card is disconnected during an interaction.

## [0.4.0-rc11] - 2026-02-02
### Fixed
- **UI Responsiveness**: Fixed an issue where buttons and dropdowns became unresponsive after navigating between dashboard tabs. The card now fully resets its HTML on disconnect to ensure event listeners are correctly re-bound upon reconnection.

## [0.4.0-rc10] - 2026-02-02
### Fixed
- **Critical JavaScript Fix**: Restored missing `class HCLCurveCard extends HTMLElement` wrapper that was accidentally removed in rc9, causing a `SyntaxError: Unexpected strict mode reserved word`. The card now correctly registers as a Custom Element.
- **Robust Navigation**: Includes all dashboard navigation fixes (Layout Polling, Canvas Clearing) from rc9, but in a valid class structure.

## [0.4.0-rc9] - 2026-02-02
### Fixed
- **Dashboard Navigation Support (Robust)**: Implemented active layout polling (`_scheduleLayoutCheck`) and explicit resizing loop in the frontend card. This robustly fixes blank charts when switching dashboard tabs/views by ensuring the canvas only renders when it has valid dimensions.

## [0.4.0-rc8] - 2026-02-02
### Fixed
- **Dashboard Navigation Support**: Fixed a bug where charts would disappear (blank canvas) when switching between dashboard views by forcing chart re-initialization.
- **UI Layout**: Fixed Validation Warnings overlaying the "Save/Revert" buttons, making them unclickable. Adjusted Z-Index stacking.

## [0.4.0-rc7] - 2026-02-02
### Security
- **XSS Prevention**: Fixed a vulnerability in the Validation UI by escaping HTML in error messages.

### Added
- **Expert Onboarding**: Added a "Repair Issue" notification to guide new users to set up the Dashboard Card via YAML.
- **Dynamic Repair**: The onboarding message now dynamically detects the correct entity ID for each HCL instance.
- **Visual Editor Support**: Added `getStubConfig` to the frontend card to support easier addition via the "Add Card" menu.

### Fixed
- **Startup Crash**: Fixed invalid `IssueSeverity.NOTICE` (replaced with `WARNING`) causing `AttributeError` during setup.
- **Translations**: Added missing German translations for the "Setup Curve Card" repair issue.
- **Race Condition**: Refactored `switch.py` to handle state changes synchronously, preventing override detection bugs.
- **Memory Leak**: Properly remove event listeners in the Frontend Card to prevent memory bloat on dashboard navigation.

### Changed
- **Config Handling**: Added robust type coercion (`float` -> `int`) for brightness/kelvin config values to prevent crashes.
- **Algorithms**: Improved PCHIP midnight handling to prevent artifacts at day boundaries.
- **Performance**: Implemented a bucketed result cache for Capability Detection to avoid redundant calculations.
- **Code Quality**: Replaced magic numbers with named constants and improved internal documentation.

## [0.4.0-rc6] - 2026-01-31
### Fixed
- **IKEA Transition Glitch**: Removed `transition` parameter from all `color_temp` commands to prevent brightness "dips" on Zigbee consumer bulbs.

### Changed
- **Optimization**: Filtered out redundant "Snap" commands in Smart Transition mode to reduce Zigbee traffic.

## [0.4.0-rc5] - 2026-01-30
### Fixed
- **Infinite Loop**: Added recursion guards and visibility checks to `_updateVisuals` to prevent background freeze.
- **Memory Leak**: Chart instances are now properly destroyed when the card is removed.
- **Sticky XY Mode**: Fixed an issue where out-of-range color commands permanently locked lights into XY mode.

### Changed
- **Rendering**: Migrated drag-handles to hardware-accelerated `translate` to eliminate layout thrashing.
- **Validation**: Validation messages now float over the chart instead of shifting the layout.
- **Logic**: Smart Active Phase validation now detects mismatches (e.g., "Bright enough but too cold").

## [0.4.0-rc4]
### Added
- **Validation Engine**: Live checks for "Errors" (save blocked) and "Warnings" (advisory).
- **Visual Feedback**: Warning zones (e.g., steep slopes, bright nights) are now visually highlighted in the chart.
- **Plausibility Checks**: Warnings for Night Brightness (>10%), Night Color (>3000K), Daily Peak Duration (<4h), and Slopes.
- **Sanitizer**: Auto-fix common data issues (duplicates, sorting) via new "Fix" button.

## [0.4.0-rc3]
### Changed
- **Scrolling Fix**: Enabled scrolling on chart backgrounds, restricted `touch-action: none` only to handles.
- **Touch Targets**: Increased handle hit-area using pseudo-elements for easier grabbing on mobile.

## [0.4.0-rc2]
### Security
- **Local Chart.js**: Replaced external CDN dependency with local `chart.js` bundle to ensure offline functionality and stability.

### Fixed
- **Chart Init Race**: Hardened `scaleReady` check in visual update loop to strictly wait for `xAxis.width > 0`.

### Changed
- **Drag Throttling**: Implemented `requestAnimationFrame` throttling for drag operations to reduce layout thrashing.

## [0.4.0-rc1]
### Fixed
- **PCHIP Reliability**: Added zero-division guards to PCHIP implementation to prevent crashes with flat line segments.
- **Frontend Race Condition**: Added robust checks to wait until Chart scales are fully initialized before positioning handles.
- **Service Validation**: `update_curve` service now strictly validates entity domain (must contain `sensor` or `switch`) and platform.
- **Migration Safety**: Added sanity checks to `migrate_legacy_config` to prevent invalid or compressed timelines.

### Changed
- **Dropdown Contrast**: Improved CSS for preset dropdowns for better cross-browser readability.

## [0.4.0-beta20]
### Added
- **Live Tooltips**: Added tooltips to drag handles showing Time & Value.

### Changed
- **Chart Cleanup**: Removed chart points ("Pearl Chain") for a cleaner look.
- **UI**: Improved Dropdown readability with dark background.

## [0.4.0-beta19]
### Fixed
- **Cache Buster**: Added version query parameter to frontend resource URL to force browser cache refresh.

## [0.4.0-beta18]
### Added
- **Axis Footer**: Added Timeline (00:00 - 24:00) below the color bar.
- **Overlay Labels**: "Brightness" and "Color Temp" labels directly in the chart area.

### Changed
- **Complete Redesign**: Implemented "Glass Precision" style with frosted glass backgrounds.
- **Responsive Layout**: Charts now sit side-by-side on desktop (Grid) and stack on mobile.
- **Pill Buttons**: Modern rounded buttons and inputs.
- **Visuals**: Enhanced handle glow effects for better visibility.

## [0.4.0-beta17]
### Added
- **Biologically Accurate Presets**: Updated Presets to detailed 12-Point Model (Default, Early Bird, Night Owl).

### Changed
- **Logic**: Presets now match the backend default logic (Midday Dip, Morning Peak, etc.).

## [0.4.0-beta16]
### Added
- **Revert Button**: Added `REVERT` button to discard unsaved changes and reload from disk.
- **Service**: Added `mode: revert` to `update_curve` service.

### Fixed
- **Drag & Drop**: Resolved `ReferenceError` preventing Drag & Drop of points.

## [0.4.0-beta15]
### Added
- **Presets**: Added drop-down with "Night Owl", "Early Bird", "Cozy", and "Default" profiles.
- **Color Bar**: Added Gradient bar showing resulting Kelvin color below charts.
- **Clamped Shading**: Areas outside configured Brightness Min/Max are now shaded grey.
- **Test Button**: Added "TEST" button to apply curve to lights *without* saving to disk.

### Changed
- **Drag Constraints**: Points can no longer cross each other (min 15 min distance enforced).

## [0.4.0-beta14]
### Added
- **Keyboard Navigation**: Added full Arrow Key support for handles.
- **Accessibility**: Added ARIA labels/attributes for screen readers.

### Fixed
- **Scrolling**: Added `touch-action: none` to prevent page scrolling while dragging handles on mobile.
- **Reliability**: Wrapped external Chart.js import in try/catch for offline robustness.

### Changed
- **Performance**: Optimized `set hass` to avoid unnecessary JSON parsing.

## [0.4.0-beta13]
### Fixed
- **Layout**: Forces Chart resize in observer and adds fallback timeout (300ms) to guarantee initialization.

## [0.4.0-beta12]
### Fixed
- **Layout**: Implemented `ResizeObserver` to robustly fix the "0,0" handle bug on resize.

## [0.4.0-beta11]
### Fixed
- **Save Error**: Removed invalid `await` from `async_update_entry` which caused errors during Save.
- **Render Race**: Frontend now waits for layout before calculating initial handle positions.

## [0.4.0-beta10]
### Fixed
- **Math**: Prevents "ZeroDivisionError" crash in PCHIP if fewer than 2 control points exist.
- **Leak**: Resolves critical "Dispatcher Leak" causing multiple redundant update cycles per save.
- **Validation**: Ensures "Update Curve" service raises visible errors in UI if Entity/Config is invalid.

### Changed
- **Robustness**: Hardened `light_controller` against invalid `supported_color_modes` (NoneType).

## [0.4.0-beta9]
### Fixed
- **Data Structure**: Backend now stores Control Points as Dicts (not Tuples), fixing "Points at 0,0" bug.
- **API**: Corrected API call `hass.helpers.entity_registry.async_get` -> `er.async_get`.

## [0.4.0-beta8]
### Fixed
- **Service**: Card now sends `entity_id` to `update_curve` service.
- **Service Scope**: `update_curve` is now a Global Service to resolve the correct config entry.

### Changed
- **Logic**: Switch properly subscribes to "Apply" signals from the Card.

## [0.4.0-beta7]
### Fixed
- **Deprecation**: Use `lovelace_data.resources` instead of dict access to avoid warnings.

## [0.4.0-beta6]
### Fixed
- **Configuration**: Added missing `services.yaml` definition for `update_curve`.

## [0.4.0-beta5]
### Fixed
- **Setup**: Use `async_register_static_paths` instead of deprecated default method.

## [0.4.0-beta4]
### Changed
- **Assets**: Frontend assets now served internally via `/hcl_lighting_static/`.
- **Packaging**: No longer requires manual file copying to `www/`. Fully self-contained.

## [0.4.0-beta3]
### Added
- **Auto-Registration**: Auto-register `hcl-curve-card.js` as Lovelace Resource on startup.

### Changed
- **UX**: Eliminates manual installation step for Dashboard Card.

## [0.4.0-beta2]
### Added
- **Frontend**: `custom:hcl-curve-card` Lovelace Card.
- **Frontend**: Full PCHIP Interpolation logic in JS.
- **Frontend**: Interactive Drag & Drop UI (Glassmorphism).
- **Frontend**: Integrated `preview` (live update) and `save` actions.

## [0.4.0-beta1]
### Added
- **Features**: "Free-hand" Curve Logic (Arbitrary Control Points).
- **Features**: `CurveConfig` data structure for explicit point storage.
- **Services**: `hcl_lighting.update_curve` service for Preview/Apply/Save.
- **Entities**: `sensor.hcl_lighting_curve` (Source of Truth) for frontend synchronization.

### Changed
- **Migration**: Automatic migration of v0.3.0 settings to v0.2.1-replica point list.
- **Interpolation**: Migrated to **PCHIP (Monotone Cubic Spline)** to match professional tools.

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

[0.4.0-rc15]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-rc15
[0.4.0-rc14]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-rc14
[0.4.0-rc13]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-rc13
[0.4.0-rc12]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-rc12
[0.4.0-rc11]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-rc11
[0.4.0-rc10]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-rc10
[0.4.0-rc9]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-rc9
[0.4.0-rc8]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-rc8
[0.4.0-rc7]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-rc7
[0.4.0-rc6]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-rc6
[0.4.0-rc5]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-rc5
[0.4.0-rc4]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-rc4
[0.4.0-rc3]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-rc3
[0.4.0-rc2]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-rc2
[0.4.0-rc1]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-rc1
[0.4.0-beta20]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta20
[0.4.0-beta19]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta19
[0.4.0-beta18]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta18
[0.4.0-beta17]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta17
[0.4.0-beta16]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta16
[0.4.0-beta15]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta15
[0.4.0-beta14]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta14
[0.4.0-beta13]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta13
[0.4.0-beta12]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta12
[0.4.0-beta11]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta11
[0.4.0-beta10]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta10
[0.4.0-beta9]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta9
[0.4.0-beta8]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta8
[0.4.0-beta7]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta7
[0.4.0-beta6]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta6
[0.4.0-beta5]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta5
[0.4.0-beta4]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta4
[0.4.0-beta3]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta3
[0.4.0-beta2]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta2
[0.4.0-beta1]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0-beta1
[0.3.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.3.0
[0.2.1]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.2.1
[0.2.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.2.0
[0.1.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.1.0
