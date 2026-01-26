"""Constants for the HCL Lighting integration."""

DOMAIN = "hcl_lighting"
CONF_TARGET = "target"
HCL_TRANSITION_SECONDS = 30
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
OVERRIDE_BRIGHTNESS_DELTA = 5      # >5% brightness change = override
OVERRIDE_KELVIN_DELTA = 200        # >200K color temp change = override
# Smooth Re-engagement Transition
REENGAGE_STEPS = 6
REENGAGE_INTERVAL_SECONDS = 30
