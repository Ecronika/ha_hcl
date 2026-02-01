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
- **Capabilities**: Auto-detects RGB/XY support to simulate Warm White (< 2000K) on capable bulbs.

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
3. Follow the setup wizard to name your instance (e.g., "Living Room") and select lights.

### 3. Setup Dashboard Card
**Automatic Setup (Recommended)**:
After installation, HCL Lighting creates a **Repair Issue** notification in Home Assistant with a one-click guide to add the card.

**Manual Setup**:
Add a "Manual" card to your dashboard with the following YAML:
```yaml
type: custom:hcl-curve-card
entity: sensor.hcl_lighting_curve
```
*(The frontend resource `hcl-curve-card.js` is automatically registered.)*

---

## ⚙️ Configuration

### Global Scheduling Options
Go to **Configure** on the integration entry to set your "Dynamic Anchors". These options generate the **Default Curve**:

*   **Wake Time**: Start of the active day (Default: 07:00).
*   **Midday Time**: The lowest point of the "Regeneration Dip" (Default: 12:30).
*   **Sleep Time**: End of the day (Default: 22:00).
*   **Min/Max Brightness**: Global scaling limits (e.g., 10% - 100%).

> **Note**: If you manually edit the curve in the Dashboard Card, your manual points take precedence over these time settings until you click **REVERT** in the UI.

### Smart Options
*   **Smart Transition Mode**: Enable this if your lights flash or stutter during updates. It separates Brightness and Color commands.

---

## 📖 Usage

The integration creates a **Switch** entity (e.g., `switch.hcl_living_room`).

*   **ON**: HCL is active. Lights follow the curve.
*   **OFF**: HCL is paused. Lights behave like normal smart lights.
*   **Manual Override**: If you manually change a light (e.g., via Wall Switch or App), the HCL Switch turns **OFF** automatically. Turn it back **ON** to resume circadian control.

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
    *   Kelvin: Updates only if delta > 50K

---

## 🤝 Contributing & Support

*   **Issues**: [GitHub Issue Tracker](https://github.com/Ecronika/ha_hcl/issues)
*   **Discussion**: [Home Assistant Community](https://community.home-assistant.io/)

### License
MIT License. Copyright (c) 2026.
