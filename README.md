# HCL Lighting for Home Assistant

A **Human Centric Lighting (HCL)** custom integration for Home Assistant that adjusts your lights' brightness and colour temperature throughout the day along a daily curve, inspired by the recommendations of DIN SPEC 67600 / DIN/TS 67600.

🇩🇪 [Deutsche Kurzanleitung](README.de.md)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/Ecronika/ha_hcl.svg)](https://github.com/Ecronika/ha_hcl/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## ✨ Features

### 🎨 Interactive Dashboard Card
- **Visual Editor**: Edit brightness and colour temperature on an interactive, touch-friendly chart.
- **Editing**: Drag points, add points (➕ button or double-click in the chart), delete the selected point (➖ button or Del key), enter exact values (time, %, K) and undo changes (↶ button or Ctrl+Z). Points always stay in chronological order.
- **Now marker**: A line shows the current time (in the Home Assistant time zone); below the charts the current values are shown (including the brightness limits).
- **Save status**: Save is confirmed by Home Assistant; errors are shown in the card and the changes stay marked as unsaved. While the lights follow an unsaved preview, the card shows a hint.
- **Presets**: One-click profiles **Default** (the integration's default curve), **Focus**, **Relax**, **Early Bird** and **Night Owl**.
- **Live Validation**: Immediate hints on implausible curves (e.g. bright, cold light at night; night = sleep time to wake time).
- **Language and theme**: German/English texts following the Home Assistant language; colours follow the active (light or dark) theme.

### 🧬 Curve
- **PCHIP Interpolation**: Monotone cubic interpolation for smooth transitions without overshooting.
- **Default profile**:
    - **Morning**: gradual rise to cool, bright light.
    - **Midday dip**: a dip around 12:30 (4000 K / 50 %). This is part of the default profile, not a normative requirement; edit or remove it in the card if you do not want it.
    - **Afternoon**: bright, cool light.
    - **Evening**: wind-down to warm, dim light.

### 🧠 Control
- **Manual control**: HCL pauses a light when you change it yourself and resumes later (see [Manual control](#manual-control)).
- **Brightness and colour temperature separately**: Two switches per instance let HCL adapt only the colour temperature, only the brightness or both.
- **Traffic Control**: Updates are only sent when the values change noticeably (brightness > 1 %, colour temperature > 50 K).
- **Instant-On**: Lights receive the HCL values right after they are switched on.
- **Capabilities**: Auto-detects colour support (XY, HS, RGB, RGBW, RGBWW) and simulates colour temperatures outside a bulb's native CT range via XY on colour-capable bulbs (supported range of the curve: 2000–7000 K). CT-only bulbs are driven to the nearest temperature they can reach.

---

## 🚀 Installation

### 1. Install via HACS
1. Open HACS in Home Assistant.
2. Go to "Integrations" > Top Right Menu > "Custom repositories".
3. Add `https://github.com/Ecronika/ha_hcl` as **Integration**.
4. Click **Install**.
5. **Restart Home Assistant**.

### 2. Add Integration
1. Go to **Settings** → **Devices & Services** → **Add Integration**.
2. Search for **"HCL Lighting"**.
3. Name your instance (e.g. "Living Room"), select the lights and set the wake, midday and sleep time. Targets can be entities, devices, areas, floors or labels; light groups are expanded to their members. Lights that are added to a selected area, device, floor or label later are picked up automatically.

**Requirements**: Home Assistant **2024.7** or newer.

### 3. Setup Dashboard Card
**Automatic Setup (Recommended)**:
After installation, HCL Lighting creates a **Repair Issue** (Settings → Repairs) with step-by-step instructions and the YAML for the card. The notice is removed when the integration entry is deleted.

**Manual Setup**:
Add a "Manual" card to your dashboard with the following YAML:
```yaml
type: custom:hcl-curve-card
entity: sensor.hcl_lighting_curve_data
```
The sensor is named `sensor.<instance name>_curve_data` (e.g. `sensor.living_room_curve_data`); the Repair Issue shows the exact entity ID.

*(The frontend resource `hcl-curve-card.js` is registered automatically when Lovelace resources are managed in the UI (storage mode). In YAML mode, add `/hcl_lighting_static/hcl-curve-card.js` as a `module` resource yourself.)*

**After an update** of the integration, reload the dashboard page in the browser without cache (Ctrl+F5, on a Mac Cmd+Shift+R; in the companion app, reset the frontend cache in the app settings) so the new card version is loaded.

---

## ⚙️ Configuration

Open **Configure** on the integration entry. The options have three pages.

### 1. Curve and lights
*   **Lights to control**
*   **Wake Time**: Start of the active day (Default: 07:00).
*   **Midday Time**: The lowest point of the midday dip (Default: 12:30).
*   **Sleep Time**: End of the day (Default: 22:00). Wake and sleep time must be more than 6 hours apart.
*   **Min/Max Brightness**: Global limits for the curve (e.g., 10% - 100%). Curve values outside the limits are clipped to them; the dashboard card shades the clipped ranges and shows the effective brightness as a dashed line. Fixed scenarios (Focus, Relax, Cleaning) use their own values.
*   **Smart Transition Mode**: Enable this if your lights flash or stutter during updates. It separates brightness and colour commands.

The three anchors must leave room for the curve sectors (wake ramp 3 h, midday sector 30 min before to 3.5 h after midday, 4 h wind-down before sleep). If the midday time does not fit, it is moved to the nearest possible time; if the day is shorter than about 11 hours, the default profile is scaled to the wake–sleep span. A warning is logged in both cases.

> **Note**: A curve saved in the Dashboard Card takes precedence over the anchor times. Saving the options keeps it. **Changing Wake, Midday or Sleep Time discards the saved curve** and generates a new default curve from the new anchors. **REVERT** in the card only discards unsaved card edits and reloads the last saved curve.

### 2. Updates and manual control
| Option | Default | Meaning |
|---|---|---|
| Update interval | 27 s | Time between two update cycles (10–600 s) |
| Transition of updates | 20 s | Must be shorter than the update interval; lights without transition support ignore it |
| Transition when switched on | 0 s | Transition of the values sent right after a light is switched on |
| Return to HCL after manual control | 240 min | 0 = HCL never takes a paused light back automatically |
| Switching a light off ends manual control | on | Off: a paused light stays paused when it is switched off and on again |
| Keep manual control across restarts | off | On: paused lights stay paused after a Home Assistant restart |
| Keep values of turn-on commands | off | On: a light switched on through Home Assistant with its own brightness or colour (scene, automation, voice, app) keeps these values |

### 3. Scenarios
Brightness and colour temperature of **Focus** (100 % / 5500 K), **Relax** (40 % / 2700 K) and **Cleaning** (100 % / 4000 K), plus a **duration** in minutes after which these scenarios return to **Auto** (0 = until changed).

---

## 📖 Usage

Each instance is a device with these entities (IDs of new installations; existing installations keep their entity IDs, only the displayed names change):

| Entity | Example ID | Purpose |
|---|---|---|
| HCL active | `switch.living_room_hcl_active` | HCL on/off. Attribute `manual_control` lists the paused lights. |
| Adapt brightness | `switch.living_room_adapt_brightness` | Off: HCL leaves the brightness alone |
| Adapt colour temperature | `switch.living_room_adapt_colour_temperature` | Off: HCL leaves the colour temperature alone |
| Scenario | `select.living_room_scenario` | Auto, Focus, Relax, Cleaning, Guest, Sleep (also the chips of the card). Attribute `until`: end of a timed scenario. |
| Curve data | `sensor.living_room_curve_data` | Data for the card (state: time of the last curve/scenario change). Attributes include `preview_active` (the lights follow an unsaved preview), `wake_time` and `sleep_time`. |

The name part of the IDs follows the language Home Assistant used when the entity was created (e.g. `_hcl_aktiv` in German).

### Scenarios
*   **Auto**: follow the curve.
*   **Focus / Relax / Cleaning**: fixed values (configurable, optionally with a duration).
*   **Guest**: HCL sends no updates.
*   **Sleep**: lights that are on when Sleep is selected are faded off. A light switched on manually during Sleep counts as manual control and stays on until it is switched off (or the timeout expires).

### Manual control
HCL pauses a light (only this light; the HCL switch stays on) when
*   Home Assistant changes its brightness or colour with a command that does not come from HCL (app, dashboard, scene, automation, voice assistant), or
*   the light reports values that differ from HCL's values (e.g. changed with a wall switch or the manufacturer's app): brightness > 2 %, colour temperature > 100 K, XY colour > 0.05.

Changes of an attribute that HCL does not adapt (see the two adapt switches) do not pause the light.

A paused light returns to HCL when it is switched off and on again, or automatically after the configured time (default 4 hours) if it is still on, with a smooth 3-minute transition during which the normal updates leave the light alone (a scenario change ends it early); HCL never switches a light on. Paused lights stay paused when the curve or the options are saved, and optionally across restarts.

By default a light that is switched on receives the HCL values immediately, even if the turn-on command contained its own values. Enable **Keep values of turn-on commands** to keep them instead.

---

## 🔧 Technical Details

*   **Update Loop**: every 27 seconds by default (configurable).
*   **Interpolation**: **PCHIP** (Piecewise Cubic Hermite Interpolating Polynomial) - guarantees monotonicity.
*   **Manual Detection**: HCL sends its commands with its own context; commands with another context that change brightness or colour mark the light as manually controlled. State reports caused by HCL's own commands are ignored. State changes that are not caused by a Home Assistant command are compared with the thresholds above. Home Assistant assigns the context of the last command to state changes of a light within 5 seconds, so a change on the device itself within these 5 seconds after an HCL update is not detected.
*   **Traffic Optimization**:
    *   Brightness: Updates only if delta > 1%
    *   Kelvin: Updates only if delta > 50K (compared with the temperature the light can reach; lights in XY mode are compared by colour)
*   **Service `hcl_lighting.update_curve`** (used by the card): `entity_id` (HCL sensor or switch), `mode` (`preview`/`apply`: use the points until the next reload, `save`: store them, `revert`: reload the saved curve) and `points` (at least 2 × `{t: 0–1440 min, b: 0–100 %, k: 2000–7000 K}` with different times, not needed for `revert`). Invalid input is rejected.

---

## 🧪 Development

Tests use `pytest-homeassistant-custom-component` (Home Assistant tests) and Playwright with Chromium (dashboard card):

```bash
pip install pytest-homeassistant-custom-component playwright
python -m playwright install chromium
pytest tests            # Home Assistant / logic tests
pytest tests_frontend   # card tests (skipped without Playwright/Chromium)
```

GitHub Actions (`.github/workflows/tests.yml`) runs hassfest, the Home Assistant tests against the minimum supported release (2024.7.0) and the current release (2026.9.3), each with the matching pinned `pytest-homeassistant-custom-component`, plus the card tests in Chromium. When a new Home Assistant release should be covered, update the `ha`/`python`/`phcc` values of the "current" matrix entry.

---

## 🤝 Contributing & Support

*   **Issues**: [GitHub Issue Tracker](https://github.com/Ecronika/ha_hcl/issues)
*   **Discussion**: [Home Assistant Community](https://community.home-assistant.io/)

### License
MIT License. Copyright (c) 2026.
