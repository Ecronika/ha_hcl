from __future__ import annotations

import logging
import math
from typing import TypedDict, List
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
        # Boot with default config
        self.generate_curve(DEFAULT_WAKE_TIME, DEFAULT_MIDDAY_TIME, DEFAULT_SLEEP_TIME)

    def generate_curve_from_config(self, config: CurveConfig):
        """Generate the active curve from a CurveConfig object."""
        self.calculate_curve_from_points(config['points'])

    def calculate_curve_from_points(self, points: List[HCLPoint]):
        """Calculate the 24h curve (96 points) from explicit control points using Cosine Interpolation.
        Matches logic in hcl_dashboard.html (v0.4.7).
        """
        if not points:
             _LOGGER.error("No points provided for curve calculation!")
             return

        # Sort points by time
        sorted_points = sorted(points, key=lambda p: p['t'])
        
        # Prepare X, B, K arrays with wrapping (-1440, 0, +1440)
        X = []
        B = []
        K = []
        
        for offset in [-1440, 0, 1440]:
            for p in sorted_points:
                X.append(p['t'] + offset)
                B.append(p['b'])
                K.append(p['k'])
        
        # Interpolate 24h cycle (every 15 min -> 97 points incl 1440)
        # We store this as self.active_curve for lookup.
        # Format: (t, k, b) tuple list.
        # NOTE: self.active_curve in v0.3.0 logic was a list of Control Points used for Spline calculation at runtime.
        # In v0.4.0 (Free-hand), we are pre-calculating the 15-min resolution curve here? 
        # OR are we storing the Control Points and interpolating at runtime?
        # The Dashboard does PCHIP at runtime.
        # BUT: The switch logic expects `self.active_curve` to be the Spline Control Points for Cubic Hermite.
        # 
        # CRITICAL DECISION:
        # To support "Free-hand" with potentially many points, the old "Hermite Loop" in get_hcl_values is too rigid (it assumes sparse points).
        # We should PRE-CALCULATE the 24h curve at high resolution (e.g. 1 min or 5 min) and just look it up.
        # OR we verify if we can just use the Cosine Interp at runtime.
        # Given the dashboard code uses Cosine Interp ("pchip" named function), we should use that at runtime.
        # So `active_curve` will store the Control Points (sorted, distinct).
        
        self.active_curve = []
        # Logic: We just store the points as Tuples (t, k, b) for compatibility with get_hcl_values logic?
        # No, get_hcl_values logic is hardcoded for Cubic Hermite. 
        # We need to UPDATE get_hcl_values to use the new interpolation if we change the structure.
        # For now, let's keep active_curve as the explicit list of control points (tuples),
        # And update get_hcl_values to use Cosine Interpolation instead of Hermite.
        
        # Convert HCLPoints to tuples for internal storage
        # Tuple: (t, k, b) - wait, HCLPoint is t,b,k? No, HCLPoint is dict. 
        # existing points were (t, k, b). HCLPoint has keys.
        # Let's verify usage in get_hcl_values. p0[0] is t, p0[1] is k, p0[2] is b.
        
        unique_points = []
        seen = set()
        for p in sorted_points:
            if p['t'] not in seen:
                 # Store as internal DICT for frontend compatibility + readability
                 unique_points.append({"t": p['t'], "k": p['k'], "b": p['b']})
                 seen.add(p['t'])
        
        self.active_curve = unique_points
        _LOGGER.debug("Calculated HCL Curve with %d control points", len(self.active_curve))

    def generate_curve(self, wake_str: str, midday_str: str, sleep_str: str):
        """Legacy wrapper: Generate curve from 3 anchors (v0.3.0 style) -> Migrates to v0.4.0 points."""
        config = self.migrate_legacy_config(wake_str, midday_str, sleep_str)
        self.generate_curve_from_config(config)

    def migrate_legacy_config(self, wake_str: str, midday_str: str, sleep_str: str) -> CurveConfig:
        """Migrate v0.3.0 anchors to v0.4.0 explicit point list (v0.2.1 Replica Profile)."""
        try:
            wake_time = dt_util.parse_time(wake_str) or dt_util.parse_time(DEFAULT_WAKE_TIME)
            midday_time = dt_util.parse_time(midday_str) or dt_util.parse_time(DEFAULT_MIDDAY_TIME)
            sleep_time = dt_util.parse_time(sleep_str) or dt_util.parse_time(DEFAULT_SLEEP_TIME)
        except Exception:
            wake_time = dt_util.parse_time(DEFAULT_WAKE_TIME)
            midday_time = dt_util.parse_time(DEFAULT_MIDDAY_TIME)
            sleep_time = dt_util.parse_time(DEFAULT_SLEEP_TIME)

        def to_min(t): return t.hour * 60 + t.minute
        
        w_min = to_min(wake_time)
        m_min = to_min(midday_time)
        s_min = to_min(sleep_time)

        # Sanity Check: Prevent invalid or compressed spans
        # Calculate active day duration (accounting for midnight wrap)
        total_span = (s_min - w_min) % 1440
        if total_span <= 360: # Less than 6 hours active day is suspicious
            _LOGGER.warning(
                "Legacy config has very short wake-sleep span (%d min). Using safe defaults.", 
                total_span
            )
            w_min, m_min, s_min = 420, 750, 1320 # Fallback 07:00, 12:30, 22:00

        # v0.2.1 Replica Logic (Offsets)
        # Structure: time, kelvin, brightness
        raw_points = [
            # Wake Sector
            (w_min, 2700, 30),
            (w_min + 120, 4500, 50),
            (w_min + 150, 5500, 75),
            (w_min + 180, 6500, 100),
            
            # Midday Sector
            (m_min - 30, 6500, 100),
            (m_min, 4000, 50), # Dip
            (m_min + 30, 4000, 50),
            (m_min + 60, 6000, 75),
            (m_min + 90, 6000, 75),
            (m_min + 210, 4000, 50),
            
            # Sleep Sector
            (s_min - 240, 2700, 30),
            (s_min, 2200, 10),
        ]

        # Convert to HCLPoint list
        points: List[HCLPoint] = []
        for t, k, b in raw_points:
            # Normalize t
            norm_t = t
            if norm_t < 0: norm_t += 1440
            if norm_t >= 1440: norm_t -= 1440
            
            points.append({"t": norm_t, "k": k, "b": b})
            
        return {"points": points, "version": 2}
    
    MINUTES_PER_DAY = 1440
    
    def get_hcl_values(self, now, min_brightness: int, max_brightness: int) -> tuple[int, int]:
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
        
        # Time Handling for Slopes
        # We need to normalize times relative to the specific wrap-around context
        
        # Calculate slope at Current Point (idx) using (idx-1, idx, idx+1)
        # Times relative to curr_pt
        t_prev_rel = prev_pt['t'] - curr_pt['t']
        if t_prev_rel >= 0: t_prev_rel -= 1440 # Previous is in past
        
        t_next_rel = next_pt['t'] - curr_pt['t']
        if t_next_rel <= 0: t_next_rel += 1440 # Next is in future
        
        # Calculate slope pairs
        # Secants d0, d1
        # d0 = (y0 - y_prev) / (t0 - t_prev)
        # d1 = (y1 - y0) / (t1 - t0)
        
        def safe_div(n, d): return n / d if d != 0 else 0
        
        # Kelvin Slopes
        # Let's standardize input for _pchip_slope
        
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
        
        # Apply user min/max to brightness
        brightness = max(min_brightness, min(max_brightness, brightness))
        
        # Global bounds
        brightness = max(1, min(100, int(round(brightness))))
        kelvin = max(2000, min(7000, int(round(kelvin))))
        
        return brightness, kelvin

    def _pchip_slope(self, t_prev, y_prev, t_curr, y_curr, t_next, y_next):
        """Calculate monotonic slope at t_curr given neighbors."""
        # Handle wrapping for time diffs
        dt_left = t_curr - t_prev
        if dt_left <= 0: dt_left += 1440
        
        dt_right = t_next - t_curr
        if dt_right <= 0: dt_right += 1440
        
        # Secants
        if dt_left == 0 or dt_right == 0: return 0
        
        d_left = (y_curr - y_prev) / dt_left
        d_right = (y_next - y_curr) / dt_right
        
        # PCHIP Logic:
        # If signs differ (peak/valley), slope is 0 to enforce monotonicity
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
