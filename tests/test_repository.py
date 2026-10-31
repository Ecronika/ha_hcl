"""Repository files that HACS and Home Assistant read (RM-T33)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]

# hacs.json keys HACS accepts (HACS_MANIFEST_JSON_SCHEMA, extra keys rejected)
HACS_KEYS = {
    "name", "content_in_root", "country", "filename", "hacs", "hide_default_branch",
    "homeassistant", "persistent_directory", "render_readme", "zip_release",
}


def test_rm_t33_hacs_json_has_only_keys_hacs_accepts():
    """0.9.0b4 had "domains" and "iot_class", which the HACS validation rejects."""
    data = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert "name" in data
    assert set(data) <= HACS_KEYS, set(data) - HACS_KEYS


def test_rm_t33_minimum_version_and_brand():
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["homeassistant"] == "2024.12.0"  # minimum version (README, CHANGELOG)
    assert (ROOT / "custom_components" / "hcl_lighting" / "brand" / "icon.png").is_file()
