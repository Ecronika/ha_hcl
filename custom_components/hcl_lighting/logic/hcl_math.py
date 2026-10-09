from __future__ import annotations

import logging
from typing import TypedDict, List
from homeassistant.util import dt as dt_util

from ..const import (
    DEFAULT_MIN_BRIGHTNESS, 
    DEFAULT_MAX_BRIGHTNESS,
    DEFAULT_WAKE_TIME,
    DEFAULT_SLEEP_TIME,
)

_LOGGER = logging.getLogger(__name__)

class HCLPoint(TypedDict):
    """Control point for HCL curve."""
    t: int # Minutes from midnight (0..1439)
    b: int # Brightness (0..100)
    k: int # Kelvin (2000..7000)

class CurveConfig(TypedDict):
    """Configuration for HCL curve."""
    points: List[HCLPoint]
    version: int

class HCLCalculator:
    """Calculator for HCL values using Free-hand Interpolation."""

    # Time -> (Kelvin, Brightness %)
    # Format: (Minutes from Midnight, Kelvin, Brightness)
    
    def __init__(self):
        """Initialize with default curve."""
        self.active_curve = []
        # True while the lights follow unsaved points (preview/apply from the card)
        self.preview_active = False
        # Boot with default config
        self.generate_curve(DEFAULT_WAKE_TIME, DEFAULT_SLEEP_TIME)

    def generate_curve_from_config(self, config: CurveConfig):
        """Generate the active curve from a CurveConfig object."""
        self.calculate_curve_from_points(config['points'])

    def calculate_curve_from_points(self, points: List[HCLPoint]):
        """Set the control points of the active curve.

        The curve is cyclic over one day. 24:00 (t=1440) is the same moment as
        00:00 and is stored as t=0; if both are given, the 00:00 point wins
        (the value the lights got at midnight before 0.7.0). Points are sorted
        and each time is kept once. get_hcl_values() interpolates them with
        PCHIP at runtime (same algorithm as the dashboard card).
        """
        if not points:
             _LOGGER.error("No points provided for curve calculation!")
             return

        normalized = []
        has_midnight = any(int(p['t']) % 1440 == 0 and int(p['t']) != 1440 for p in points)
        for p in points:
            t = int(p['t'])
            if t == 1440:
                if has_midnight:
                    _LOGGER.warning(
                        "Curve has points at 00:00 and 24:00 (the same moment); using the 00:00 point"
                    )
                    continue
                t = 0
            normalized.append({"t": t, "k": p['k'], "b": p['b']})

        unique_points = []
        seen = set()
        for p in sorted(normalized, key=lambda p: p['t']):
            if p['t'] not in seen:
                unique_points.append(p)
                seen.add(p['t'])

        self.active_curve = unique_points
        _LOGGER.debug("Calculated HCL Curve with %d control points", len(self.active_curve))

    def generate_curve(self, wake_str: str, sleep_str: str):
        """Set the default curve for the wake and sleep time (RM-R06/R07)."""
        self.calculate_curve_from_points(default_points(wake_str, sleep_str))

    MINUTES_PER_DAY = 1440
    
    def get_hcl_values(
        self, now, min_brightness: int, max_brightness: int
    ) -> tuple[int, int]:
        """Calculate target Brightness and Color Temp using PCHIP Interpolation (Monotone).
        
        Args:
            now: datetime object
            min_brightness: User configured minimum brightness (0-100)
            max_brightness: User configured maximum brightness (0-100)
            
        Returns:
            tuple(brightness, kelvin)
        """
        # Defensive Input Validation & Coercion
        try:
            min_brightness = int(float(min_brightness)) if min_brightness is not None else DEFAULT_MIN_BRIGHTNESS
            max_brightness = int(float(max_brightness)) if max_brightness is not None else DEFAULT_MAX_BRIGHTNESS
        except (ValueError, TypeError):
             _LOGGER.error("Invalid config types for brightness. Using defaults.")
             min_brightness = DEFAULT_MIN_BRIGHTNESS
             max_brightness = DEFAULT_MAX_BRIGHTNESS

        min_brightness = max(0, min(100, min_brightness))
        max_brightness = max(0, min(100, max_brightness))

        if min_brightness >= max_brightness:
             _LOGGER.error("Invalid brightness bounds (min=%d >= max=%d), check config! Using defaults.", min_brightness, max_brightness)
             min_brightness = DEFAULT_MIN_BRIGHTNESS
             max_brightness = DEFAULT_MAX_BRIGHTNESS

        current_minutes = now.hour * 60 + now.minute
        points = self.active_curve
        
        if not points:
            return min_brightness, 2700

        # Guard: Need at least 2 points for PCHIP
        if len(points) < 2:
            # Fallback to single point value or default
            val = points[0]
            # Use clamping logic for result
            b = max(1, min(100, val['b']))
            k = max(2000, min(7000, val['k']))
            
            # Apply user bounds to brightness
            out_b = max(min_brightness, min(max_brightness, b))
            return out_b, k

        # PCHIP requires context of the whole curve or at least neighbors.
        # Since we have relatively few points (e.g. 10-20), we can just PCHIP the whole 24h cycle
        # effectively or find the segment + slopes.
        # For efficient on-the-fly calculation without full pre-calc:
        # PCHIP slope at point i depends on points i-1, i, i+1.
        
        # 1. Find segment
        # Default to last segment (wrapping to start)
        idx = len(points) - 1
        
        # Check normal segments
        for i in range(len(points) - 1):
            if points[i]['t'] <= current_minutes < points[i+1]['t']:
                idx = i
                break
        
        # 2. Extract Neighbors for PCHIP
        # We need p[i-1], p[i], p[i+1], p[i+2] to calculate slopes at p[i] and p[i+1]
        n_points = len(points)
        
        curr_pt = points[idx]
        next_pt = points[(idx + 1) % n_points]
        
        # Calculate Slopes (m0 at curr_pt, m1 at next_pt)
        # Slope depends on left and right neighbors
        prev_pt = points[(idx - 1) % n_points]
        next_next_pt = points[(idx + 2) % n_points]
        
        # Slopes (_pchip_slope handles the wrap-around of the times itself)
        # Slope at Current Point
        mk_curr = self._pchip_slope(
            prev_pt['t'], prev_pt['k'], 
            curr_pt['t'], curr_pt['k'], 
            next_pt['t'], next_pt['k']
        )
        mb_curr = self._pchip_slope(
            prev_pt['t'], prev_pt['b'], 
            curr_pt['t'], curr_pt['b'], 
            next_pt['t'], next_pt['b']
        )

        # Slope at Next Point (idx+1)
        mk_next = self._pchip_slope(
            curr_pt['t'], curr_pt['k'], 
            next_pt['t'], next_pt['k'], 
            next_next_pt['t'], next_next_pt['k']
        )
        mb_next = self._pchip_slope(
            curr_pt['t'], curr_pt['b'], 
            next_pt['t'], next_pt['b'], 
            next_next_pt['t'], next_next_pt['b']
        )

        # 3. Cubic Hermite Interpolation using PCHIP slopes
        # Valid for interval [curr_pt, next_pt]
        
        # Normalized Time t (0..1)
        t0 = curr_pt['t']
        t1 = next_pt['t']
        dt = t1 - t0
        if dt < 0: dt += 1440
        
        if dt == 0: return curr_pt['b'], curr_pt['k'] # Fail safe

        # Current time relative to t0
        dist = current_minutes - t0
        if dist < 0: dist += 1440
        
        t = dist / dt
        
        # Evaluate
        kelvin = self._evaluate_hermite(t, dt, curr_pt['k'], next_pt['k'], mk_curr, mk_next)
        brightness = self._evaluate_hermite(t, dt, curr_pt['b'], next_pt['b'], mb_curr, mb_next)
        
        # 4. Clamp Results
        # Clamping (WYSIWYG)
        
        # User min/max are limits: curve values outside are clipped
        brightness = max(min_brightness, min(max_brightness, brightness))
        
        # Global bounds
        brightness = max(1, min(100, int(round(brightness))))
        kelvin = max(2000, min(7000, int(round(kelvin))))
        
        return brightness, kelvin

    def _pchip_slope(self, t_prev, y_prev, t_curr, y_curr, t_next, y_next):
        """Calculate PCHIP (Piecewise Cubic Hermite Interpolating Polynomial) slope.
        
        Uses weighted harmonic mean to ensure monotonicity (no overshoots).
        
        Args:
            t_prev, t_curr, t_next: Time in minutes (0-1439, wraps at midnight)
            y_prev, y_curr, y_next: Values (Brightness 0-100 or Kelvin 2000-7000)
        
        Returns:
            float: Slope (dy/dt) at t_curr, zero if local extremum detected
            
        Edge Cases:
            - Midnight wrap: 1430 -> 10 is a forward distance of 20 min
            - Gaps longer than 12 h stay positive (the curve is cyclic, the
              neighbours are always the previous/next point in time)
            - Flat segments: Returns 0 if |slope| < 1e-9
        """
        # Forward distances on the 24 h circle (prev -> curr -> next)
        dt_left = (t_curr - t_prev) % 1440
        dt_right = (t_next - t_curr) % 1440
        
        # Secants
        if dt_left == 0 or dt_right == 0: return 0
        
        d_left = (y_curr - y_prev) / dt_left
        d_right = (y_next - y_curr) / dt_right
        
        # PCHIP Logic:
        # If signs differ (peak/valley), slope is 0 to enforce monotonicity
        if d_left * d_right <= 0:
            return 0
            
        # PCHIP Zero-Division Guard (Flat lines)
        if abs(d_left) < 1e-9 or abs(d_right) < 1e-9:
            return 0
        
        # Harmonic Mean for slope (Weighted by interval lengths)
        # w1 = 2*h_rate + h_left
        # w2 = h_right + 2*h_rate
        # This is the standard PCHIP formula for non-uniform grids
        
        w1 = 2 * dt_right + dt_left
        w2 = dt_right + 2 * dt_left
        
        return (w1 + w2) / (w1 / d_left + w2 / d_right)

    def _evaluate_hermite(self, t, h, y0, y1, m0, m1):
        """Evaluate Cubic Hermite Spline at normalized time t."""
        # t: 0..1
        # h: interval length (x1 - x0) - needed because m0/m1 are dy/dx
        # y0, y1: values
        # m0, m1: slopes
        
        t2 = t*t
        t3 = t2*t
        
        h00 = 2*t3 - 3*t2 + 1
        h10 = t3 - 2*t2 + t
        h01 = -2*t3 + 3*t2
        h11 = t3 - t2
        
        # Standard Hermite formula uses derivatives w.r.t t (0..1), so scale slopes by h
        return h00*y0 + h10*h*m0 + h01*y1 + h11*h*m1


# Default curve (RM-R06/R07): (minutes from the anchor, kelvin, brightness %).
# Day: from the wake time - a gentle start, activation within 20 minutes, a
# bright plateau, cooler towards midday (wake + 5 h) ...
_FROM_WAKE = ((0, 3000, 30), (20, 4500, 90), (60, 5000, 100), (300, 6000, 100))
# ... back to 5000 K, from 3 h before the sleep time down to 10 % / 2200 K
_TO_SLEEP = ((-240, 5000, 100), (-180, 5000, 100), (0, 2200, 10))
# Night (sleep to wake time): dim and warm for orientation; the rise starts at
# the wake time, not before
_NIGHT = (2200, 5)
_NIGHT_AFTER_SLEEP = 15
_NIGHT_MIN_MINUTES = 30
# The day needs this span for the points above (wake + 5 h < sleep - 4 h);
# a shorter day (> 6 h, checked by the config flow) gets the reference day
# (07:00-22:00) scaled to its span.
_FULL_DAY_MINUTES = 300 + 240 + 1
_REFERENCE_DAY_MINUTES = 900
_FALLBACK = ("07:00", "22:00")


def _minutes(value: str | None, default: str) -> int:
    parsed = dt_util.parse_time(str(value)) if value else None
    parsed = parsed or dt_util.parse_time(default)
    return parsed.hour * 60 + parsed.minute


def default_points(wake_str: str | None, sleep_str: str | None) -> List[HCLPoint]:
    """Control points of the default curve for a wake and sleep time (RM-R06/R07)."""
    wake = _minutes(wake_str, DEFAULT_WAKE_TIME)
    sleep = _minutes(sleep_str, DEFAULT_SLEEP_TIME)
    span = (sleep - wake) % 1440
    if span <= 360:  # rejected by the config flow; old or invalid data
        _LOGGER.warning("Wake-sleep span (%d min) too short; using 07:00-22:00", span)
        wake, sleep = _minutes(_FALLBACK[0], DEFAULT_WAKE_TIME), _minutes(_FALLBACK[1], DEFAULT_SLEEP_TIME)
        span = (sleep - wake) % 1440
    day = [(t, k, b) for t, k, b in _FROM_WAKE] + [(span + t, k, b) for t, k, b in _TO_SLEEP]
    if span < _FULL_DAY_MINUTES:
        scale = span / _REFERENCE_DAY_MINUTES
        reference = [(t, k, b) for t, k, b in _FROM_WAKE] + [
            (_REFERENCE_DAY_MINUTES + t, k, b) for t, k, b in _TO_SLEEP
        ]
        day = [(round(t * scale), k, b) for t, k, b in reference]
    night = 1440 - span
    if night >= _NIGHT_MIN_MINUTES:
        day += [(span + _NIGHT_AFTER_SLEEP, *_NIGHT), (night + span - 1, *_NIGHT)]
    return [{"t": (wake + t) % 1440, "k": k, "b": b} for t, k, b in day]
