"""Pure math calculations for HCL values."""
from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)

class HCLCalculator:
    """Calculator for HCL values using Cubic Hermite Spline interpolation."""

    # Time -> (Kelvin, Brightness %)
    # Using DIN SPEC 67600 inspired points
    # Format: (Minutes from Midnight, Kelvin, Brightness)
    POINTS = [
        (0, 2200, 10),           # 00:00
        (7 * 60, 2700, 30),      # 07:00
        (9 * 60, 4500, 50),      # 09:00
        (9 * 60 + 30, 5500, 75), # 09:30
        (10 * 60, 6500, 100),    # 10:00
        (12 * 60, 6500, 100),    # 12:00
        (12 * 60 + 30, 4000, 50),# 12:30 (Regeneration)
        (13 * 60, 4000, 50),     # 13:00
        (13 * 60 + 30, 6000, 75),# 13:30 (Re-Activation)
        (14 * 60, 6000, 75),     # 14:00
        (16 * 60, 4000, 50),     # 16:00
        (18 * 60, 2700, 30),     # 18:00
        (22 * 60, 2200, 10),     # 22:00
    ]
    
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
        # Defensive Input Validation
        min_brightness = max(0, min(100, min_brightness))
        max_brightness = max(0, min(100, max_brightness))

        current_minutes = now.hour * 60 + now.minute
        points = self.POINTS
        
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
