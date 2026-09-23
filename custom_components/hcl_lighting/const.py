"""Constants for the HCL Lighting integration."""

DOMAIN = "hcl_lighting"
CONF_TARGET = "target"
HCL_TRANSITION_SECONDS = 20 # Reduced to ensure completion before next 27s update
UPDATE_INTERVAL_SECONDS = 27
BRIGHTNESS_THRESHOLD = 1
KELVIN_THRESHOLD = 50
XY_COLOR_SENSITIVITY = 5.0
KELVIN_RANGE = 4500.0
CONF_SMART_TRANSITION = "smart_transition"
CONF_MIN_BRIGHTNESS = "min_brightness"
CONF_MAX_BRIGHTNESS = "max_brightness"

# Capability Cache Version
# v1 (implicit): v0.2.0 and earlier
# v2: v0.2.1+ (Safe state caching)
CAPABILITY_CACHE_VERSION = 2

# Defaults
DEFAULT_MIN_BRIGHTNESS = 10
DEFAULT_MAX_BRIGHTNESS = 100

# Manual Override Detection
OVERRIDE_TIMEOUT_HOURS = 4
OVERRIDE_BRIGHTNESS_DELTA = 2      # >2% (Safety margin against jitter/rounding noise)
OVERRIDE_KELVIN_DELTA = 100        # >100K (Must be >56K to survive steepest HCL dip at 12:15)
# Smooth Re-engagement Transition
REENGAGE_STEPS = 6
REENGAGE_INTERVAL_SECONDS = 30

# Dynamic Curve Anchors
CONF_WAKE_TIME = "wake_time"
CONF_MIDDAY_TIME = "midday_time"
CONF_SLEEP_TIME = "sleep_time"

DEFAULT_WAKE_TIME = "07:00"
DEFAULT_MIDDAY_TIME = "12:30"
DEFAULT_SLEEP_TIME = "22:00"

# v0.4.0 Interactive UI
SERVICE_UPDATE_CURVE = "update_curve"
CONF_CURVE_CONFIG = "curve_config"

ATTR_CURVE_VERSION = "curve_version"
ATTR_CURVE_HASH = "curve_hash"
ATTR_SAMPLE_COUNT = "sample_count"
ATTR_SAMPLES = "samples"

# Release Hardening Constants
XY_COLOR_DISTANCE_THRESHOLD = 0.05 # Euclidean distance in CIE 1931 space
IGNORE_WINDOW_SECONDS = 2.0        # Seconds to ignore events after setting a value
 
# v0.5.0 Scenario Engine
CONF_SCENARIOS = "scenarios"
 
MODE_AUTO = "auto"
MODE_SLEEP = "sleep"
MODE_FOCUS = "focus"
MODE_RELAX = "relax"
MODE_CLEANING = "cleaning"
MODE_GUEST = "guest"
 
HCL_MODES = [
    MODE_AUTO,
    MODE_SLEEP,
    MODE_FOCUS,
    MODE_RELAX,
    MODE_CLEANING,
    MODE_GUEST,
]
 
SCENARIO_DEFAULTS = {
    # 5500K is "Focus" enough without being harsh blue (6500K+)
    MODE_FOCUS: {"brightness": 100, "kelvin": 5500},
    # 2700K is standard warm white, 40% is good for reading
    MODE_RELAX: {"brightness": 40, "kelvin": 2700},
    # 4000K is neutral white, good for cleaning visibility
    MODE_CLEANING: {"brightness": 100, "kelvin": 4000},
    # Sleep logic handles the "0", but we define it data-model wise
    MODE_SLEEP: {"brightness": 0, "kelvin": 2000}, 
    MODE_GUEST: {"brightness": None, "kelvin": None}, 
}

# v0.6.0 Options (behaviour)
CONF_UPDATE_INTERVAL = "update_interval"            # seconds between update cycles
CONF_TRANSITION = "transition"                      # seconds, transition of cycle updates
CONF_TURN_ON_TRANSITION = "turn_on_transition"      # seconds, transition when a light is switched on
CONF_OVERRIDE_TIMEOUT = "override_timeout"          # minutes until HCL takes a paused light back, 0 = never
CONF_OVERRIDE_RESET_ON_OFF = "override_reset_on_off"  # switching a light off ends its manual control
CONF_PERSIST_OVERRIDES = "persist_overrides"        # keep manual control across HA restarts
CONF_RESPECT_TURN_ON_VALUES = "respect_turn_on_values"  # turn-on commands with own values are not overwritten

DEFAULT_UPDATE_INTERVAL = UPDATE_INTERVAL_SECONDS
DEFAULT_TRANSITION = HCL_TRANSITION_SECONDS
DEFAULT_TURN_ON_TRANSITION = 0
DEFAULT_OVERRIDE_TIMEOUT = OVERRIDE_TIMEOUT_HOURS * 60
DEFAULT_OVERRIDE_RESET_ON_OFF = True
DEFAULT_PERSIST_OVERRIDES = False
DEFAULT_RESPECT_TURN_ON_VALUES = False

# v0.6.0 Options (scenarios)
CONF_SCENARIO_DURATION = "scenario_duration"        # minutes until Focus/Relax/Cleaning return to Auto, 0 = never
DEFAULT_SCENARIO_DURATION = 0
TIMED_MODES = (MODE_FOCUS, MODE_RELAX, MODE_CLEANING)
CONFIGURABLE_SCENARIOS = (MODE_FOCUS, MODE_RELAX, MODE_CLEANING)


def scenario_option_keys(mode: str) -> tuple[str, str]:
    """Option keys (brightness, kelvin) of a configurable scenario."""
    return f"{mode}_brightness", f"{mode}_kelvin"
