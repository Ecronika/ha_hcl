import sys
from datetime import datetime, time, timedelta
import logging
import types

# Mock Home Assistant imports
mock_ha = types.ModuleType("homeassistant")
mock_ha.util = types.ModuleType("homeassistant.util")
mock_ha.util.dt = type('MockDtUtil', (), {
    'parse_time': lambda self, t_str: time(int(t_str.split(':')[0]), int(t_str.split(':')[1])) if isinstance(t_str, str) and ':' in t_str else None,
    'now': lambda self: datetime.now()
})()

mock_ha.config_entries = types.ModuleType("homeassistant.config_entries")
mock_ha.config_entries.ConfigEntry = type('ConfigEntry', (), {})

mock_ha.core = types.ModuleType("homeassistant.core")
mock_ha.core.HomeAssistant = type('HomeAssistant', (), {})

mock_ha.const = types.ModuleType("homeassistant.const")
mock_ha.const.Platform = type('Platform', (), {'SWITCH': 'switch', 'SENSOR': 'sensor'})

mock_ha.helpers = types.ModuleType("homeassistant.helpers")
mock_ha.helpers.entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
mock_ha.helpers.issue_registry = types.ModuleType("homeassistant.helpers.issue_registry")

sys.modules['homeassistant'] = mock_ha
sys.modules['homeassistant.util'] = mock_ha.util
sys.modules['homeassistant.util.dt'] = mock_ha.util.dt
sys.modules['homeassistant.config_entries'] = mock_ha.config_entries
sys.modules['homeassistant.core'] = mock_ha.core
sys.modules['homeassistant.const'] = mock_ha.const
sys.modules['homeassistant.helpers'] = mock_ha.helpers
sys.modules['homeassistant.helpers.entity_platform'] = mock_ha.helpers.entity_platform

logging.basicConfig(level=logging.DEBUG)

# Import the module under test
# We need to add the path to sys.path first
import os
sys.path.append(os.path.abspath("c:/Users/tpaul/.gemini/antigravity/scratch/ha_hcl"))

from custom_components.hcl_lighting.logic.hcl_math import HCLCalculator

def test_migration():
    print("--- Testing Migration ---")
    calc = HCLCalculator()
    
    # Test Migration Logic
    config = calc.migrate_legacy_config("07:00", "12:30", "22:00")
    points = config['points']
    
    print(f"Migrated Points Count: {len(points)}")
    for p in points:
        print(f"  t={p['t']}, k={p['k']}, b={p['b']}")
        
    # Expected v0.2.1 Replica (13 points including midnight/wrap logic which was 12 + 2 = 14 in generate_curve comment, but migration might differ)
    # My migration logic had 12 raw points.
    assert len(points) == 12, f"Expected 12 points, got {len(points)}"
    
    # Calculate with these points
    calc.calculate_curve_from_points(points)
    print("Curve Calculation successful.")

def test_pchip_interpolation():
    print("\n--- Testing PCHIP Interpolation ---")
    calc = HCLCalculator()
    
    # Define points that would cause overshoot in Cubic Spline but not PCHIP
    # A step up, then flat.
    points = [
        {'t': 0, 'k': 2000, 'b': 0},
        {'t': 360, 'k': 4000, 'b': 100}, # 06:00
        {'t': 720, 'k': 4000, 'b': 100}, # 12:00 (Flat top)
        {'t': 1080, 'k': 2000, 'b': 0},  # 18:00
    ]
    calc.calculate_curve_from_points(points)
    
    # Check 09:00 (midpoint of flat top transition)
    # Between 06:00 (100%) and 12:00 (100%).
    # PCHIP MUST be 100%. Catmull-Rom or Cubic might overshoot >100%.
    
    t_check = datetime(2023, 1, 1, 9, 0) # 540 min
    b, k = calc.get_hcl_values(t_check, 0, 100)
    print(f"Time 09:00 (Flat Top): Brightness={b}% (Expected 100%)")
    
    # Assert Monotonicity (Should not exceed 100)
    assert b == 100, f"PCHIP Overshoot detected! Got {b}, expected 100"
    
    # Check Ramp (03:00)
    # Between 0 (0%) and 6 (100%).
    # t=0.5. 
    # PCHIP on linear ramp should be close to linear but smoothed.
    t_ramp = datetime(2023, 1, 1, 3, 0) # 180 min
    b_ramp, k_ramp = calc.get_hcl_values(t_ramp, 0, 100)
    print(f"Time 03:00 (Ramp): Brightness={b_ramp}%")
    
    # Check Monotonicity in Ramp
    # Should be strictly increasing from 00:00 to 06:00
    prev_b = 0
    for h in range(0, 6):
        t = datetime(2023, 1, 1, h, 0)
        curr_b, _ = calc.get_hcl_values(t, 0, 100)
        assert curr_b >= prev_b, f"Monotonicity violation at {h}:00. {curr_b} < {prev_b}"
        prev_b = curr_b
        
    print("PCHIP Monotonicity verified.")

if __name__ == "__main__":
    test_migration()
    test_pchip_interpolation()
