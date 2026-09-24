# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-09-23
### Added
- **Adapt brightness / Adapt colour temperature**: two switches per instance. With one of them off, HCL only controls the other attribute; changes of the attribute HCL does not adapt no longer pause the light. Sleep mode still switches lights off. Both switches keep their state across reloads and restarts.
- **Manual control through Home Assistant**: HCL sends its commands with its own context. Commands from apps, dashboards, scenes, automations or voice assistants that change brightness or colour of a light that is on now pause the light immediately (also inside the 22-s window after an HCL update, where such changes were missed before).
- **Option "Keep values of turn-on commands"** (default off): a light switched on through Home Assistant with its own values keeps them instead of receiving the HCL values.
- **Manual-control options**: time until HCL takes a paused light back (default 240 min as before, 0 = never), whether switching a light off ends manual control (default on as before), and whether manual control survives Home Assistant restarts (default off as before).
- **Attribute `manual_control`** on the HCL switch listing the paused lights.
- **Scenario options**: brightness and colour temperature of Focus, Relax and Cleaning (defaults unchanged) and an optional duration after which they return to Auto (attribute `until` on the scenario select; kept across restarts).
- **Update options**: update interval (default 27 s), transition of updates (default 20 s) and transition when a light is switched on (default 0 s).
- **Setup**: wake, midday and sleep time can be set when adding the integration; wake and sleep time must be more than 6 hours apart (also checked in the options).
- **Dashboard card**: add points (button or double-click), delete the selected point (button or Del), numeric input of time/brightness/colour temperature, undo (button or Ctrl+Z), a marker for the current time with the current values, the effective brightness under min/max limits as a dashed line, and scenario lines with the configured values.
- **Dashboard card**: German and English texts following the Home Assistant language; colours follow the active Home Assistant theme (light and dark).
- **Translations**: names of the scenario states, the new entities and options, and the `update_curve` service.
- German quick guide `README.de.md`; hassfest check in the CI workflow.

### Changed
- **Entity names**: the HCL switch is now called "HCL active" ("HCL aktiv") and the mode select "Scenario" ("Szenario"). Existing installations keep their entity IDs; new installations get IDs like `switch.<name>_hcl_active` and `select.<name>_scenario`. The scenario select is no longer a configuration entity, so it appears in auto-generated dashboards and can be exposed to voice assistants.
- **Targets** given as devices, areas, floors or labels are resolved again when the entity, device or area registry changes (e.g. a new light in a selected area).
- **Curve sensor**: the state is a timestamp (device class `timestamp`, time of the last curve/scenario change); the curve data attributes are no longer written to the recorder database.
- **Options** are split into three pages (curve and lights, updates and manual control, scenarios).
- The `update_curve` service is registered once for the integration and stays available while no entry is loaded; the card resource is registered once per Home Assistant run instead of on every reload.
- **Revert** in the card uses the anchor times entered at setup when no curve was saved and no anchor options exist.
- A paused light that is found switched off during an update cycle is released (if switching off ends manual control), e.g. after a switch-off that HCL did not see.
- README: descriptions of the default profile and presets corrected (midday dip is part of the default profile, not a norm requirement; there is no "Shift Work" preset).

### Fixed
- **Manifest**: `http` added as dependency and `lovelace` as after-dependency (the integration uses both); the invalid key `funding_url` was removed and `documentation`/`issue_tracker` point to the repository (hassfest).
- `tests/test_hcl_math_v4.py` runs again (no Windows path and module mocks).

## [0.5.1] - 2026-09-23
### Fixed
- **Sleep Mode**: A light switched on manually during Sleep mode is no longer switched off again by the next update cycle; it is treated as a manual override (as documented for 0.5.0-beta1).
- **Options lost the edited curve**: Saving the integration options replaced all options and silently deleted the curve saved in the dashboard card. Options are now merged; the saved curve is only discarded when Wake, Midday or Sleep Time is changed.
- **Manual colour changes right after an HCL update**: Colour temperature or colour changes made within the ignore window after an HCL update (22 s) were not detected and were reverted by the next cycle. Changes that move the light away from the HCL target are now detected for brightness, colour temperature and XY colour.
- **Endless updates**: Lights in XY mode (colour bulbs, XY simulation) and CT lights whose range does not cover the target (e.g. 2200–4000 K) were re-sent every 27 s. The comparison now uses the reachable colour temperature or the XY colour. This also prevents false manual-override detection on such lights.
- **Overrides lost on save**: Saving the curve or the options reloads the entry; manual overrides are now kept across the reload (still cleared by a Home Assistant restart).
- **Anchor times**: Wake/Midday/Sleep combinations that did not leave room for all sectors produced duplicate or out-of-order curve points (e.g. 07:00/14:00/21:00). Midday is now moved into its feasible range, and days shorter than ~11 h scale the default profile.
- **Curves with gaps longer than 12 h**: Interpolation crashed with a division by zero (e.g. two-point curves) or overshot and differed from the dashboard card. Slopes now use forward distances on the 24 h cycle.
- **Floor and label targets**: Floors and labels selected in the target selector were ignored. Label support was also proposed by @joneshf in #1 – thank you!
- **Startup race**: Light groups that finish loading after HCL were not expanded to their members until the switch was toggled. Targets are resolved again when Home Assistant has started.
- **Card mode chips**: The chips now show the actual mode of the select entity (also after restarts or changes by automations).
- **Card brightness limits**: The curve sensor now exposes `min_brightness`/`max_brightness`, so the card shades the clipped ranges again.
- **Lovelace resource registration**: Resources are loaded before they are checked or changed. Previously, depending on the Home Assistant version, the card resource was added again on each start or other stored dashboard resources were overwritten. YAML-mode resources are no longer touched (setup could fail when an old HCL resource URL was present).
- **Re-engagement**: After the 4-hour override timeout, HCL no longer switches on lights that are off.
- **Card styles**: A missing `:host` selector discarded the card's main style rules.
- **Card scenario line**: The horizontal line for the active scenario (announced in 0.5.0-beta1) is now drawn.
- **Translations**: English Repair Issue text and the name field label in the setup form were missing.
- **Service `update_curve`**: Input is validated (mode, at least two points with valid ranges); `revert` is listed in `services.yaml` and `points` is optional for it.
- **Repair Issue**: The card setup notice is removed when the integration entry is deleted.
- **Mode select without device**: The mode select entity was not assigned to the HCL device, so it was named `select.mode` (`select.mode_2`, … for further instances). New installations now get `select.<instance>_mode`; existing entity IDs are kept by the entity registry and the entity is attached to its HCL device.
- **Scenario chips after adding an instance**: The curve sensor did not know the mode select of a newly added instance (`mode_entity_id` stayed empty until the next curve/mode update), so the card chips did nothing. The sensor now follows the registration and renaming of its mode select.
- **Minimum Home Assistant version**: `hacs.json` now requires 2024.7.0 (needed for `StaticPathConfig`).

### Added
- Test suite based on `pytest-homeassistant-custom-component` (`tests/`) and Playwright browser tests for the card (`tests_frontend/`).
- GitHub Actions workflow running the tests against the minimum supported and the current Home Assistant release.

## [0.5.0-beta2] - 2026-02-04
### Fixed
- **Race Condition**: Resolved issue where "Scenario Chips" didn't work immediately after startup because the Select Entity wasn't found in time.
- **Diagnostics**: Added console warnings in Frontend if configuration is incomplete.

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

[0.6.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.6.0
[0.5.1]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.5.1
[0.4.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0
[0.3.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.3.0
[0.2.1]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.2.1
[0.2.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.2.0
[0.1.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.1.0
