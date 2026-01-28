"""Pure math calculations for HCL values."""
from __future__ import annotations

import logging

from datetime import time
from homeassistant.util import dt as dt_util

from ..const import (
    DEFAULT_MIN_BRIGHTNESS, 
    DEFAULT_MAX_BRIGHTNESS,
    DEFAULT_WAKE_TIME,
    DEFAULT_MIDDAY_TIME,
    DEFAULT_SLEEP_TIME
)

_LOGGER = logging.getLogger(__name__)

class HCLCalculator:
    """Calculator for HCL values using Cubic Hermite Spline interpolation."""

    # Time -> (Kelvin, Brightness %)
    # Using DIN SPEC 67600 inspired points
    # Format: (Minutes from Midnight, Kelvin, Brightness)
    # Dynamic Curve Storage
    active_curve = []
    
    def __init__(self):
        """Initialize with default curve."""
        self.generate_curve(DEFAULT_WAKE_TIME, DEFAULT_MIDDAY_TIME, DEFAULT_SLEEP_TIME)

    def generate_curve(self, wake_str: str, midday_str: str, sleep_str: str):
        """Generate the HCL curve based on 3 anchor points."""
        try:
            wake_time = dt_util.parse_time(wake_str) or dt_util.parse_time(DEFAULT_WAKE_TIME)
            midday_time = dt_util.parse_time(midday_str) or dt_util.parse_time(DEFAULT_MIDDAY_TIME)
            sleep_time = dt_util.parse_time(sleep_str) or dt_util.parse_time(DEFAULT_SLEEP_TIME)
        except Exception:
            _LOGGER.error("Error parsing HCL times, using defaults")
            wake_time = dt_util.parse_time(DEFAULT_WAKE_TIME)
            midday_time = dt_util.parse_time(DEFAULT_MIDDAY_TIME)
            sleep_time = dt_util.parse_time(DEFAULT_SLEEP_TIME)

        def to_min(t): return t.hour * 60 + t.minute
        
        w_min = to_min(wake_time)
        m_min = to_min(midday_time)
        s_min = to_min(sleep_time)

        # Basic Validation: Ensure logic doesn't break if times are weird
        # For v1 we assume 0..24h and user sanity, but we sort the points anyway.
        
        # Validate and Elasticize Sectors
        # Calculate available durations
        def get_duration(start, end):
            d = end - start
            if d < 0: d += 1440
            return d

        dur_wake_to_midday = get_duration(w_min, m_min)
        dur_midday_to_sleep = get_duration(m_min, s_min)
        
        # Define default offsets
        DEFAULT_WAKE_PEAK_OFFSET = 120    # +2h
        DEFAULT_MIDDAY_PRE_OFFSET = 30    # -30m
        
        # Factor for Wake Sector (Wake -> Midday)
        # We need space for Wake+2h AND Midday-30m. Total needed: 150m.
        needed_wm = DEFAULT_WAKE_PEAK_OFFSET + DEFAULT_MIDDAY_PRE_OFFSET
        factor_wm = 1.0
        if dur_wake_to_midday < needed_wm + 30: # +30m buffer
             factor_wm = dur_wake_to_midday / (needed_wm + 30)
             _LOGGER.warning("Elastic Curve: Compressing Morning Sector by factor %.2f", factor_wm)

        wake_peak_off = int(DEFAULT_WAKE_PEAK_OFFSET * factor_wm)
        midday_pre_off = int(DEFAULT_MIDDAY_PRE_OFFSET * factor_wm)


        # Factor for Midday Sector (Midday -> Sleep)
        # We have Midday+90m (Re-activation). 
        # New: Sleep-240m (Social Evening). Sleep-120m (Wind-down).
        # We need space for Re-activation offset (90) + Social Evening offset (240). Total 330m.
        needed_ms = 90 + 240
        factor_ms = 1.0
        if dur_midday_to_sleep < needed_ms + 30:
             factor_ms = dur_midday_to_sleep / (needed_ms + 30)
             _LOGGER.warning("Elastic Curve: Compressing Afternoon Sector by factor %.2f", factor_ms)
             
        midday_post_off = int(90 * factor_ms)
        social_evening_off = int(240 * factor_ms)
        wind_down_off = int(120 * factor_ms)

        # Construct Points based on Relative Offsets (Elastic)
        points = [
            # Wake Sector
            (w_min, 2700, 30),                 # Wake Up
            (w_min + wake_peak_off, 6500, 100),# +Elastic: Full Activation
            
            # Midday Sector
            (m_min - midday_pre_off, 6500, 100), # -Elastic: Pre-Lunch Peak
            (m_min, 5000, 80),                 # Lunch Start (Cozy)
            (m_min + 30, 4000, 50),            # Dip (Regeneration) - Keep 30m fixed for dip? Yes.
            (m_min + midday_post_off, 6000, 75), # +Elastic: Re-Activation
            
            # Sleep Sector
            (s_min - social_evening_off, 3800, 60), # -Elastic: Social Evening (Cozy Start)
            (s_min - wind_down_off, 2700, 30),      # -Elastic: Wind-Down (Melatonin Prep)
            (s_min, 2200, 10),                 # Bedtime
        ]
        
        # Dynamic Midnight wrapping
        # If the day wrap happens in a gradient, we need to ensure 1440 aligns with 0
        # If Sleep is 01:00, then 1440 (24:00) should be interpolated between Evening and Sleep.
        # But our interpolation engine handles the 1440->0 wrap automatically if we just don't define 1440 explicitly IF it's not a discrete point.
        # However, to be safe for the cubic spline, having a 1440 point is good for the last segment.
        
        # Let's calculate the "Virtual Midnight" value
        # This is simplified: We just clamp the result.
        points.append((0, 2200, 10)) # Ensure anchor at 0 exists
        points.append((1440, 2200, 10)) # Ensure anchor at 1440 exists
        
        # Normalize and Sort
        # Handle wrap-around or >1440 if offsets push it over
        final_points = []
        for m, k, b in points:
            
            # Simple approach for valid daily curve:
            # If minute < 0: add 1440
            # If minute >= 1440: sub 1440 (unless it's the exact end anchor 1440)
            
            norm_m = m
            if norm_m < 0: norm_m += 1440
            if norm_m > 1440: norm_m -= 1440 # 25:00 -> 01:00
            
            # Special logic: Do not fold 1440 back to 0, keep it as end anchor if intended
            if m == 1440: norm_m = 1440
            
            final_points.append((norm_m, k, b))
            
        # Ensure distinct points (overlapping times can cause div/0)
        # Sort by time
        final_points.sort(key=lambda x: x[0])
        
        # Deduplicate timestamps (keep last defined)
        unique_points = []
        seen_times = set()
        for p in final_points:
            if p[0] not in seen_times:
                unique_points.append(p)
                seen_times.add(p[0])
            else:
                 # Update existing
                 for i, ex in enumerate(unique_points):
                     if ex[0] == p[0]:
                         unique_points[i] = p
        
        self.active_curve = unique_points
        _LOGGER.debug("Generated HCL Curve with %d points: %s", len(self.active_curve), self.active_curve)
    
    MINUTES_PER_DAY = 1440
    
    def get_hcl_values(self, now, min_brightness: int, max_brightness: int) -> tuple[int, int]:
        """Calculate target Brightness and Color Temp for the given time.
        
        Args:
            now: datetime object
            min_brightness: User configured minimum brightness (0-100)
            max_brightness: User configured maximum brightness (0-100)
            
        Returns:
            tuple(brightness, kelvin)
        """
        # Defensive Input Validation & Coercion
        try:
            min_brightness = int(min_brightness) if min_brightness is not None else DEFAULT_MIN_BRIGHTNESS
            max_brightness = int(max_brightness) if max_brightness is not None else DEFAULT_MAX_BRIGHTNESS
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
        
        # 1. Find segment
        # Default to last segment (wrapping to start)
        idx = len(points) - 1
        
        # Check normal segments
        for i in range(len(points) - 1):
            if points[i][0] <= current_minutes < points[i+1][0]:
                idx = i
                break
        
        # 2. Extract Data for Segment [idx, idx+1]
        p0 = points[idx]
        p1 = points[(idx + 1) % len(points)]
        
        t0, k0, b0 = p0
        t1, k1, b1 = p1
        
        # Handle time wrapping
        dt_interval = t1 - t0
        if dt_interval < 0:
            dt_interval += self.MINUTES_PER_DAY
        
        # Division by zero guard
        if dt_interval == 0:
             _LOGGER.error("Degenerate segment detected in HCL curve (dt=0). Skipping interpolation.")
             return min_brightness, 4000 # Fail safe

        # 3. Calculate Normalized Time t (0..1)
        # Handle current_minutes crossing midnight relative to t0
        dist_from_t0 = current_minutes - t0
        if dist_from_t0 < 0:
            dist_from_t0 += self.MINUTES_PER_DAY
            
        t = dist_from_t0 / dt_interval
        
        # 4. Tangents (Slopes) for Catmull-Rom style spline
        # Need p_minus and p_plus for context
        p_minus = points[(idx - 1) % len(points)]
        p_plus = points[(idx + 2) % len(points)]
        
        # Calculate slopes for Kelvin and Brightness
        
        # Kelvin tangents
        # m0 = slope through p0 from p_minus to p1
        m0_k = self._get_slope(p_minus[0], p_minus[1], p1[0], p1[1])
        # m1 = slope through p1 from p0 to p_plus
        m1_k = self._get_slope(p0[0], p0[1], p_plus[0], p_plus[1])
        
        # Brightness tangents
        m0_b = self._get_slope(p_minus[0], p_minus[2], p1[0], p1[2])
        m1_b = self._get_slope(p0[0], p0[2], p_plus[0], p_plus[2])
        
        # 5. Cubic Hermite Interpolation
        # h00 = 2t^3 - 3t^2 + 1
        # h10 = t^3 - 2t^2 + t
        # h01 = -2t^3 + 3t^2
        # h11 = t^3 - t^2
        
        t2 = t * t
        t3 = t2 * t
        
        h00 = 2*t3 - 3*t2 + 1
        h10 = t3 - 2*t2 + t
        h01 = -2*t3 + 3*t2
        h11 = t3 - t2
        
        kelvin = h00*k0 + h10*dt_interval*m0_k + h01*k1 + h11*dt_interval*m1_k
        brightness = h00*b0 + h10*dt_interval*m0_b + h01*b1 + h11*dt_interval*m1_b
        
        # 6. Scale Brightness to User Limits
        # "User Min" should correspond to the "Lowest HCL Value" (Night = 10%),
        # not the theoretical 0%. Mapping [10, 100] -> [UserMin, UserMax].
        INTERNAL_MIN_HCL = 10.0
        INTERNAL_RANGE = 100.0 - INTERNAL_MIN_HCL
        
        # Normalize input (brightness from spline 10-100) to 0-1 range relative to effective curve
        normalized_b = (brightness - INTERNAL_MIN_HCL) / INTERNAL_RANGE
        
        # Clamp normalized to 0-1 (in case spline dipped slightly below 10)
        normalized_b = max(0.0, min(1.0, normalized_b))
        
        # Scale to user range
        scaled_b = min_brightness + normalized_b * (max_brightness - min_brightness)
        
        brightness = scaled_b

        # Clamp values to valid ranges
        brightness = max(1, min(100, int(brightness)))
        kelvin = max(2000, min(6500, int(kelvin)))
        
        return brightness, kelvin

    def _get_slope(self, t1, v1, t2, v2):
        """Calculate slope with periodic wraparound handling."""
        dt = t2 - t1
        if dt < 0:
            dt += self.MINUTES_PER_DAY
        if dt == 0:
            return 0
        return (v2 - v1) / dt
