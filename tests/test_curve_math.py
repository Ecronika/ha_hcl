"""Curve maths: default curve (RM-R06/R07), PCHIP interpolation, midnight handling."""
from __future__ import annotations

import pytest

from datetime import datetime

from custom_components.hcl_lighting.logic.hcl_math import HCLCalculator, default_points



def _js_reference(points, t_target, key):
    """Port of hcl-curve-card.js _pchip (tripled arrays => circular curve)."""
    s = sorted(points, key=lambda p: p["t"])
    X, Y = [], []
    for off in (-1440, 0, 1440):
        for p in s:
            X.append(p["t"] + off)
            Y.append(p[key])
    i = 0
    while i < len(X) - 2 and t_target > X[i + 1]:
        i += 1

    def slope(a, b, c):
        dl, dr = b[0] - a[0], c[0] - b[0]
        if dl == 0 or dr == 0:
            return 0
        d1, d2 = (b[1] - a[1]) / dl, (c[1] - b[1]) / dr
        if d1 * d2 <= 0:
            return 0
        w1, w2 = 2 * dr + dl, dr + 2 * dl
        return (w1 + w2) / (w1 / d1 + w2 / d2)

    P = lambda j: (X[j], Y[j])
    cu, nx, pv, nn = P(i), P(i + 1), P(i - 1), P(i + 2)
    m0, m1 = slope(pv, cu, nx), slope(cu, nx, nn)
    h = nx[0] - cu[0]
    t = (t_target - cu[0]) / h
    t2, t3 = t * t, t * t * t
    return (2 * t3 - 3 * t2 + 1) * cu[1] + (t3 - 2 * t2 + t) * h * m0 + (-2 * t3 + 3 * t2) * nx[1] + (t3 - t2) * h * m1


DAY_ONLY = [
    {"t": t, "k": k, "b": b}
    for t, k, b in [
        (360, 2700, 20), (420, 4000, 50), (480, 5000, 80), (540, 6000, 100), (600, 6000, 100), (660, 5000, 80),
        (720, 4500, 70), (780, 5000, 80), (840, 4500, 70), (900, 3500, 50), (960, 3000, 40), (1020, 2700, 30),
    ]
]


# ---------------------------------------------------------------- B-41
@pytest.mark.usefixtures("evening")
def test_b41_midnight_24_00_is_the_same_moment_as_00_00():
    calc = HCLCalculator()
    calc.calculate_curve_from_points(
        [{"t": 540, "b": 20, "k": 2700}, {"t": 1200, "b": 21, "k": 2700}, {"t": 1440, "b": 5, "k": 2200}]
    )
    assert [p["t"] for p in calc.active_curve] == [0, 540, 1200]
    # 00:00 is exactly the point value (before 0.7.0 the curve was extrapolated here)
    assert calc.get_hcl_values(datetime(2026, 1, 1, 0, 0), 1, 100) == (5, 2200)


def test_pchip_single_point_safety():
    """A single point does not crash PCHIP: its value applies all day."""
    calc = HCLCalculator()
    calc.calculate_curve_from_points([{"t": 0, "k": 3000, "b": 50}])
    assert calc.get_hcl_values(datetime.now(), 0, 100) == (50, 3000)


def test_pchip_empty_safety():
    """An empty curve gives the minimum brightness and 2700 K."""
    calc = HCLCalculator()
    calc.active_curve = []
    assert calc.get_hcl_values(datetime.now(), 10, 100) == (10, 2700)


@pytest.mark.parametrize(("wake", "sleep"), [("07:00", "22:00"), ("06:30", "23:30"), ("09:00", "01:00"), ("05:00", "21:00")])
def test_rm_r06_default_curve(wake, sleep):
    """Night dim and warm until the wake time, quick morning rise (RM-R06)."""
    calc = HCLCalculator()
    calc.generate_curve(wake, sleep)
    w = int(wake[:2]) * 60 + int(wake[3:])
    s = int(sleep[:2]) * 60 + int(sleep[3:])

    def at(minute):
        minute %= 1440
        return calc.get_hcl_values(datetime(2026, 1, 1, minute // 60, minute % 60), 3, 100)

    night = (w - s) % 1440
    for m in range(15, night):  # from 15 min after the sleep time until the wake time
        b, k = at(s + m)
        assert b <= 5 and k <= 2200, (m, b, k)
    assert at(w - 1) == (5, 2200)  # no rise before the wake time
    b, k = at(w + 20)
    assert b >= 85 and k >= 4300
    assert at(w + 60) == (100, 5000)
    assert at(s) == (10, 2200)
    # the day has no dip (RM-R07): 100 % from wake + 1 h to sleep - 3 h
    for m in range(60, (s - w) % 1440 - 180, 15):
        assert at(w + m)[0] == 100, m


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


# ---------------------------------------------------------------- B-08 (default curve of 0.8.0, RM-R06/R07)
@pytest.mark.parametrize(
    ("wake", "sleep", "count"),
    [
        ("07:00", "22:00", 9),
        ("10:00", "23:00", 9),
        ("07:00", "21:00", 9),
        ("09:00", "01:00", 9),
        ("05:00", "22:00", 9),
        ("08:00", "15:00", 9),  # 7 h day: the reference day is scaled
        ("22:00", "14:00", 9),  # night shift
        ("07:00", "06:50", 7),  # 10 min night: no night plateau
    ],
)
def test_b08_anchor_curves_are_strictly_ordered(wake, sleep, count):
    pts = default_points(wake, sleep)
    assert len(pts) == count
    w = int(wake[:2]) * 60 + int(wake[3:])
    s = int(sleep[:2]) * 60 + int(sleep[3:])
    rel = [(p["t"] - w) % 1440 for p in pts]
    assert rel[0] == 0
    assert all(a < b for a, b in zip(rel, rel[1:])), f"not strictly increasing: {rel}"
    by_t = {p["t"]: (p["b"], p["k"]) for p in pts}
    assert by_t[w] == (30, 3000)  # wake time: gentle start
    assert by_t[s % 1440] == (10, 2200)  # sleep time


def test_b08_valid_default_anchors_unchanged():
    pts = default_points("07:00", "22:00")
    assert [(p["t"], p["b"], p["k"]) for p in pts] == [
        (420, 30, 3000), (440, 90, 4500), (480, 100, 5000), (720, 100, 6000),
        (1080, 100, 5000), (1140, 100, 5000), (1320, 10, 2200), (1335, 5, 2200), (419, 5, 2200),
    ]


# ---------------------------------------------------------------- B-09
def test_b09_two_point_curve_does_not_crash():
    calc = HCLCalculator()
    calc.calculate_curve_from_points([{"t": 360, "k": 2700, "b": 20}, {"t": 1200, "k": 5000, "b": 80}])
    for h in range(24):
        b, k = calc.get_hcl_values(datetime(2026, 1, 1, h, 0), 0, 100)
        assert 20 <= b <= 80 and 2700 <= k <= 5000


def test_b09_gap_over_12h_matches_card_and_has_no_overshoot():
    calc = HCLCalculator()
    calc.calculate_curve_from_points(DAY_ONLY)
    for m in range(0, 1440, 15):
        b, k = calc.get_hcl_values(datetime(2026, 1, 1, m // 60, m % 60), 0, 100)
        assert abs(b - round(_js_reference(DAY_ONLY, m, "b"))) <= 1, m
        assert abs(k - round(_js_reference(DAY_ONLY, m, "k"))) <= 1, m
        if m >= 1020 or m < 360:  # overnight segment 17:00 (30 %) -> 06:00 (20 %)
            assert 20 <= b <= 30, (m, b)


def test_b09_default_curve_unchanged():
    """Values of the default curve (07:00/22:00, RM-R06) are pinned."""
    calc = HCLCalculator()
    got = [calc.get_hcl_values(datetime(2026, 1, 1, h, 0), 3, 100) for h in (0, 3, 6, 9, 12, 15, 18, 21)]
    assert got == [(5, 2200), (5, 2200), (5, 2200), (100, 5396), (100, 6000), (100, 5500), (100, 5000), (43, 2926)]
