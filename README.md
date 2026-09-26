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
- **Now marker**: A line shows the current time (in the Home Assistant time zone); below the charts the values HCL sends now are shown (scenario, brightness limits and scaling included; from the setpoint sensors, "not available" while they have no value).
- **Scenario chips**: switch the scenario directly in the card. The curve can be edited in every scenario; it only applies in Auto.
- **Views**: full (default) or compact (`view: compact`: status and scenario chips, the editor opens on demand). The card has a visual editor and adapts to narrow columns (from 240 px) and Sections dashboards.
- **Keyboard**: selected point: ↑/↓ value (PgUp/PgDn in larger steps), ←/→ time, Home/End minimum/maximum value, Shift = larger steps, Del delete.
- **Save status**: Save is confirmed by Home Assistant; errors are shown in the card and the changes stay marked as unsaved. While the lights follow an unsaved preview, the card shows a hint.
- **Presets**: One-click profiles **Default** (the integration's default curve), **Default with quiet night** (5 % / 2200 K from sleep time), **Default without midday dip**, **Focus**, **Relax**, **Early Bird** and **Night Owl**.
- **Live Validation**: Immediate hints on implausible curves (e.g. bright, cold light at night; night = sleep time to wake time).
- **Language and theme**: German/English texts following the Home Assistant language, time and number format of the Home Assistant profile; colours follow the active (light or dark) theme.
- **Unsaved changes are kept**: if the curve is changed elsewhere (another browser, a service call) while you edit, the card keeps your draft and offers to load the other curve.

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
- **Setpoint sensors**: the values HCL sends now, as sensors for automations and gateways (see [Recipes](#recipes)).
- **Services**: apply now, set or release manual control, set a scenario with a duration, read the curve (see [Services](#services)).
- **Diagnostics and logbook**: diagnostics download on the integration page; logbook entries and an event when a light starts or stops being under manual control.
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
Edit a dashboard → **Add card** → search for **HCL Curve Card**. The visual editor lets you pick the instance and the view. After an instance has been added, a one-time notification shows the YAML with the exact entity ID.

**YAML**:
```yaml
type: custom:hcl-curve-card
entity: sensor.hcl_lighting_curve_data
```
The sensor is named `sensor.<instance name>_curve_data` (e.g. `sensor.living_room_curve_data`). Optional: `view: compact`.

**Card resource**: registered automatically when Lovelace resources are managed in the UI (storage mode), as `/hcl_lighting_static/hcl-curve-card.js?v=<version>`; an update replaces the entry. In YAML mode add it yourself:
```yaml
lovelace:
  resources:
    - url: /hcl_lighting_static/hcl-curve-card.js
      type: module
```
**Manual installation without HACS**: copy `custom_components/hcl_lighting` into the `custom_components` folder of your configuration and restart Home Assistant.

**Removing the integration**: the card resource stays in the dashboard resources (Settings → Dashboards → ⋮ → Resources); delete it there if you no longer use the card.

**After an update** of the integration, reload the dashboard page in the browser without cache (Ctrl+F5, on a Mac Cmd+Shift+R; in the companion app, reset the frontend cache in the app settings) so the new card version is loaded.

---

## ⚙️ Configuration

Open **Configure** on the integration entry. The options have three pages.

### 1. Curve and lights
*   **Lights to control**
*   **Wake Time**: Start of the active day (Default: 07:00).
*   **Midday Time**: The lowest point of the midday dip (Default: 12:30).
*   **Sleep Time**: End of the day (Default: 22:00). Wake and sleep time must be more than 6 hours apart.
*   **Min/Max Brightness**: Global limits for the curve (e.g., 10% - 100%). Curve values outside the limits are clipped to them; the dashboard card shades the clipped ranges and shows the effective brightness as a dashed line. Fixed scenarios (Focus, Relax, Cleaning) use their own values unless *Limit scenarios* is on (page 3).
*   **Scale to min/max instead of clipping** (default off): the curve range 10–100 % is mapped onto min–max (b' = min + (b − 10) · (max − min) / 90), so the shape of the curve is kept; values below 10 % end at min.
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
| Transition when the scenario changes | = transition of updates | Also used when a timed scenario ends; may be longer than the update interval (the lights are left alone until it has finished) |

### 3. Scenarios
Brightness and colour temperature of **Focus** (100 % / 5500 K), **Relax** (40 % / 2700 K), **Cleaning** (100 % / 4000 K) and **Night light** (3 % / 2200 K), plus a **duration** in minutes after which Focus, Relax and Cleaning return to **Auto** (0 = until changed).
*   **Limit Focus/Relax/Cleaning to min/max brightness** (default off).
*   **Sleep and Night light end at the wake time** (default off): they switch back to Auto at the next wake time.

---

## 📖 Usage

Each instance is a device with these entities (IDs of new installations; existing installations keep their entity IDs, only the displayed names change):

| Entity | Example ID | Purpose |
|---|---|---|
| HCL active | `switch.living_room_hcl_active` | HCL on/off. Attribute `manual_control` lists the paused lights. |
| Adapt brightness | `switch.living_room_adapt_brightness` | Off: HCL leaves the brightness alone |
| Adapt colour temperature | `switch.living_room_adapt_colour_temperature` | Off: HCL leaves the colour temperature alone |
| Scenario | `select.living_room_scenario` | Auto, Sleep, Night light, Focus, Relax, Cleaning, Guest (also the chips of the card). Attribute `until`: end of a timed scenario. |
| Target brightness | `sensor.living_room_target_brightness` | Brightness HCL sends now (%, scenario and limits included; Sleep 0 %, Guest `unknown`) |
| Target colour temperature | `sensor.living_room_target_colour_temperature` | Colour temperature HCL sends now (K) |
| Curve data | `sensor.living_room_curve_data` | Data for the card (state: time of the last curve/scenario change). Attributes include `preview_active` (the lights follow an unsaved preview), `wake_time` and `sleep_time`. |

The name part of the IDs follows the language Home Assistant used when the entity was created (e.g. `_hcl_aktiv` in German).

### Scenarios
*   **Auto**: follow the curve.
*   **Focus / Relax / Cleaning**: fixed values (configurable, optionally with a duration).
*   **Guest**: HCL sends no updates.
*   **Sleep**: lights that are on when Sleep is selected are faded off. A light switched on manually during Sleep counts as manual control and stays on until it is switched off (or the timeout expires).
*   **Night light**: dim, warm light (default 3 % / 2200 K). Lights that are on, or are switched on during the night, get these values; HCL never switches a light on or off.

The setpoint sensors show the values independently of the adapt switches and of manual control. A scenario change is sent with the *transition when the scenario changes*.

### Manual control
HCL pauses a light (only this light; the HCL switch stays on) when
*   Home Assistant changes its brightness or colour with a command that does not come from HCL (app, dashboard, scene, automation, voice assistant), or
*   the light reports values that differ from HCL's values (e.g. changed with a wall switch or the manufacturer's app): brightness > 2 %, colour temperature > 100 K, XY colour > 0.05.

Changes of an attribute that HCL does not adapt (see the two adapt switches) do not pause the light.

A paused light returns to HCL when it is switched off and on again, or automatically after the configured time (default 4 hours) if it is still on, with a smooth 3-minute transition during which the normal updates leave the light alone (a scenario change ends it early); HCL never switches a light on. Paused lights stay paused when the curve or the options are saved, and optionally across restarts.

By default a light that is switched on receives the HCL values immediately, even if the turn-on command contained its own values. Enable **Keep values of turn-on commands** to keep them instead.

### Services
| Service | Fields | Effect |
|---|---|---|
| `hcl_lighting.apply` | `entity_id` (any entity of the instance), `lights` (optional), `transition` (s, optional), `release_manual_control` | Sends the current values now to the lights that are on. Never switches a light on; paused lights are skipped unless `release_manual_control: true`. Not available in Guest mode. A transition longer than the update transition is not interrupted by the update cycles. |
| `hcl_lighting.set_manual_control` | `entity_id`, `lights` (optional, default all), `manual_control` (default `true`) | Pauses the lights or hands them back to HCL |
| `hcl_lighting.set_scenario` | `entity_id`, `scenario`, `duration` (min, optional; 0 = until changed) | Sets the scenario; a duration overrides the configured end |
| `hcl_lighting.get_curve` | `entity_id` | Response data: `points`, `saved_points`, `preview_active`, `wake_time`, `midday_time`, `sleep_time` |
| `hcl_lighting.update_curve` | see [Technical Details](#-technical-details) | Used by the card |

Event `hcl_lighting_manual_control` (`entity_id`, `manual_control`, `instance`, `config_entry_id`) is fired when a light starts or stops being under manual control. If the same light is adapted by two instances for the same attribute, a repair issue names the light and the instances.

### Recipes
**Switch a light on with the HCL values** (e.g. for bulbs that cannot take values while off, or a KNX/DALI gateway):
```yaml
action: light.turn_on
target:
  entity_id: light.bedside
data:
  brightness_pct: "{{ states('sensor.living_room_target_brightness') | int(50) }}"
  color_temp_kelvin: "{{ states('sensor.living_room_target_colour_temperature') | int(3000) }}"
```
In Sleep the target brightness is 0 % (the light is switched off); in Guest mode the sensors are `unknown` and the defaults in `int(...)` are used.

**Hand all lights back to HCL at the wake time**:
```yaml
triggers:
  - trigger: time
    at: "07:00:00"
actions:
  - action: hcl_lighting.set_manual_control
    data:
      entity_id: switch.living_room_hcl_active
      manual_control: false
```

**Copy the curve to another instance**:
```yaml
- action: hcl_lighting.get_curve
  data:
    entity_id: sensor.living_room_curve_data
  response_variable: curve
- action: hcl_lighting.update_curve
  data:
    entity_id: sensor.bedroom_curve_data
    mode: save
    points: "{{ curve.points }}"
```

**Daylight (lux)**: HCL does not read light sensors. Automations can react to a lux sensor with the services above, e.g. pause lights with `set_manual_control` and switch them off while there is enough daylight, and hand them back afterwards.

---

## 🔧 Technical Details

*   **Update Loop**: every 27 seconds by default (configurable).
*   **Interpolation**: **PCHIP** (Piecewise Cubic Hermite Interpolating Polynomial) - guarantees monotonicity.
*   **Manual Detection**: HCL sends its commands with its own context; commands with another context that change brightness or colour mark the light as manually controlled. State reports caused by HCL's own commands are ignored. State changes that are not caused by a Home Assistant command are compared with the thresholds above. Home Assistant assigns the context of the last command to state changes of a light within 5 seconds, so a change on the device itself within these 5 seconds after an HCL update is not detected.
*   **Traffic Optimization**:
    *   Brightness: Updates only if delta > 1%
    *   Kelvin: Updates only if delta > 50K (compared with the temperature the light can reach; lights in XY mode are compared by colour)
*   **Service `hcl_lighting.update_curve`** (used by the card): `entity_id` (HCL sensor or switch), `mode` (`preview`/`apply`: use the points until the next reload, `save`: store them, `revert`: reload the saved curve) and `points` (at least 2 × `{t: 0–1440 min, b: 0–100 %, k: 2000–7000 K}` with different times, not needed for `revert`; 1440 counts as 00:00). Invalid input is rejected.
*   **RGBW/RGBWW lights** get the colour temperature through the XY simulation. Home Assistant's own conversion to the white channels was checked for 0.7.0 and not used: the white-channel range of such lights is not available and values outside it produce invalid channel values.

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
