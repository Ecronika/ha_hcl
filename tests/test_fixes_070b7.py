"""0.7.0b7: performance items RM-T10, RM-T11 and RM-T13 of the roadmap (RM-F03: browser tests)."""
from __future__ import annotations

from types import SimpleNamespace

from homeassistant.core import Context, callback

from custom_components.hcl_lighting.const import CONF_CURVE_CONFIG, DOMAIN, OWN_CONTEXT_SECONDS
from custom_components.hcl_lighting.logic import light_controller as lc

from .helpers import CT_ATTRS, core, set_light, setup_entry
from .test_fixes_070b3 import SENSOR, SWITCH, Lights, _hcl_on

UNRECORDED = {"calculated_brightness", "calculated_color_temp", "target_entities", "manual_control"}
POINTS = [{"t": 0, "b": 20, "k": 2200}, {"t": 720, "b": 90, "k": 5500}, {"t": 1200, "b": 40, "k": 3000}]


# ---------------------------------------------------------------- RM-T10
async def test_rm_t10_switch_attributes_are_live_but_not_recorded(hass, no_frontend_registration):
    Lights(hass)
    for eid in ("light.c", "light.a", "light.b"):
        set_light(hass, eid, "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    await setup_entry(hass, ["light.c", "light.a", "light.b"])
    await _hcl_on(hass)
    state = hass.states.get(SWITCH)
    # still in the live state (automations, templates, card) ...
    assert UNRECORDED <= set(state.attributes)
    assert state.attributes["calculated_brightness"] is not None
    # ... but excluded from the history database
    assert UNRECORDED <= set(state.state_info["unrecorded_attributes"])


async def test_rm_t10_target_entities_are_sorted_and_stable(hass, no_frontend_registration):
    Lights(hass)
    lights = [f"light.l{n:02d}" for n in range(20, 0, -1)]
    for eid in lights:
        set_light(hass, eid, "off", **CT_ATTRS)
    await setup_entry(hass, lights)
    await _hcl_on(hass)
    assert hass.states.get(SWITCH).attributes["target_entities"] == sorted(lights)
    changes = []
    unsub = hass.bus.async_listen(
        "state_changed", callback(lambda e: changes.append(e) if e.data["entity_id"] == SWITCH else None)
    )
    # resolving the same lights again (e.g. a registry update) changes nothing
    from .helpers import switch_entity

    sw = switch_entity(hass)
    sw._resolved_targets = set(reversed(sorted(sw._resolved_targets)))
    sw.async_write_ha_state()
    await hass.async_block_till_done()
    unsub()
    assert changes == []


# ---------------------------------------------------------------- RM-T11
class _CountingDict(dict):
    """Counts full scans of the remembered contexts."""

    scans = 0

    def items(self):
        type(self).scans += 1
        return super().items()

    def __iter__(self):
        type(self).scans += 1
        return super().__iter__()

    def keys(self):
        type(self).scans += 1
        return super().keys()

    def values(self):
        type(self).scans += 1
        return super().values()


async def test_rm_t11_expired_contexts_are_removed_without_full_scans(hass, no_frontend_registration, monkeypatch):
    Lights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    controller = core(hass, entry)["controller"]
    clock = [1000.0]
    # only the controller's clock (the event loop keeps the real one)
    monkeypatch.setattr(lc, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    controller._own_contexts = _CountingDict(controller._own_contexts)
    _CountingDict.scans = 0

    parent = Context()
    old = [controller._new_context(parent) for _ in range(500)]
    clock[0] += OWN_CONTEXT_SECONDS / 2
    young = [controller._new_context() for _ in range(500)]
    assert all(controller.is_own_context(c) for c in old + young)
    # a state change caused by an HCL command (context = child of the command)
    assert controller.is_own_context(Context(parent_id=old[0].id))

    clock[0] += OWN_CONTEXT_SECONDS / 2 + 1  # the first 500 are expired
    newest = controller._new_context()
    assert not any(controller.is_own_context(c) for c in old)
    assert not controller.is_own_context(Context(parent_id=old[0].id))
    assert all(controller.is_own_context(c) for c in young + [newest])
    assert len(controller._own_contexts) == 501
    # 1001 commands, none of them searched all remembered contexts
    assert _CountingDict.scans == 0


# ---------------------------------------------------------------- RM-T13
def _hcl_entities(hass):
    from homeassistant.helpers import entity_registry as er

    return {e.entity_id for e in er.async_get(hass).entities.values() if e.platform == DOMAIN}


async def test_rm_t13_saving_the_curve_does_not_reload(hass, no_frontend_registration):
    lights = Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
    calc = core(hass, entry)["calculator"]
    ours = _hcl_entities(hass)
    unavailable = []
    unsub = hass.bus.async_listen(
        "state_changed",
        callback(lambda e: unavailable.append(e.data["entity_id"])
                 if e.data["entity_id"] in ours and e.data["new_state"] is not None
                 and e.data["new_state"].state == "unavailable" else None),
    )
    reloads = []
    real_reload = hass.config_entries.async_reload

    async def _reload(entry_id):
        reloads.append(entry_id)
        return await real_reload(entry_id)

    hass.config_entries.async_reload = _reload
    lights.calls.clear()
    context = Context()
    await hass.services.async_call(
        DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": "save", "points": POINTS},
        blocking=True, context=context,
    )
    await hass.async_block_till_done()
    unsub()
    assert reloads == []
    assert unavailable == []
    # saved, active and shown
    assert entry.options[CONF_CURVE_CONFIG] == {"points": POINTS, "version": 2}
    assert calc.active_curve == POINTS
    assert calc.preview_active is False
    attrs = hass.states.get(SENSOR).attributes
    assert attrs["control_points"] == POINTS
    assert attrs["preview_active"] is False
    # the lights follow the saved curve at once (command linked to the call)
    assert lights.for_light("light.a")
    assert lights.for_light("light.a")[-1].context.parent_id == context.id


async def test_rm_t13_saved_curve_survives_a_reload(hass, no_frontend_registration):
    Lights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await hass.services.async_call(
        DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": "save", "points": POINTS}, blocking=True
    )
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert core(hass, entry)["calculator"].active_curve == POINTS
    assert hass.states.get(SENSOR).attributes["control_points"] == POINTS


async def test_rm_t13_other_option_changes_still_reload(hass, no_frontend_registration):
    Lights(hass)
    set_light(hass, "light.a", "off", **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    first = core(hass, entry)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "transition": 7})
    await hass.async_block_till_done()
    assert core(hass, entry) is not first  # set up again
    # options and curve saved one after the other: the options still reload
    second = core(hass, entry)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "transition": 9})
    await hass.services.async_call(
        DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": "save", "points": POINTS}, blocking=True
    )
    await hass.async_block_till_done()
    assert core(hass, entry) is not second
    assert entry.options["transition"] == 9
    assert entry.options[CONF_CURVE_CONFIG]["points"] == POINTS
    assert core(hass, entry)["calculator"].active_curve == POINTS


async def test_rm_t13_save_ends_a_running_transition_protection(hass, no_frontend_registration):
    """Like the reload before (RM-B22): the saved curve reaches the light at once."""
    lights = Lights(hass)
    set_light(hass, "light.a", "on", brightness=3, color_temp_kelvin=2000, **CT_ATTRS)
    entry = await setup_entry(hass, ["light.a"])
    await _hcl_on(hass)
    await hass.services.async_call(DOMAIN, "apply", {"entity_id": SWITCH, "transition": 120}, blocking=True)
    om = core(hass, entry)["override_manager"]
    assert om.is_reengaging("light.a")
    lights.calls.clear()
    await hass.services.async_call(
        DOMAIN, "update_curve", {"entity_id": SENSOR, "mode": "save", "points": POINTS}, blocking=True
    )
    await hass.async_block_till_done()
    assert lights.for_light("light.a")
    assert not om.is_reengaging("light.a")
