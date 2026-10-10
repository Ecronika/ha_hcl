"""Static path and Lovelace resource of the card, card hint."""
from __future__ import annotations

import json
import pytest

from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE
from pathlib import Path
from pytest_homeassistant_custom_component.common import MockConfigEntry
from unittest.mock import AsyncMock, MagicMock

from custom_components.hcl_lighting.ha_internals import async_register_lovelace_resource
from custom_components.hcl_lighting.const import DOMAIN

from .support.entries import CT_ATTRS, set_light, setup_entry


COMPONENT = Path(__file__).parent.parent / "custom_components" / "hcl_lighting"


CARD_URL = "/hcl_lighting_static/hcl-curve-card.js?v=" + json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))["version"]


async def _register_with_storage(hass, hass_storage, items):
    """Run the resource registration against an unloaded storage collection (state at HA start)."""
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    hass_storage["lovelace_resources"] = {
        "version": 1,
        "minor_version": 1,
        "key": "lovelace_resources",
        "data": {"items": items},
    }
    collection = ResourceStorageCollection(hass, MagicMock())
    assert collection.loaded is False
    hass.data["lovelace"] = MagicMock(resources=collection)
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    await async_register_lovelace_resource(hass)
    await hass.async_block_till_done()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)  # flush delayed store writes (as on shutdown)
    await hass.async_block_till_done()
    # What the frontend sees later: a fresh load from storage.
    fresh = ResourceStorageCollection(hass, MagicMock())
    await fresh.async_get_info()
    return sorted(i["url"] for i in fresh.async_items())


def _notifications(hass):
    from homeassistant.components import persistent_notification

    return persistent_notification._async_get_or_create_notifications(hass)


# ------------------------------------------------------------------ Ä-15 / Ä-16
async def test_a16_frontend_registered_once(hass):
    """Static path once per run; setup of further entries and reloads only check it."""
    from unittest.mock import AsyncMock
    from custom_components.hcl_lighting.ha_internals import async_register_lovelace_resource

    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "http", {})
    hass.http.async_register_static_paths = AsyncMock()
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    hass.config_entries.async_update_entry(entry, options={"max_brightness": 90})  # reload
    await hass.async_block_till_done()
    second = MockConfigEntry(domain=DOMAIN, title="Zwei", data={"name": "Zwei", "target": {"entity_id": ["light.a"]}})
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()
    await async_register_lovelace_resource(hass)
    assert hass.http.async_register_static_paths.await_count == 1


# ---------------------------------------------------------------- Ä-20 card hint
@pytest.mark.usefixtures("evening")
async def test_a20_card_hint_is_a_one_time_notification(hass, no_frontend_registration):
    from homeassistant.components import persistent_notification
    from homeassistant.helpers import issue_registry as ir

    entry = await setup_entry(hass, ["light.a"])
    notifications = persistent_notification._async_get_or_create_notifications(hass)
    nid = f"{DOMAIN}_card_{entry.entry_id}"
    assert "sensor.hcl_curve_data" in notifications[nid]["message"]
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"setup_curve_card_{entry.entry_id}") is None
    persistent_notification.async_dismiss(hass, nid)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert nid not in notifications


@pytest.mark.usefixtures("evening")
async def test_a20_upgrade_removes_the_old_repair_issue_without_new_hint(hass, no_frontend_registration):
    from homeassistant.components import persistent_notification
    from homeassistant.helpers import issue_registry as ir
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain=DOMAIN, title="HCL", data={"name": "HCL", "target": {"entity_id": ["light.a"]}})
    entry.add_to_hass(hass)
    ir.async_create_issue(
        hass, DOMAIN, f"setup_curve_card_{entry.entry_id}", is_fixable=False,
        severity=ir.IssueSeverity.WARNING, translation_key="setup_curve_card",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"setup_curve_card_{entry.entry_id}") is None
    assert f"{DOMAIN}_card_{entry.entry_id}" not in persistent_notification._async_get_or_create_notifications(hass)


# ---------------------------------------------------------------- B-52 / Ä-26 registration
@pytest.mark.usefixtures("evening")
async def test_b52_missing_lovelace_is_retried_and_version_from_manifest(hass):
    import json
    from pathlib import Path
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.hcl_lighting.ha_internals import async_register_lovelace_resource

    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    assert await async_register_lovelace_resource(hass) is False  # no Lovelace yet
    collection = MagicMock()
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    collection.__class__ = ResourceStorageCollection
    collection.async_get_info = AsyncMock()
    collection.async_items = MagicMock(return_value=[
        {"id": "old", "type": "module", "url": "/hcl_lighting_static/hcl-curve-card.js?v=0.6.1"}
    ])
    collection.async_update_item = AsyncMock()
    collection.async_create_item = AsyncMock()
    collection.async_delete_item = AsyncMock()
    hass.data["lovelace"] = MagicMock(resources=collection)
    assert await async_register_lovelace_resource(hass) is True
    version = json.loads((Path(__file__).parents[1] / "custom_components/hcl_lighting/manifest.json").read_text())["version"]
    collection.async_update_item.assert_awaited_once_with(
        "old", {"res_type": "module", "url": f"/hcl_lighting_static/hcl-curve-card.js?v={version}"}
    )
    collection.async_create_item.assert_not_awaited()
    collection.async_delete_item.assert_not_awaited()
    assert hass.http.async_register_static_paths.await_count == 1


@pytest.mark.usefixtures("evening")
async def test_b52_failed_registration_is_not_marked_done(hass):
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.hcl_lighting.ha_internals import async_register_lovelace_resource
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    collection = MagicMock()
    collection.__class__ = ResourceStorageCollection
    collection.async_get_info = AsyncMock()
    collection.async_items = MagicMock(return_value=[])
    collection.async_create_item = AsyncMock(side_effect=RuntimeError("storage"))
    hass.data["lovelace"] = MagicMock(resources=collection)
    assert await async_register_lovelace_resource(hass) is False
    collection.async_create_item = AsyncMock(return_value={"id": "new"})
    assert await async_register_lovelace_resource(hass) is True


# ---------------------------------------------------------------- B-14
async def test_b14_existing_resources_preserved_and_not_duplicated(hass, hass_storage):
    items = [
        {"id": "user", "type": "module", "url": "/local/other-card.js"},
        {"id": "abc", "type": "module", "url": CARD_URL},
    ]
    urls = await _register_with_storage(hass, hass_storage, items)
    assert urls == sorted(["/local/other-card.js", CARD_URL])


async def test_b14_old_version_resource_is_replaced(hass, hass_storage):
    items = [
        {"id": "user", "type": "module", "url": "/local/other-card.js"},
        {"id": "old", "type": "module", "url": "/hcl_lighting_static/hcl-curve-card.js?v=0.4.1"},
    ]
    urls = await _register_with_storage(hass, hass_storage, items)
    assert urls == sorted(["/local/other-card.js", CARD_URL])


# ---------------------------------------------------------------- B-23 / Ä-20
async def test_b23_card_hint_removed_with_entry(hass, no_frontend_registration):
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    notification_id = f"{DOMAIN}_card_{entry.entry_id}"
    assert notification_id in _notifications(hass)
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert notification_id not in _notifications(hass)


async def test_b14_yaml_mode_resources_do_not_break_setup(hass):
    from homeassistant.components.lovelace.resources import ResourceYAMLCollection

    collection = ResourceYAMLCollection([{"id": "1", "type": "module", "url": "/hcl_lighting_static/hcl-curve-card.js?v=0.4.1"}])
    hass.data["lovelace"] = MagicMock(resources=collection)
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    await async_register_lovelace_resource(hass)  # must not raise
