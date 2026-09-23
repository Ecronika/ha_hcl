# HCL Lighting for Home Assistant

A **Human Centric Lighting (HCL)** custom integration for Home Assistant that automatically adjusts your lights' brightness and color temperature throughout the day to match natural circadian rhythms.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/Ecronika/ha_hcl.svg)](https://github.com/Ecronika/ha_hcl/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## ✨ Features

### 🎨 Interactive Dashboard (New in v0.4.0)
- **Visual Editor**: Visualize and edit your lighting curve with an interactive, touch-friendly chart.
- **Drag & Drop**: Simply drag control points to adjust Brightness and Color Temperature.
- **Biologically Accurate Presets**: One-click profiles for **Early Bird**, **Night Owl**, or **Shift Work**.
- **Live Validation**: Immediate feedback on "implausible" curves (e.g., bright blue light at midnight).

### 🧬 Biologically Inspired Core
- **PCHIP Interpolation**: Uses **Monotone Cubic Splines** for smooth, organic transitions without overshooting.
- **HCL Phases**:
    - **Morning**: Gradual warming up (Activating).
    - **Midday Dip**: A natural "Regeneration" dip around 12:30 PM (4000K).
    - **Focus**: High-Kelvin peaks for concentration.
    - **Evening**: Smooth wind-down to warm, dim light.

### 🧠 Intelligent Control
- **Smart Override 2.0**: Automatically detects manual changes (brightness or color) and pauses HCL control.
- **Traffic Control**: Updates are only sent if values change significantly (reducing Zigbee/WiFi traffic by ~90%).
- **Instant-On**: Lights turn on *immediately* with the correct circadian settings (no "Color Flash").
- **Capabilities**: Auto-detects RGB/XY support and simulates colour temperatures outside a bulb's native CT range via XY on colour-capable bulbs (supported range of the curve: 2000–7000 K). CT-only bulbs are driven to the nearest temperature they can reach.

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
3. Follow the setup wizard to name your instance (e.g., "Living Room") and select lights. Targets can be entities, devices, areas, floors or labels; light groups are expanded to their members (also for groups that finish loading after Home Assistant has started).

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

---

## ⚙️ Configuration

### Global Scheduling Options
Go to **Configure** on the integration entry to set your "Dynamic Anchors". These options generate the **Default Curve**:

*   **Wake Time**: Start of the active day (Default: 07:00).
*   **Midday Time**: The lowest point of the "Regeneration Dip" (Default: 12:30).
*   **Sleep Time**: End of the day (Default: 22:00).
*   **Min/Max Brightness**: Global limits for the curve (e.g., 10% - 100%). Curve values outside the limits are clipped to them; the dashboard card shades the clipped ranges. Fixed scenarios (Focus, Relax, Cleaning) use their own values.

The three anchors must leave room for the curve sectors (wake ramp 3 h, midday sector 30 min before to 3.5 h after midday, 4 h wind-down before sleep). If the midday time does not fit, it is moved to the nearest possible time; if the day is shorter than about 11 hours, the default profile is scaled to the wake–sleep span. A warning is logged in both cases.

> **Note**: A curve saved in the Dashboard Card takes precedence over the anchor times. Saving the options (targets, brightness limits, smart transition) keeps it. **Changing Wake, Midday or Sleep Time discards the saved curve** and generates a new default curve from the new anchors. **REVERT** in the card only discards unsaved card edits and reloads the last saved curve.

### Smart Options
*   **Smart Transition Mode**: Enable this if your lights flash or stutter during updates. It separates Brightness and Color commands.

---

## 📖 Usage

The integration creates a **Switch** entity (e.g., `switch.living_room_hcl_mode`; the name suffix follows the language Home Assistant used when the entity was created, e.g. `_hcl_modus` in German).

*   **ON**: HCL is active. Lights follow the curve.
*   **OFF**: HCL is paused. Lights behave like normal smart lights.
*   **Manual Override**: If you manually change a light (e.g., via Wall Switch or App), HCL control is **paused for that specific light**. The Main Switch remains **ON**. Turn the light **OFF and ON** again to resume circadian control. After **4 hours** HCL takes a paused light back automatically (smooth 3-minute transition) if it is still on; a light that is off is never switched on by HCL. Paused lights stay paused when the curve or the options are saved; a restart of Home Assistant clears all pauses.

A **Mode** select entity (e.g. `select.living_room_mode`, part of the same HCL device; also used by the chips of the dashboard card) switches between scenarios:

*   **Auto**: follow the curve.
*   **Focus / Relax / Cleaning**: fixed values (5500 K/100 %, 2700 K/40 %, 4000 K/100 %).
*   **Guest**: HCL sends no updates.
*   **Sleep**: lights that are on when Sleep is selected are faded off. A light switched on manually during Sleep counts as a manual override and stays on until it is switched off (or the 4-hour timeout expires).

---

## 🔧 Technical Details

*   **Update Loop**: Every **27 seconds** (periodic).
*   **Interpolation**: **PCHIP** (Piecewise Cubic Hermite Interpolating Polynomial) - guarantees monotonicity.
*   **Manual Detection Thresholds**:
    *   Brightness: > 2% deviation
    *   Color Temp: > 100K deviation
    *   XY Color: > 0.05 Euclidean distance
*   **Traffic Optimization**:
    *   Brightness: Updates only if delta > 1%
    *   Kelvin: Updates only if delta > 50K (compared with the temperature the light can reach; lights in XY mode are compared by colour)
*   **Service `hcl_lighting.update_curve`** (used by the card): `entity_id` (HCL sensor or switch), `mode` (`preview`/`apply`: use the points until the next reload, `save`: store them, `revert`: reload the saved curve) and `points` (at least 2 × `{t: 0–1440 min, b: 0–100 %, k: 2000–7000 K}`, not needed for `revert`). Invalid input is rejected.

---

## 🧪 Development

Tests use `pytest-homeassistant-custom-component` (Home Assistant tests) and Playwright with Chromium (dashboard card):

```bash
pip install pytest-homeassistant-custom-component playwright
python -m playwright install chromium
pytest tests --ignore=tests/test_hcl_math_v4.py   # Home Assistant / logic tests
pytest tests_frontend                             # card tests (skipped without Playwright/Chromium)
```

GitHub Actions (`.github/workflows/tests.yml`) runs the Home Assistant tests against the minimum supported release (2024.7.0) and the current release (2026.9.3), each with the matching pinned `pytest-homeassistant-custom-component`, plus the card tests in Chromium. When a new Home Assistant release should be covered, update the `ha`/`python`/`phcc` values of the "current" matrix entry.

`tests/test_hcl_math_v4.py` is a legacy standalone script that replaces Home Assistant modules with mocks; it is excluded from the regular run.

---

## 🤝 Contributing & Support

*   **Issues**: [GitHub Issue Tracker](https://github.com/Ecronika/ha_hcl/issues)
*   **Discussion**: [Home Assistant Community](https://community.home-assistant.io/)

### License
MIT License. Copyright (c) 2026.
