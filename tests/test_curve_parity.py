"""The dashboard card computes the same curve as the integration (B-41, Ä-05).

Runs the curve maths of hcl-curve-card.js in Node.js and compares every
minute of the day with HCLCalculator. Skipped when Node.js is not installed.
"""
from __future__ import annotations

import json
import random
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from custom_components.hcl_lighting.logic.hcl_math import HCLCalculator

CARD = Path(__file__).parents[1] / "custom_components" / "hcl_lighting" / "frontend" / "hcl-curve-card.js"
NODE = shutil.which("node")


def _curves():
    rnd = random.Random(7)
    random_points = sorted(rnd.sample(range(0, 1440, 15), 30))
    return {
        "default": None,  # default curve of the integration
        "two_points": [{"t": 360, "b": 20, "k": 2700}, {"t": 1200, "b": 80, "k": 5000}],
        "night_owl_24h": [{"t": 540, "b": 20, "k": 2700}, {"t": 1200, "b": 21, "k": 2700}, {"t": 1440, "b": 5, "k": 2200}],
        "contradictory_midnight": [{"t": 0, "b": 10, "k": 2200}, {"t": 720, "b": 50, "k": 4000}, {"t": 1440, "b": 90, "k": 6500}],
        "random_30": [{"t": t, "b": rnd.randint(0, 100), "k": rnd.randrange(2000, 7001, 50)} for t in random_points],
    }


def _js(curves, limits):
    src = CARD.read_text(encoding="utf-8")
    maths = src[src.index("// ---------------------------------------------------------------- 2. curve maths"):
                src.index("// ---------------------------------------------------------------- 3. formatting")]
    script = maths + f"""
const curves = {json.dumps(curves)}, limits = {json.dumps(limits)}, out = {{}};
for (const [name, pts] of Object.entries(curves)) {{
  const norm = hclNormalize(pts);
  out[name] = [];
  for (let m = 0; m < 1440; m++) {{
    const v = hclValueAt(norm, m);
    out[name].push([v.b, v.k, ...limits.map(l => hclEffectiveB(v.b, l))]);
  }}
}}
console.log(JSON.stringify(out));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason="Node.js not installed")
def test_card_and_integration_compute_the_same_curve():
    curves = _curves()
    default = HCLCalculator().active_curve
    curves["default"] = [dict(p) for p in default]
    limits = [
        {"minB": 10, "maxB": 100, "scale": False},
        {"minB": 20, "maxB": 60, "scale": False},
        {"minB": 20, "maxB": 60, "scale": True},
    ]
    js = _js(curves, limits)
    for name, points in curves.items():
        calc = HCLCalculator()
        calc.calculate_curve_from_points(points)
        for minute in range(1440):
            now = datetime(2026, 1, 1, minute // 60, minute % 60)
            row = js[name][minute]
            b_raw, k = row[0], row[1]
            _b, k_py = calc.get_hcl_values(now, 0, 100)
            assert abs(k - k_py) <= 0.5 + 1e-6, (name, minute, k, k_py)
            for index, limit in enumerate(limits):
                b_py, _k = calc.get_hcl_values(now, limit["minB"], limit["maxB"], scale=limit["scale"])
                b_js = max(1, row[2 + index])  # the integration never sends less than 1 %
                assert abs(b_js - b_py) <= 0.5 + 1e-6, (name, minute, limit, b_js, b_py, b_raw)
