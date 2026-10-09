"""Translations, error messages and services.yaml."""
from __future__ import annotations

import json
import pytest
import re
import yaml

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pathlib import Path

from custom_components.hcl_lighting.const import DOMAIN

from .support.entries import DIM, SWITCH, hcl_on, set_light, setup_entry
from .support.lights import FakeLights


async def _two_lights(hass, switch_on=True):
    lights = FakeLights(hass)
    for eid in ("light.a", "light.b"):
        set_light(hass, eid, "on", **DIM)
    entry = await setup_entry(hass, ["light.a", "light.b"])
    if switch_on:
        await hcl_on(hass)
    lights.calls.clear()
    return lights, entry


INTEGRATION = Path(__file__).parents[1] / "custom_components" / DOMAIN


def _exceptions(name):
    return json.loads((INTEGRATION / name).read_text(encoding="utf-8")).get("exceptions", {})


COMPONENT = Path(__file__).parent.parent / "custom_components" / "hcl_lighting"


# ---------------------------------------------------------------- RM-H06
def test_rm_h06_every_error_message_is_translated():
    keys_in_code = set()
    for source in INTEGRATION.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        keys_in_code |= set(re.findall(r'translation_key="(\w+)"', text))
        # no error with a fixed text for the caller
        assert not re.search(r"raise (HomeAssistantError|ServiceValidationError)\(\s*f?[\"']", text), source.name
    keys_in_code |= {"lights_failed", "lights_no_answer", "lights_failed_and_no_answer"}  # chosen at runtime
    issues = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))["issues"]
    keys_in_code -= set(issues)  # repair issues use translation_key too
    strings, en, de = (_exceptions(n) for n in ("strings.json", "translations/en.json", "translations/de.json"))
    assert keys_in_code and keys_in_code == set(strings) == set(en) == set(de)
    for key in strings:
        placeholders = set(re.findall(r"{(\w+)}", strings[key]["message"]))
        assert set(re.findall(r"{(\w+)}", de[key]["message"])) == placeholders, key


async def test_rm_h06_errors_carry_their_translation(hass, no_frontend_registration):
    lights, _entry = await _two_lights(hass)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "apply", {"entity_id": SWITCH, "lights": ["light.other"]}, blocking=True
        )
    assert err.value.translation_key == "not_controlled"
    assert str(err.value) == "Not controlled by this HCL instance: light.other"
    lights.fail = {"light.b"}
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH}, blocking=True)
    assert err.value.translation_key == "lights_failed"
    assert err.value.translation_placeholders["failed"] == "light.b"
    assert str(err.value).startswith("Light update failed for light.b: ")


# ---------------------------------------------------------------- RM-D05
def test_rm_d05_services_yaml_matches_the_schema():
    path = Path(__file__).parent.parent / "custom_components" / "hcl_lighting" / "services.yaml"
    update_curve = yaml.safe_load(path.read_text(encoding="utf-8"))["update_curve"]
    assert "name" not in update_curve and "description" not in update_curve  # texts in strings.json
    mode = update_curve["fields"]["mode"]
    assert mode["required"] is False and mode["default"] == "preview"


# ---------------------------------------------------------------- B-20
def test_b20_english_translation_has_issue_texts_and_name_label():
    # 0.7.0: the card hint is a notification (Ä-20); the only repair issue is F-08
    for fname in ("en.json", "de.json"):
        data = json.loads((COMPONENT / "translations" / fname).read_text(encoding="utf-8"))
        issue = data["issues"]["light_in_multiple_instances"]
        assert issue["title"] and "{light}" in issue["description"], fname
        assert data["config"]["step"]["user"]["data"]["name"], fname
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    assert strings["config"]["step"]["user"]["data"]["name"]
