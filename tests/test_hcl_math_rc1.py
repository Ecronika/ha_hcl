from custom_components.hcl_lighting.logic.hcl_math import HCLCalculator
from datetime import datetime
import unittest

class TestHCLMathRC1(unittest.TestCase):
    def test_pchip_single_point_safety(self):
        """Test that single point doesn't crash PCHIP."""
        calc = HCLCalculator()
        # Only one point: Should fall back to static value
        calc.calculate_curve_from_points([{'t': 0, 'k': 3000, 'b': 50}])
        
        try:
            b, k = calc.get_hcl_values(datetime.now(), 0, 100)
            self.assertEqual(k, 3000)
            self.assertEqual(b, 50)
        except ZeroDivisionError:
            self.fail("PCHIP crashed with ZeroDivisionError on single point")
            
    def test_pchip_empty_safety(self):
        """Test empty curve fallback."""
        calc = HCLCalculator()
        calc.active_curve = [] # Clear manually
        
        b, k = calc.get_hcl_values(datetime.now(), 10, 100)
        self.assertEqual(k, 2700) # Default fallback
        self.assertEqual(b, 10)   # bounded min_brightness (10 passed in args? no, 10 passed is min, but function uses max(1, min))
        # Wait, if points empty, returns min_brightness, 2700.
        # If min_brightness passed is 10, returns 10.

if __name__ == '__main__':
    unittest.main()
