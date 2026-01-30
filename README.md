# HCL Lighting for Home Assistant

A **Human Centric Lighting (HCL)** custom integration for Home Assistant that automatically adjusts your lights' brightness and color temperature throughout the day to match natural circadian rhythms.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/Ecronika/ha_hcl.svg)](https://github.com/Ecronika/ha_hcl/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

✨ **Biologically-inspired light curves** based on DIN SPEC 67600 standard
- Smooth transitions using cubic Hermite spline interpolation
- Morning activation: gradual warm-up from 2200K → 6500K
- Midday regeneration dip: brief reduction around 12:30 PM
- Afternoon re-activation: second focus peak
- Evening wind-down: smooth transition back to warm tones

🎯 **Flexible targeting**
- Control lights by individual entities, devices, areas, or groups
- Automatic group expansion to individual lights
- Smart capability detection for each light

🧠 **Smart compatibility**
- Automatic detection of light capabilities (color temp, brightness-only, etc.)
- Extended warm white simulation using XY color for lights that don't support very low Kelvin values
- Optional "Smart Transition" mode to prevent visual artifacts on incompatible lights

⚙️ **Configurable**
- Set custom minimum and maximum brightness ranges
- Enable/disable smart transition mode
- Full UI configuration (no YAML required)

🔄 **Intelligent updates**
- Periodic updates (~30s) with smart delta detection
- Instant application when lights turn on (no color flash)
- State restoration after Home Assistant restart

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add `https://github.com/Ecronika/ha_hcl` as repository with category "Integration"
6. Click "Install" on the HCL Lighting card
7. Restart Home Assistant

### Manual Installation

1. Download the latest release from the [releases page](https://github.com/Ecronika/ha_hcl/releases)
2. Extract the `custom_components/hcl_lighting` folder to your Home Assistant `custom_components` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "HCL Lighting"
4. Select your target lights, devices, or areas
5. Configure options:
   - **Minimum Brightness**: Lowest brightness level (default: 10%)
   - **Maximum Brightness**: Highest brightness level (default: 100%)
   - **Smart Transition Mode**: Enable for better compatibility with some lights (default: disabled)

## Multiple Areas / Instances

You can create **multiple independent HCL instances** to control different areas with different schedules (e.g. "Living Room" vs "Home Office" or "Shift Work" vs "Normal").

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration** again
3. Select **HCL Lighting**
4. Configure the new instance with its own:
   - **Target Lights**: Select the lights for this specific zone
   - **Schedule**: Define unique Wake/Sleep times for this area
   - **Brightness Limits**: Set appropriate min/max brightness

Each instance creates its own Switch entity (e.g., `switch.hcl_lighting_living_room`, `switch.hcl_lighting_office`) which can be toggled independently.

## Usage

Once configured, the integration creates a switch entity:
- **Turn ON**: Lights will automatically follow the HCL curve
- **Turn OFF**: Integration stops controlling lights

The switch entity provides attributes showing:
- `calculated_brightness`: Current brightness percentage from HCL curve
- `calculated_color_temp`: Current color temperature in Kelvin
- `target_entities`: List of controlled lights

## HCL Curve Details

The integration uses a 24-hour curve with key control points:

| Time  | Color Temp | Brightness | Phase |
|-------|------------|------------|-------|
| Time  | Color Temp | Brightness | Phase |
|-------|------------|------------|-------|
| Wake | 2700K | 30% | Wake-up Start |
| +2h | 6500K | 100% | Full Activation |
| Midday | 5000K | 80% | Social Midday |
| +30m | 4000K | 50% | Regeneration Dip |
| +Re-Act | 6000K | 75% | Re-Activation |
| -4h Sleep | 3800K | 60% | Social Evening |
| -2h Sleep | 2700K | 30% | Wind-Down |
| Sleep | 2200K | 10% | Bedtime |

Transitions between these points use **cubic Hermite spline interpolation** for smooth, natural-feeling changes.

## Compatibility

Tested with:
- Philips Hue lights
- IKEA Trådfri lights
- Generic Zigbee lights
- Z-Wave lights

The integration automatically adapts to each light's capabilities:
- **Color temperature support**: Full HCL control
- **XY/RGB color support**: Warm white simulation for low Kelvin values
- **Brightness only**: Brightness curve without color temperature
- **On/Off only**: Skipped (no control possible)

## Technical Details

- **Update interval**: 27 seconds (periodic)
- **Transition duration**: 20 seconds (configurable via smart transition mode)
- **Update Thresholds** (Traffic Control):
  - Brightness: >1% change
  - Color temperature: >50K change
- **Override Thresholds** (Manual Detection):
  - Brightness: >2% deviation (with divergence detection)
  - Color temperature: >100K deviation (with steep slope tolerance)
  - Color (XY): >0.05 vector distance
- **Interpolation method**: Cubic Hermite splines with periodic boundary conditions

## Troubleshooting

**Lights don't update:**
- Ensure the HCL switch is turned ON
- Check that lights are turned on (integration only controls active lights)
- Verify lights are included in your target selection

**Color flashes when turning lights on:**
- This is expected behavior - the integration applies HCL settings instantly
- If undesired, you can disable the integration temporarily

**Incompatible transitions:**
- Enable "Smart Transition Mode" in the integration options
- This splits brightness and color updates to prevent visual artifacts

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Credits

- Inspired by DIN SPEC 67600 standard for biologically effective lighting
- Built for the Home Assistant community

## Support

If you encounter issues or have questions:
- Open an issue on [GitHub](https://github.com/Ecronika/ha_hcl/issues)
- Share your experience in the [Home Assistant Community](https://community.home-assistant.io/)
