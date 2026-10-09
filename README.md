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
- **Now marker**: A line shows the current time (in the Home Assistant time zone); below the charts the active scenario with its end (e.g. "until 07:00") and the values HCL sends now are shown (scenario and brightness limits included; from the setpoint sensors, "target values not available" while they have no value).
- **Scenario chips**: switch the scenario directly in the card. The curve can be edited in every scenario; it only applies in Auto.
- **Views**: full (default) or compact (`view: compact`: status and scenario chips, the editor opens on demand). The card has a visual editor and adapts to narrow columns (from 240 px) and Sections dashboards. In Sections dashboards keep the height on "auto": the height of the card changes with its content (editor open or closed, hints); with a fixed height the card scrolls inside.
- **Title**: the name of the instance (rename the entry under Settings → Devices & services, e.g. "Kitchen"), or `title:` in the card configuration.
- **Keyboard**: selected point: ↑/↓ value (PgUp/PgDn in larger steps), ←/→ time, Home/End minimum/maximum value, Shift = larger steps, Del/Backspace delete.
- **Screen readers**: every point is a slider ("Brightness point 1, 07:00, 30 %"); adjust its value with the slider gesture of the screen reader, or select it and enter time and values in the fields below the charts.
- **Preview, Save, Revert**: **Preview** sends the unsaved curve to the lights until the next reload, **Save** stores it (without reloading the integration), **Revert** loads the saved curve. Save is confirmed by Home Assistant; errors are shown in the card and the changes stay marked as unsaved. While the lights follow an unsaved preview, the card shows a hint.
- **Default curve**: the button **Default curve** loads the default curve for the wake and sleep time of the instance into the editor (save it to keep it). Up to 0.7 the card had fixed presets instead.
- **Live Validation**: Immediate hints on implausible curves (e.g. bright, cold light at night; night = sleep time to wake time).
- **Language and theme**: German/English texts following the Home Assistant language, time and number format of the Home Assistant profile; colours follow the active (light or dark) theme.
- **Unsaved changes are kept**: if the curve is changed elsewhere (another browser, a service call) while you edit, the card keeps your draft and offers to load the other curve.

### 🧬 Curve
- **PCHIP Interpolation**: Monotone cubic interpolation for smooth transitions without overshooting.
- **Default curve** (generated from the wake and sleep time; values for 07:00 / 22:00):
    - **Morning**: 30 % / 3000 K at wake time, 90 % / 4500 K 20 minutes later, 100 % / 5000 K after one hour – the morning light is bright soon.
    - **Day**: 100 %, the colour temperature rises to 6000 K five hours after wake time and returns to 5000 K four hours before sleep time. No midday dip.
    - **Evening**: from three hours before sleep time down to 10 % / 2200 K at sleep time.
    - **Night**: 5 % / 2200 K from 15 minutes after sleep time until wake time (orientation light; HCL never switches a light on).
    - The values are engineering choices between glare and effect; no standard defines them. A day shorter than about 9 hours gets the curve scaled to its span.

### 🧠 Control
- **Manual control**: HCL pauses a light when you change it yourself and resumes later (see [Manual control](#manual-control)).
- **Brightness and colour temperature separately**: Two switches per instance let HCL adapt only the colour temperature, only the brightness or both.
- **Traffic Control**: Updates are only sent when the values change noticeably (brightness > 1 %, colour temperature > 50 K).
- **Instant-On**: Lights receive the HCL values right after they are switched on, without transition (not in Guest mode; a light switched on during Sleep counts as manual control).
- **Setpoint sensors**: the values HCL sends now, as sensors for automations and gateways (see [Recipes](#recipes)).
- **Services**: apply now, set or release manual control, set a scenario with a duration, read the curve (see [Services](#services)).
- **Diagnostics and logbook**: diagnostics download on the integration page (without the instance name; entity, device, area, floor and label IDs replaced by pseudonyms such as `light.redacted_1`, manual control as its age in minutes; curve and wake/sleep times remain for troubleshooting – review the download before sharing it publicly); logbook entries and an event when a light starts or stops being under manual control.
- **Capabilities**: Lights with colour temperature are always driven by it, limited to the range they can reach (also RGBCCT lights: no colour jump at the range limit, no RGB white). Lights with colour but without colour temperature (XY, HS, RGB, RGBW, RGBWW) get it through an XY simulation (supported range of the curve: 2000–7000 K).

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
3. Name your instance (e.g. "Living Room"), select the lights (at least one target) and set the wake and sleep time. Targets can be entities, devices, areas, floors or labels; light groups are expanded to their members. Lights that are added to a selected area, device, floor or label later are picked up automatically. Areas, devices, floors and labels are resolved by Home Assistant itself, with the rules of the installed version (the same as for light actions). Typically hidden lights and configuration/diagnostic lights reached through a device or area (e.g. status LEDs of wall switches) are skipped, a light assigned to its own area belongs to that area, not to the area of its device, and on versions with child devices a device includes them. Details follow the installed version, e.g. whether a configuration/diagnostic light that carries a selected label itself is included. Lights given directly are always used.

**Requirements**: Home Assistant **2024.7** or newer.

### 3. Setup Dashboard Card
Edit a dashboard → **Add card** → search for **HCL Curve Card**. The visual editor lets you pick the instance and the view. After an instance has been added, a one-time notification shows the YAML with the exact entity ID.

**YAML**:
```yaml
type: custom:hcl-curve-card
entity: sensor.hcl_lighting_curve_data
```
The sensor is named `sensor.<instance name>_curve_data` (e.g. `sensor.living_room_curve_data`). Optional: `view: compact`, `title: Kitchen` (default: name of the instance).

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
*   **Lights to control**: at least one target (entities, devices, areas, floors, labels).
*   **Wake time**: Start of the active day (Default: 07:00).
*   **Sleep time**: End of the day (Default: 22:00). Wake and sleep time must be more than 6 hours apart.
*   **Minimum/Maximum brightness**: Global limits for the curve (1–100 %, minimum lower than maximum; default 3–100 %; instances set up before 0.8.0 keep their minimum, 10 % if it was never changed). Curve values outside the limits are clipped to them; the dashboard card shades the clipped ranges and shows the effective brightness as a dashed line. Focus, Relax and Cleaning also stay within the limits; Sleep and Night light do not (they are meant to be darker than a daytime minimum).
*   **Compatibility mode (slow/complex lights)**: Enable this if your lights flash or stutter during updates, e.g. IKEA TRÅDFRI (they fade only one value per command and ignore further commands during a colour fade). It sends brightness and colour in two separate commands, colour temperature without transition (transition 0, so no default transition of a light profile or of the light's integration applies); if that fails, the values are sent once without transition. It applies to updates with a transition; the values sent right after a light is switched on and updates without transition are always one command.

If the day is shorter than about 9 hours, the default curve is scaled to the wake–sleep span.

> **Note**: A curve saved in the Dashboard Card takes precedence over the anchor times. Saving the options keeps it. **Changing the wake or sleep time discards the saved curve** and generates a new default curve from the new anchors. **REVERT** in the card only discards unsaved card edits and reloads the last saved curve.

### 2. Updates and manual control
| Option | Default | Meaning |
|---|---|---|
| Return to HCL after manual control | 240 min | 0–1440 min; 0 = HCL never takes a paused light back automatically |
| Switching a light off ends manual control | on | Off: a paused light stays paused when it is switched off and on again. A light that is unavailable for up to 5 minutes (restart, radio dropout) stays paused; a longer gap counts as switched off |
| Keep manual control across restarts | off | On: paused lights stay paused after a Home Assistant restart |
| Keep values of turn-on commands | off | On: a light switched on through Home Assistant with its own brightness or colour (scene, automation, voice, app) keeps these values |


The collapsed section **Advanced: timing** holds the timing options; they rarely need a change:

| Option | Default | Meaning |
|---|---|---|
| Update interval | 27 s | Time between two update cycles (15–300 s) |
| Transition of updates | 20 s | 0–300 s, must be shorter than the update interval; lights without transition support ignore it |
| Transition when the scenario changes | = transition of updates | 0–300 s; also used when a timed scenario ends; may be longer than the update interval (the lights are left alone until it has finished) |

A light that is switched on gets the values at once, without transition (the option "Transition when switched on" of 0.6/0.7 was removed in 0.8.0).

### 3. Scenarios
Brightness (1–100 %) and colour temperature (2000–7000 K) of **Focus** (100 % / 5500 K), **Relax** (40 % / 2700 K), **Cleaning** (100 % / 4000 K) and **Night light** (3 % / 2200 K), plus a **duration** (0–1440 min) after which Focus, Relax and Cleaning return to **Auto** (0 = until changed). Sleep and Night light always return to Auto at the next wake time; `hcl_lighting.set_scenario` with `duration: 0` keeps them until changed.

### Notes on lights
Some bulbs have firmware limits that HCL cannot fix, but the options can work around them:
*   **IKEA TRÅDFRI** (and similar): enable the **compatibility mode** (see above).
*   **Lights that keep glowing after Sleep**: Sleep switches the lights off with the *transition when the scenario changes*. Some bulbs stay at their minimum level when switched off with a transition (reported for IKEA and AwoX/EGLO) while Home Assistant shows them off. Set this transition to 0 s.
*   **Lights that switch themselves back on** (reported for Sengled): switched off during a long transition, they may continue it. Use a short *transition of updates*.
*   **Previous colour visible when switching on**: HCL sends its values when the light reports on, so the light shows its previous values for a moment. To avoid that, switch it on with the HCL values (see *Recipes*). With ZHA, the option "Enhanced light transition" keeps such a command with a transition from fading from the previous colour.

---

## 📖 Usage

Each instance is a device with these entities (IDs of new installations; existing installations keep their entity IDs, only the displayed names change):

| Entity | Example ID | Purpose |
|---|---|---|
| HCL active | `switch.living_room_hcl_active` | HCL on/off. Disabling this entity stops the instance (the actions `apply`, `set_manual_control` and `set_scenario` then report it). Attribute `manual_control` lists the paused lights. Its attributes (`manual_control`, `target_entities`, `calculated_*`) are live values and not stored in the history; the history of the values is in the target sensors, manual control in the logbook. |
| Adapt brightness | `switch.living_room_adapt_brightness` | Off: HCL leaves the brightness alone (Sleep still switches lights off) |
| Adapt colour temperature | `switch.living_room_adapt_colour_temperature` | Off: HCL leaves the colour temperature alone |
| Scenario | `select.living_room_scenario` | Auto, Sleep, Night light, Focus, Relax, Cleaning, Guest (deprecated; also the chips of the card). Attribute `until`: end of a timed scenario. |
| Target brightness | `sensor.living_room_target_brightness` | Brightness HCL sends now (%, scenario and limits included; Sleep 0 %, Guest `unknown`) |
| Target colour temperature | `sensor.living_room_target_colour_temperature` | Colour temperature HCL sends now (K) |
| Curve data | `sensor.living_room_curve_data` | Data for the card (state: time of the last curve/scenario change). Attributes include `instance` (name of the instance, card title), `preview_active` (the lights follow an unsaved preview), `wake_time`, `sleep_time` and `default_points` (default curve for these times, used by the card's **Default curve** button). |

The name part of the IDs follows the language Home Assistant used when the entity was created (e.g. `_hcl_aktiv` in German).

### Scenarios
*   **Auto**: follow the curve.
*   **Focus / Relax / Cleaning**: fixed values (configurable, optionally with a duration), within the min/max brightness.
*   **Guest** (deprecated, removed in 0.9.0): HCL sends no updates – the same as switching *HCL active* off. Selecting it logs a warning and shows a repair issue; switch *HCL active* off instead.
*   **Sleep**: lights that are on when Sleep is selected are faded off. A light switched on manually during Sleep counts as manual control and stays on until it is switched off (or the timeout expires).
*   **Night light**: dim, warm light (default 3 % / 2200 K). Lights that are on, or are switched on during the night, get these values; HCL never switches a light on or off.

Sleep and Night light end at the next wake time (back to Auto). The setpoint sensors show the values independently of the adapt switches and of manual control. A scenario change is sent with the *transition when the scenario changes*.

### Manual control
HCL pauses a light (only this light; the HCL switch stays on) when
*   Home Assistant changes its brightness or colour with a command that does not come from HCL (app, dashboard, scene, automation, voice assistant), or
*   the light reports values that differ from HCL's values (e.g. changed with a wall switch or the manufacturer's app): brightness > 2 %, colour temperature > 100 K, XY colour > 0.05.

Changes of an attribute that HCL does not adapt (see the two adapt switches) do not pause the light. A light that is unavailable or unknown for up to 5 minutes (restart, radio dropout, bridge restart) stays paused; a longer gap counts as switched off.

A paused light returns to HCL when it is switched off and on again (with "Switching a light off ends manual control", the default), or automatically after the configured time (default 4 hours) if it is still on, with a smooth 3-minute transition during which the normal updates leave the light alone (a scenario change, a curve change or switching the light off end it early); HCL never switches a light on. Paused lights stay paused when the curve or the options are saved, and optionally across restarts.

By default a light that is switched on receives the HCL values immediately, even if the turn-on command contained its own values. Enable **Keep values of turn-on commands** to keep them instead.

### Services
| Service | Fields | Effect |
|---|---|---|
| `hcl_lighting.apply` | `entity_id` (any entity of the instance), `lights` (optional), `transition` (s, optional), `release_manual_control` | Sends the current values now to the lights that are on. Never switches a light on; paused lights are skipped unless `release_manual_control: true`. Not available in Guest mode. A transition longer than the update transition is not interrupted by the update cycles. Sends the values at the time of the call; ends with an error if a light command failed or a light did not answer within 10 s (the other lights are updated). |
| `hcl_lighting.set_manual_control` | `entity_id`, `lights` (optional, default all), `manual_control` (default `true`) | Pauses the lights or hands them back to HCL |
| `hcl_lighting.set_scenario` | `entity_id`, `scenario`, `duration` (min, optional; 0 = until changed) | Sets the scenario; a duration overrides the configured end |
| `hcl_lighting.get_curve` | `entity_id` | Response data: `points`, `saved_points`, `preview_active`, `wake_time`, `sleep_time` |
| `hcl_lighting.update_curve` | see [Technical Details](#-technical-details) | Used by the card |

**Permissions**: for a user with restricted permissions, the writing actions (`apply`, `set_manual_control`, `set_scenario`, `update_curve`) need control of the given HCL entity, of the instance's *HCL active* switch (and of the scenario select for `set_scenario`) and of the lights given in `lights`; `get_curve` needs read access. An action that sends the HCL values to the lights at once also needs control of every light of the instance, as if the user switched them directly: `apply` without `lights`, `set_manual_control` with `manual_control: false` (it updates the instance at once), `set_scenario`, `update_curve`, and choosing a scenario, switching *HCL active* on or an adapt switch on/off in the dashboard. Pausing lights (`manual_control: true`) and switching HCL off send no command. Automations and scripts are not restricted. The light commands HCL sends for an action are linked to it (parent context) and run as the user who caused them, so logbook and traces show where they came from; the periodic updates and the automatic end of a scenario run without a user.

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

*   **Update Loop**: every 27 seconds by default (configurable). Only one update runs at a time: a timer tick is skipped while an update is still sending, while updates requested by a scenario change, a curve preview/revert, the release of manual control or `apply` wait for it and are then sent (several requests are combined).
*   **Interpolation**: **PCHIP** (Piecewise Cubic Hermite Interpolating Polynomial) - guarantees monotonicity.
*   **Manual Detection**: HCL sends its commands with its own context; commands with another context that change brightness or colour mark the light as manually controlled. State changes that are not caused by a Home Assistant command are compared with the thresholds above. A report "on" with brightness 0 (e.g. a KNX light whose brightness status arrives just before or after its switching status) carries no brightness and is not compared for brightness. Home Assistant assigns the context of the last command to state changes of a light within 5 seconds, also to a change on the device itself (e.g. a wall dimmer). A state report with HCL's context therefore counts as HCL's own only if it fits the command (at the HCL value or moving towards it); a change beyond the light's previous value is manual control at once, a change back towards it is decided when the command's transition has ended (a light that has not reached the HCL value by then is manually controlled).
*   **Traffic Optimization**:
    *   Brightness: Updates only if delta > 1%
    *   Kelvin: Updates only if delta > 50K (compared with the temperature the light can reach; lights in XY mode are compared by colour)
*   **Colour temperature range**: lights with native colour temperature get the value they can reach (limited to their min/max), also when they support colour (since 0.8.0); lights with colour but without colour temperature get it through the XY simulation.
*   **One command per light**: HCL sends each light its own command, so a failing light does not hide the success of the others.
*   **Failed commands**: a light whose command failed is not treated as updated (no transition protection, no false manual control on its next report; this also applies to the command right after a light is switched on); the next update tries again. A light that keeps failing is logged once as a warning and once when it accepts commands again (repeats at debug level).
*   **Slow lights**: an update waits at most 10 s for its light commands and then goes on; the command is not cancelled. A light gets no further command while one is still running (also across a reload of the integration and when it is switched on).
*   **Service `hcl_lighting.update_curve`** (used by the card): `entity_id` (any entity of the instance), `mode` (default `preview`; `preview`/`apply`: use the points until the next reload, `save`: store them (without reloading the integration), `revert`: reload the saved curve) and `points` (at least 2 × `{t: 0–1440 min, b: 0–100 %, k: 2000–7000 K}` with different times, not needed for `revert`; 1440 counts as 00:00; other keys are ignored). Invalid input is rejected.
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

`tests/` is organised by responsibility (e.g. `test_manual_control_detection.py`, `test_light_commands.py`, `test_config_flow.py`); the roadmap IDs stay in the test names (`test_rm_b41_…`). Shared helpers live in `tests/support/` (entries and entity IDs, the light test double `FakeLights`, curves); test modules do not import each other.

GitHub Actions (`.github/workflows/tests.yml`) runs Ruff (rules in `ruff.toml`), hassfest, the Home Assistant tests against the minimum supported release (2024.7.0), the two releases at the boundary of Home Assistant's target helpers (2025.7.0, 2025.8.0) and the current release (2026.9.3), each with the matching pinned `pytest-homeassistant-custom-component`, plus the card tests in Chromium. When a new Home Assistant release should be covered, update the `ha`/`python`/`phcc` values of the "current" matrix entry.

---

## 🤝 Contributing & Support

*   **Issues**: [GitHub Issue Tracker](https://github.com/Ecronika/ha_hcl/issues)
*   **Discussion**: [Home Assistant Community](https://community.home-assistant.io/)

### License
MIT License. Copyright (c) 2026.
