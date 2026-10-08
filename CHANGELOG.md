# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.1] - 2026-10-08
Bugfix release: RM-B41, RM-B42 and RM-D06 of the roadmap. The minimum Home Assistant version stays 2024.7.

### Fixed
- **Report "on" with brightness 0 counted as manual control** (RM-B41): a light that reports "on" with brightness 0 for a moment (e.g. KNX, when the brightness status arrives just before or after the switching status) was paused after switching on, until it was switched off or the return time had passed (since 0.7.0b13); when switching off, manual control started and ended in the same second (logbook entries and `hcl_lighting_manual_control` events). Such a report carries no brightness and no longer counts as a change of brightness.
- **Compatibility mode: colour temperature could fade after all** (RM-B42): the colour temperature commands (and the command without transition sent after a failure) had no transition, so a default transition applied (`light_profiles.csv` of Home Assistant, the default transition of Zigbee2MQTT or ZHA). The colour faded and the brightness command came during the fade, which bulbs like IKEA TRÅDFRI can ignore. They are now sent with transition 0.

### Changed
- **README: notes on lights** (RM-D06): which option helps with IKEA TRÅDFRI, lights that keep glowing after Sleep, lights that switch themselves back on and the previous colour visible when switching on; when the compatibility mode applies.

## [0.7.0] - 2026-10-04
Summary of all changes since 0.6.1; the details are in the entries of the pre-releases 0.7.0b1 to 0.7.0b14 below (RM-… numbers refer to the roadmap). The minimum Home Assistant version stays 2024.7.

### Upgrade notes – behaviour that changes from 0.6.1
- **Focus, Relax and Cleaning stay within the minimum and maximum brightness** (RM-R01). With the default limits (10–100 %) nothing changes. Sleep and Night light are not limited.
- **Sleep (and the new Night light) end at the next wake time** and return to Auto (RM-R03). `hcl_lighting.set_scenario` with `duration: 0` keeps them until changed.
- **One light command per light** instead of one command for several lights (RM-B13): more, smaller commands, so a failing light no longer hides the success of the others.
- **Users with restricted permissions** need control of the HCL entities and, for actions that send the HCL values at once, of every light of the instance (RM-B07, RM-B31, RM-B34). Admins, automations and scripts are not affected.
- **At least one light target** is required in the setup and the options (RM-B35).
- **The attributes of *HCL active*** (`calculated_*`, `target_entities`, `manual_control`) are no longer stored in the history (RM-T10); the setpoint sensors and the logbook keep the history.
- **Diagnostics** contain pseudonyms instead of names and IDs (RM-B32).
- **The card hint after setup** is a one-time notification instead of a repair issue; the old repair issue is removed.
- **Removed**: the simulator `docs/hcl_simulator.html` (RM-R04) and the demo `docs/hcl_dashboard.html`. After the update reload the dashboard page without cache (Ctrl+F5) so the new card is loaded.

### Added
- **Setpoint sensors** "Target brightness" and "Target colour temperature": the values HCL sends now (scenario and limits included), e.g. to switch a light on with the HCL values or to feed a KNX/DALI gateway.
- **Scenario "Night light"** (default 3 % / 2200 K, configurable) and the option **"Transition when the scenario changes"**.
- **Actions** `hcl_lighting.apply`, `hcl_lighting.set_manual_control`, `hcl_lighting.set_scenario` (optional duration) and `hcl_lighting.get_curve` (response data), with translated error messages (RM-H06).
- **Event `hcl_lighting_manual_control`** and **logbook entries** for manual control and scenario changes.
- **Diagnostics download** (pseudonymized, RM-B32) and a **repair issue** when two instances adapt the same light for the same attribute.
- **Dashboard card**: visual card editor, compact view (`view: compact`), size hints for Sections dashboards (height "auto" by default, RM-B26), Night light chip, presets "Default with quiet night" and "Default without midday dip", "now" values from the setpoint sensors, the end of a timed scenario (RM-F04), the instance name as title (RM-F05), screen-reader sliders for the curve points (RM-B28) and larger touch areas.

### Changed
- **Manual control**: a light that is unreachable for up to 5 minutes (restart, radio dropout) keeps its manual control (RM-B24). A change on the device itself within 5 seconds after an HCL command (e.g. dimming at a wall dimmer right after switching on) is recognised by its values (RM-B33).
- **Updates are never dropped**: requests during a running update (scenario change, curve preview, release of manual control, `apply`) wait and are combined (RM-B01, RM-B02, RM-B18, RM-B20).
- **Lights that do not answer** no longer hold up HCL: an update waits at most 10 s; a light gets no second command while one is still running – also across a reload and when it is switched on (RM-B23, RM-B30, RM-T14, RM-T17). The setup no longer waits for light commands (RM-B37).
- **Failed commands** are not treated as successful (tracking, ignore window and transition protection are restored, RM-B04, RM-B14, RM-B15); `apply` reports failed lights (RM-B16). A light that keeps failing is logged once, not in every update (RM-B39).
- **Colour temperature** is limited to the range of lights with native colour temperature (RM-B03).
- **Targets** are resolved by Home Assistant's own target resolution of the installed version (hidden and configuration lights reached indirectly are skipped, child devices included where supported; RM-B06, RM-B17, RM-B19); member changes of light groups are picked up.
- **Long transitions** of `apply`, scenario changes, the turn-on transition and the smooth return are no longer cut short by the update cycles; switching HCL on or a reload takes the lights back at once (RM-B21, RM-B22).
- **Saving the curve** takes effect without reloading the integration (RM-T13).
- **Dashboard card**: unsaved drafts are kept when the curve changes elsewhere, much less work per Home Assistant state change (RM-F03), Chart.js loaded by the card with a fixed version, time and number format of the Home Assistant profile, usable from 240 px width.
- **Capabilities** of a light are evaluated again when it reports other ones (RM-B36).
- **Card resource** is updated in place on version changes (one entry with `?v=<version>`), and registered again once Home Assistant has started if Lovelace was not ready.

### Fixed
- Many smaller fixes of the betas, among them: midnight (24:00) in curves, the card in Masonry dashboards, dragging and screen readers in the card, permissions of the actions, the disabled main switch (RM-B38), unknown keys stored by `update_curve` (RM-B40) and an emptied light target that fell back to the first setup (RM-B35). See the entries below.

### Internal
- Ruff in CI (RM-B12), CI tests also on Home Assistant 2025.7 and 2025.8 (RM-T09), cleanups (RM-B10, RM-T15, RM-T16, RM-T18).

### Not included
- RGBWW lights keep getting the colour temperature through the XY simulation (Home Assistant does not expose the white-channel range of such lights).

## [0.7.0b14] - 2026-10-04
Fourteenth pre-release (beta) of 0.7.0: RM-T17, RM-B34 and RM-D04 of the roadmap (external analysis of 0.7.0b13) and RM-B35 to RM-B40, RM-T18 and RM-D05 (code review of 0.7.0b13). The minimum Home Assistant version stays 2024.7.

### Fixed
- **Light command at switching on held Home Assistant and allowed a second command** (RM-T17): the command HCL sends when a light is switched on (Fast-HCL) was awaited in HCL's state listener without a time limit (a task Home Assistant waits for at start and stop), and the next update sent the light a second command. It now runs in the background like all other light commands; a light with a command still running gets no further command (also at switching on). A late failure restores the tracking values and ends the protection of the turn-on transition.
- **Permission check used the lights of the last run** (RM-B34): with HCL off, the list of lights is not kept current. A user with restricted permissions could switch HCL on although a light had joined the area, device, label or group meanwhile that the user may not control; the following updates then controlled it. The check now resolves the lights of the instance at that moment.
- **Empty light target fell back to the lights of the first setup** (RM-B35): a target emptied in the options was replaced by the target of the first setup. Setup and options now require at least one target; a stored empty target means no lights.
- **Lights that report their capabilities late were skipped** (RM-B36): the capability of a light (colour temperature, colour, brightness, on/off) was kept from the first time it was on, e.g. "on/off only" while the integration had not reported more yet, until the next reload. It is now evaluated again whenever the light reports other capabilities.
- **Setup waited for the light commands** (RM-B37): an instance that was on before a restart or reload sent its values during the setup and waited for them (up to 10 s for a light that does not answer). The first update now runs in the background; the lights still get the values at once.
- **Disabled main switch** (RM-B38): with *HCL active* disabled, `apply` ended with an internal error and `set_manual_control` reported success without effect. These actions and `set_scenario` now report that the main switch is disabled.
- **A failing light filled the log** (RM-B39): a light whose commands keep failing (e.g. reported on but not reachable) logged an error with traceback in every update (about 130 per hour). It is now logged once as a warning when it starts failing (repeats at debug level) and once as info when it accepts commands again. Actions still report failed lights to the caller.
- **`update_curve` stored unknown keys** (RM-B40): keys besides `t`, `b` and `k` of a point were stored in the entry options; they are dropped now.

### Changed
- **Diagnostics note** (RM-D04): the README no longer calls the download "safe to attach to an issue": names and IDs are pseudonymized, but the curve and the wake, midday and sleep times remain for troubleshooting.
- **Action description** (RM-D05): `mode` of `update_curve` is optional in the action editor, as in the action itself (default `preview`); its texts come from the translations only.

### Internal
- Misleading and outdated comments removed; one constant for the 3-minute smooth return instead of steps and interval (RM-T18). Unused capability cache version removed (RM-B36).

## [0.7.0b13] - 2026-10-04
Thirteenth pre-release (beta) of 0.7.0: fixes RM-B33 of the roadmap (field test of 0.7.0b12 with wall dimmers). The minimum Home Assistant version stays 2024.7.

### Fixed
- **Dimming at the wall right after switching on was overwritten** (RM-B33): Home Assistant gives the state changes of a light the context of the last command for 5 seconds, also a change made on the device itself (e.g. a KNX wall dimmer or a manufacturer's remote). HCL took such a change within 5 seconds after its own command for its own report and did not pause the light, so the next update set the HCL value again. This hit the usual use of wall dimmers: switching on (HCL sends its values at once) and dimming right away. Every new HCL command opened the next 5-second gap. A state report with HCL's context now counts as HCL's own only if it fits the command: at the HCL value or moving towards it. A change beyond the range between the light's value when the command was sent and the HCL value is manual control at once. A change back towards the light's earlier value can also be the device's own report during the transition (some devices report the target first and then their intermediate values); it is decided when the transition of the command has ended: if the light has not reached the HCL value by then, it is manually controlled, and HCL leaves it alone until then.

## [0.7.0b12] - 2026-10-04
Twelfth pre-release (beta) of 0.7.0: fixes RM-B30 to RM-B32 and RM-T14 of the roadmap (external code analysis of 0.7.0b11) and quality items RM-B12, RM-T15, RM-T16 and RM-H06. The minimum Home Assistant version stays 2024.7.

### Fixed
- **Light commands across a reload** (RM-B30): a command that answered only after the 10-second limit (RM-B23) could still be running when the instance was reloaded (options or name saved). The new instance did not know it: it sent the light a second command, took a late state report of the old command for manual control, and a late failure of the old command rolled back the tracking values the new instance had set since. Running commands and their contexts now survive a reload: the light gets no second command until the first one has finished, its state reports stay HCL's own, and a late failure rolls back only if no newer command has set the light since (also within one instance, e.g. a light switched on again meanwhile).
- **Smooth return to HCL could hold up Home Assistant** (RM-T14): the commands of the smooth return after manual control were normal tasks; a light that did not answer kept Home Assistant waiting for it (e.g. at shutdown). They are now background tasks like all other commands.
- **Permissions of the lights an action drives** (RM-B31): an action of a user with restricted permissions was checked only for the HCL entities (and the lights given in `lights`), but drove all lights of the instance. An action that sends the HCL values to the lights at once now also needs control of every light of the instance, as if the user switched them directly: `apply` without `lights`, `set_manual_control` with `manual_control: false` (it updates the instance at once), `set_scenario`, `update_curve`, and choosing a scenario, switching *HCL active* on or an adapt switch in the dashboard. The light commands of an action run as the user who caused it (logbook, traces, permissions); periodic updates and the automatic end of a scenario run without a user. Admins, automations and scripts are not affected.
- **Diagnostics contained personal data** (RM-B32): the download showed the instance name, entity and area IDs (room names) and the times of manual control. The name is removed, entity, device, area, floor and label IDs are replaced by pseudonyms (`light.redacted_1`, `area_1`, the same in every part of the download), manual control is given as its age in minutes. Curve and anchor times stay.

### Changed
- **Translatable error messages** (RM-H06): the errors of the actions (e.g. "Not controlled by this HCL instance", "Light update failed for …") have translations (English, German). `update_curve` reports a wrong entity as a validation error like the other actions (before: a general error) and, like them, accepts any entity of an HCL instance.

### Internal
- Ruff runs in CI (RM-B12, rules in `ruff.toml`: errors, not style); unused imports, a duplicate import and unused variables removed. Unused constants removed (RM-T15). Imports moved to module level (RM-T16; the version switch of the target resolution is decided once at import).

## [0.7.0b11] - 2026-10-03
Eleventh pre-release (beta) of 0.7.0: fixes RM-B25 to RM-B29 and adds RM-F05 of the roadmap (field test of 0.7.0b10 on a phone, with TalkBack). The minimum Home Assistant version stays 2024.7.

### Fixed
- **Points jumped away from the finger while dragging** (RM-B27): hints above the charts ("Brightness changes too steeply …", the draft line) appeared and disappeared while a point was dragged and moved the charts, but the position was calculated against the place of the charts when the point was grabbed. At a warning threshold the charts jumped up and down and the point could hardly be placed. While a point is dragged nothing above the charts changes any more (the hints follow when it is released), and the position is measured on every move. On touch screens the points can be grabbed in a larger area (44 px; the point looks the same).
- **Card covered the cards below in a Sections dashboard with a fixed height** (RM-B26): with a fixed number of rows the card was taller than its cell and drew over the next section (e.g. with the editor open on a phone). The card now fills a fixed height and scrolls inside; with the height on "auto" (now also the default of the card) it is as tall as its content.
- **Curve points could not be moved with a screen reader** (RM-B28): the points were custom sliders; with TalkBack a point could be selected but not adjusted, the focus jumped to the whole chart. Every point now has a native slider (value, time and value read out), which screen readers adjust with their own gestures; the points are no longer rebuilt while they are used, so the focus stays. Keyboard and dragging work as before.
- **Screen readers read the separators** (RM-B29): the status and draft lines were read with "dot" between the values; screen readers now get pauses instead (the visible text is unchanged).
- **End of a scenario a full day ahead looked like now** (RM-F04 follow-up, RM-B25): `hcl_lighting.set_scenario` with `duration: 1440` showed e.g. "until 20:27" at 20:27; an end a full day ahead now shows the date.

### Added
- **Card title from the instance** (RM-F05): the card shows the name of its instance instead of "HCL Configurator" (rename the entry under Settings → Devices & services, e.g. "Kitchen"); `title:` in the card configuration (also in the visual editor) overrides it. The curve sensor has the new attribute `instance` (not stored in the history). The instance picker of the visual editor shows these names too.

## [0.7.0b10] - 2026-10-03
Tenth pre-release (beta) of 0.7.0: fixes RM-B24 and RM-D03 and adds RM-F04 of the roadmap (field test of 0.7.0b9). The minimum Home Assistant version stays 2024.7.

### Fixed
- **Manual control ended when a light was briefly unavailable** (RM-B24): a light that reported `unavailable` or `unknown` was treated like a light that was switched off, so (with "Switching a light off ends manual control", the default) its manual control ended and HCL overwrote the user's values as soon as the light reported `on` again. This happened after every Home Assistant restart with lights that report `unavailable`/`unknown` for a moment while starting (e.g. Zigbee2MQTT/MQTT lights), so "Keep manual control across restarts" had no effect for them, and after radio dropouts or bridge/broker restarts. A light that is unreachable for up to 5 minutes now keeps its manual control. A longer gap still counts like switching off (e.g. a lamp without power at the wall switch comes back with its power-on values), if switching off ends manual control.
- **Misleading debug message** (RM-D03): switching a light off shortly after an HCL command logged "Override detected inside Ignore Window!" although no manual control was set. Switching off now skips this check (it ends manual control as before, also within the ignore window), and the message for a real change reads "Change away from the HCL value inside the ignore window for … checking for manual control".

### Added
- **Dashboard card shows when a scenario ends** (RM-F04): the line below the charts shows the end of a timed scenario, e.g. "Now 23:10 · Night light · until 07:00 · 3 % · 2200 K" (with the date if the end is more than a day ahead). No end (`duration: 0`) shows nothing. The end comes from the attribute `until` of the scenario select.

## [0.7.0b9] - 2026-10-01
Ninth pre-release (beta) of 0.7.0: three options added in the 0.7.0 betas become fixed behaviour, and the simulator is removed (RM-R01 to RM-R04 of the roadmap; keep the integration lean). The minimum Home Assistant version stays 2024.7. Compared with 0.6.1, two behaviours change (marked below); compared with the earlier 0.7.0 betas, the three options are gone.

### Changed
- **Focus, Relax and Cleaning always stay within the minimum and maximum brightness** (RM-R01; option "Limit scenarios to minimum/maximum" removed). Sleep and Night light are not limited. With the default limits (10–100 %) nothing changes. *Change from 0.6.1*: a scenario value outside your limits is now limited to them.
- **Minimum and maximum brightness only clip** (RM-R02; option "Scale brightness to minimum/maximum" removed, as in 0.6.1): curve values outside the limits are set to the limit; card, target value sensors and lights show the same values. The curve sensor no longer has the attribute `brightness_scaling`.
- **Sleep and Night light always end at the next wake time** (RM-R03; option "Scenarios end at wake time" removed): they return to Auto at the wake time. `hcl_lighting.set_scenario` with `duration: 0` keeps them until changed, a duration in minutes ends them earlier or later. *Change from 0.6.1*: Sleep no longer stays until it is changed. A Sleep or Night light restored from an earlier version without an end time stays until it is changed once.
- The removed options are deleted from the stored options the next time the options are saved; until then they have no effect.

### Removed
- **Simulator** `docs/hcl_simulator.html` (RM-R04): a third copy of the curve calculation without a test against the integration; the dashboard card has a preview. The GitHub Pages page of the simulator is no longer available.

## [0.7.0b8] - 2026-09-30
Eighth pre-release (beta) of 0.7.0: fixes RM-B23 of the roadmap (external analysis of 0.7.0b6). The minimum Home Assistant version stays 2024.7.

### Fixed
- **A light that does not answer held up HCL** (RM-B23): an update waited for all light commands without a time limit (Home Assistant sets none for these commands). A light that counts as available but answers late or not at all (Zigbee device about to drop out, overloaded bridge, integrations with their own retries) delayed the other lights, scenario changes, curve preview/save, the return from manual control and `hcl_lighting.apply`, and periodic updates were skipped. An update now waits at most 10 seconds and then goes on. The command to the slow light is not cancelled: if it succeeds later, nothing changes; if it fails later, HCL treats it like any failed command. Until it has finished, that light gets no further command, so commands do not pile up. `hcl_lighting.apply` ends with an error naming lights that did not answer in time (the other lights are updated).

## [0.7.0b7] - 2026-09-29
Seventh pre-release (beta) of 0.7.0: performance items RM-F03, RM-T10, RM-T11 and RM-T13 of the roadmap (performance review of 0.7.0b6). The minimum Home Assistant version stays 2024.7.

### Changed
- **Dashboard card: less work on every Home Assistant state change** (RM-F03): Home Assistant hands the card a new state after every change of any entity, often several times a second. The card processed each of them completely (number and time formats, curve comparison, status line). It now stops at once unless something it shows has changed (curve sensor, scenario, target value sensors, language, number/time format, theme, time zone). Measured in headless Chromium with 2000 other entities: about 40–65 µs per change before, about 2 µs now, and no DOM changes. The "now" line still moves every minute.
- **History database: attributes of the *HCL active* switch are no longer recorded** (RM-T10): `calculated_brightness`, `calculated_color_temp`, `target_entities` and `manual_control` are live values (automations, templates and the card see them as before). Recording them stored a new attribute row with the complete light list with every new value, many times a day. The history of the values is kept by the target value sensors, manual control by its event and logbook entries. `target_entities` is now sorted, so resolving the same lights again changes nothing.
- **Own commands recognised with less effort** (RM-T11): HCL remembers the contexts of its own light commands for 5 minutes. Expired ones were searched among all remembered contexts before every command (effort grew with the square of the commands per cycle); they are now removed oldest first.
- **Saving the curve no longer reloads the integration** (RM-T13): the saved points were already active, but saving reloaded the whole instance, so all HCL entities (and the card) were unavailable for a moment and every listener was set up again. The saved curve now takes effect in place, like revert: the lights get it at once (a running long transition ends, as after the reload before) and the action is linked to the command. Any other change of the configuration (options, also when saved right before the curve) reloads as before.

## [0.7.0b6] - 2026-09-27
Sixth pre-release (beta) of 0.7.0: fixes RM-B21 and RM-B22 of the roadmap. The minimum Home Assistant version stays 2024.7.

### Fixed
- **Turn-on transition cut short** (RM-B21): the transition of the values sent right after a light is switched on (option "Transition when switched on", up to 30 s) was not protected against the normal update cycles. A cycle during the transition (e.g. update interval 10 s, turn-on transition 30 s) sent the values again with the update transition and replaced the fade. The light is now left alone until the turn-on transition has ended, as for long `apply` and scenario transitions; if the command fails, no protection is set.
- **HCL off and on (or reload) left lights waiting** (RM-B22): a light still protected by an earlier long transition (`apply`, scenario, smooth return) was skipped by the update right after switching *HCL active* on again, and after a reload of the integration (e.g. options or curve saved), until the old protection ran out (up to minutes). Switching HCL on and setting it up again now end these protections, so HCL takes its lights back at once. Switching HCL on while it is already on changes nothing.

## [0.7.0b5] - 2026-09-27
Fifth pre-release (beta) of 0.7.0: fixes RM-B19 and RM-B20 of the roadmap (review of 0.7.0b4). The minimum Home Assistant version stays 2024.7.

### Fixed
- **No lights controlled on Home Assistant 2025.1 to 2025.7** (RM-B19, regression in 0.7.0b4): on these versions the target resolution built its internal service call with the argument order of Home Assistant 2024.x. Home Assistant 2025.1 added a new first parameter, so the target ended up in the wrong field and no light was found - HCL did not control any light. The call is now built with named parameters and works with both signatures.
- **Scenario change blocked by an older long transition** (RM-B20): a scenario or curve change ended running transition protections immediately, even when an older `apply` or scenario update with a long transition was still waiting to be sent. That older update then set its protection afterwards, and the new scenario was not sent until the protection ran out (up to the length of the transition) and then only with the normal transition. The protection now ends when the new update actually runs, after the older one.

### Changed
- README: the target resolution follows the rules of the installed Home Assistant version; details (e.g. configuration lights that carry a selected label) are described as version dependent (RM-D01).
- CI: the Home Assistant tests also run on 2025.7.0 and 2025.8.0, the two releases at the boundary of Home Assistant's target helpers (RM-T09).

## [0.7.0b4] - 2026-09-27
Fourth pre-release (beta) of 0.7.0: fixes RM-B13 to RM-B18 of the roadmap (review of 0.7.0b3, there numbered RM-B12 to RM-B17). The minimum Home Assistant version stays 2024.7.

### Fixed
- **Partly failed commands** (RM-B13): HCL sent one command for several lights. Home Assistant runs such a command for all lights and reports the first error afterwards, so after a failure HCL treated all of them as not updated, although some had received the values (their tracking values were then outdated). Each light now gets its own command.
- **Ignore window after a failed command** (RM-B14): after a failed command only the tracking values were restored; the window in which HCL ignores the light's reports (up to the length of the transition) stayed active, so a manual change right afterwards could be missed. Values and window are now restored together.
- **Failed command after switching a light on** (RM-B15): when the command HCL sends right after a light is switched on failed, the tracking values and the ignore window stayed as if it had succeeded. They are now restored as for the other commands.
- **`hcl_lighting.apply` hid failed lights** (RM-B16): the action ended successfully even if light commands failed. It now ends with an error naming the lights that failed (the other lights are updated), like Home Assistant's own light actions.
- **Devices with child devices** (RM-B17): targets are now resolved by Home Assistant's own target resolution of the installed version (the one light actions use) instead of HCL's own copy. On versions with child devices (Home Assistant 2026) a device includes the lights of its child devices, and the details (e.g. labelled configuration lights) follow the installed version exactly.
- **`apply` queued behind a running update** (RM-B18): an `apply` waiting for a running update calculated its values only when it could send, so it could already send the values of a scenario chosen after it, with the `apply` transition instead of the scenario transition. `apply` now sends the values of the time it was called; the later scenario change follows with its own transition.

### Changed
- One light command per light instead of one command per group of lights (more, smaller commands; needed to know which light failed).

## [0.7.0b3] - 2026-09-26
Third pre-release (beta) of 0.7.0: fixes RM-B01 to RM-B11 of the roadmap (phase 1). The minimum Home Assistant version stays 2024.7.

### Fixed
- **Scenario change during an update** (RM-B01): an update requested while a previous one was still sending (scenario change, curve preview/revert, release of manual control, HCL switched on, targets changed) was dropped, so e.g. a new scenario only arrived with the next timer tick. Requests now wait for the running update and are then sent; several requests are combined into one update with the newest values. Only timer ticks are skipped while an update is running.
- **`hcl_lighting.apply` during an update** (RM-B02): `apply` could send in parallel with a running update cycle. It now waits for the cycle, so the newer request is sent last.
- **Colour temperature outside a light's range** (RM-B03): lights with native colour temperature received the unlimited target (e.g. 6500 K for a 2200–4000 K light). They now get the value they can reach (4000 K), also when switched on and with the compatibility mode (smart transition); lights with different ranges get separate commands.
- **Failed light commands** (RM-B04): a light whose command failed was treated as updated: it got the transition protection of `apply`/scenario changes or of the smooth return after manual control, and its tracking values pointed to values it never received. Only successful commands count now; a failed light keeps its previous tracking values and a failed smooth return hands the light back to the normal updates.
- **Compatibility mode errors** (RM-B05): when the two-step command and the fallback without transition both failed, the error was swallowed and the light counted as updated. The final error is now logged and reported (the first failure is logged as a warning).
- **Target resolution** (RM-B06): areas, devices, floors and labels are resolved like Home Assistant resolves action targets: hidden lights and configuration/diagnostic lights (e.g. status LEDs of wall switches) reached through a device, area, floor or label are skipped, and a light with its own area is no longer included through the area of its device. Lights given directly are always used. The same rules apply when HCL recognises manual control from light actions.
- **Permissions of the actions** (RM-B07): `apply`, `set_manual_control`, `set_scenario` and `update_curve` could be used by any user who could call actions. A user with restricted permissions now needs control of the given HCL entity, of the *HCL active* switch (for `set_scenario` also of the scenario select) and of the lights given in `lights`; `get_curve` needs read access. Automations, scripts and admins are not affected.
- **Origin of light commands** (RM-B08): the light commands HCL sends for an action (`apply`, `set_scenario`, `set_manual_control`, `update_curve`, scenario select, *HCL active* and adapt switches) carry the action's context as parent, so logbook and traces show where they came from.
- **Group listener while HCL is off** (RM-B09): the watch of light group members stayed active after switching HCL off; it is now released and set up again when HCL is switched on.
- **Options dialog** (RM-B11): an error while preparing the first options page was logged and hidden behind a fallback form meant for old Home Assistant versions. The fallback is removed (not needed since 2024.7), errors are no longer hidden.

### Changed
- Removed unused code in the curve calculation (RM-B10); no functional change.
- Tests: a test of the manual-control event could fail at random (the test listened with a plain function, which Home Assistant runs in a worker thread, so the order of two events was not fixed).

## [0.7.0b2] - 2026-09-26
Second pre-release (beta) of 0.7.0.

### Fixed
- **Dashboard card, unsaved changes after a reload**: when the curve sensor was missing or unavailable for a moment (e.g. while the integration reloads), an unsaved draft was replaced by the saved curve when the sensor returned, and undo was cleared. The draft and undo are now kept; a different curve on return is offered with "Load that curve" as for other updates.
- **Dashboard card, unavailable sensor**: an unavailable or unknown curve sensor that still carried its old attributes was shown as current data with the editor. The card now shows the sensor as unavailable.
- **Dashboard card, "now" values**: when the setpoint sensors had no current value (unknown/unavailable), the card showed values of the Auto curve even in other scenarios. It now shows "target values not available". Without setpoint sensors (disabled, or an older integration) the card computes the values from the active scenario or, in Auto, from the curve.
- **Dashboard card, removed cards**: a card removed from the page (e.g. when switching dashboard views) kept its two charts registered in Chart.js. A card that stays removed for a second now releases them and rebuilds them when it is shown again; the draft is kept. Cards moved by the dashboard keep their charts.
- **`hcl_lighting.apply` with a long transition**: the next update cycle sent the values again with the update transition (20 s) and cut a longer transition short. Lights are now left alone until the requested transition has ended, as for a long scenario transition; a scenario change, a new `apply` or switching the light off ends this.

## [0.7.0b1] - 2026-09-25
Pre-release (beta) of 0.7.0.

### Added
- **Setpoint sensors**: two new sensors per instance, "Target brightness" (%) and "Target colour temperature" (K). They show the values HCL would send now, including scenario, minimum/maximum and brightness scaling, independent of the adapt switches and of manual control. Guest mode → `unknown`, Sleep → 0 %. No `state_class` (no long-term statistics). Use them e.g. to switch a light on with the HCL values or to pass the values to a KNX/DALI gateway.
- **Scenario "Night light"**: dim, warm light for the night (default 3 % / 2200 K, configurable). Like all scenarios it never switches lights on or off; lights that are on get the night-light values. Colour lights get the colour temperature through the XY simulation.
- **Option "Scenarios end at wake time"** (default off): Sleep and Night light return to Auto at the next wake time. A duration given with `set_scenario` takes precedence (0 = until changed).
- **Option "Scale brightness to minimum/maximum"** (default off = limit as in 0.4–0.6): the curve range 10–100 % is mapped to minimum–maximum instead of being cut off. Card, simulator and sensors show the scaled curve.
- **Option "Limit scenarios to minimum/maximum"** (default off): Focus, Relax and Cleaning also respect minimum and maximum brightness. Sleep, Night light and Guest are not affected.
- **Option "Transition on scenario change"** (default: same as the update transition, 20 s): used when the scenario is changed and when a timed scenario ends. Lights are protected from the next update cycle until a longer transition has finished.
- **Services**:
  - `hcl_lighting.apply`: send the current HCL values now to all or selected lights of an instance, with optional transition; never switches a light on; lights under manual control are skipped unless `release_manual_control` is set. Not available in Guest mode (error message).
  - `hcl_lighting.set_manual_control`: pause lights (manual control) or hand them back to HCL.
  - `hcl_lighting.set_scenario`: set the scenario, optionally with a duration in minutes (0 = no duration).
  - `hcl_lighting.get_curve`: returns the curve points, the saved points, whether a preview is active and the anchor times as response data (e.g. to copy a curve to another instance with `update_curve`).
- **Event `hcl_lighting_manual_control`** (`entity_id`, `manual_control`, `instance`, `config_entry_id`) when a light starts or stops being under manual control, and **logbook entries** for it and for scenario changes.
- **Diagnostics**: download from the integration page (options, targets and their capabilities, manual control, curve).
- **Repair issue** when the same light is adapted by more than one HCL instance for the same attribute (brightness or colour temperature). It disappears when the conflict is resolved. Splitting one light between two instances via the adapt switches is not reported.
- **Dashboard card**: visual card editor (instance and view), `view: compact` (status and scenario chips, editor can be expanded), size hints for Sections dashboards (`getGridOptions`), a "Night light" chip, presets "Default with quiet night" and "Default without midday dip", and the "now" values from the new setpoint sensors.

### Changed
- **Card hint after setup**: the hint to add the dashboard card is a one-time notification instead of a repair issue. The existing "setup curve card" repair issue is removed on update; installations that had it get no new notification.
- **Dashboard card**:
  - The curve can be edited in every scenario; a hint says that the curve only applies in Auto.
  - Times follow the time format of the Home Assistant profile (12/24 h), numbers its number format.
  - In Sections dashboards the card now reports its size; the full view still uses the full width.
  - Scenario chips show the confirmed state of the scenario select (with a pending state while switching) and are announced as toggle buttons.
  - Chart.js is loaded with a fixed version by the card itself; a different Chart.js version loaded by another card is no longer used.
- **Group members**: when the members of a targeted light group change (its `entity_id` attribute), the lights are resolved again, also without a registry event.
- **Card resource**: the dashboard resource is updated in place on version changes (one entry with `?v=<version>`); if Lovelace is not ready at startup, registration is retried once Home Assistant has started.
- **Simulator** (`docs/hcl_simulator.html`): Chart.js pinned to 4.5.1, option for brightness scaling.

### Fixed
- **Midnight in curves**: a point at 24:00 is treated as 00:00. Curves containing both 00:00 and 24:00 keep the 00:00 point (warning in the log); `update_curve` rejects contradictory values for 00:00 and 24:00.
- **Dashboard card, unsaved changes**: updates from Home Assistant (another browser, a second card, a service call) no longer overwrite an unsaved draft; the card shows a hint with "Load that curve" instead. "Revert" only shows the saved curve after Home Assistant has confirmed it.
- **Dashboard card, input**: empty or invalid numbers no longer set a point to 0; the point stays unchanged and the field shows a hint.
- **Dashboard card, dragging**: a drag interrupted by the browser (pointer cancel, lost capture, removed card) ends cleanly instead of leaving the point attached to the pointer.
- **Dashboard card, states**: missing, unavailable or invalid sensor data shows a message instead of an empty or broken chart.
- **Dashboard card, night checks**: times in warnings are shown modulo 24 h (00:15 instead of 24:15); warnings spanning midnight are merged.
- **Dashboard card, layout**: usable from 240 px width, time axis per chart, text contrast in light and dark theme.
- **Dashboard card in Masonry dashboards** could stay empty when the dashboard moved the card while it was loading.

### Removed
- `docs/hcl_dashboard.html` (outdated demo, not a Home Assistant card).

### Not included
- RGBWW lights keep getting the colour temperature through the XY simulation. Sending `color_temp_kelvin` and letting Home Assistant convert it was checked and dropped: Home Assistant does not expose the white-channel range of such lights and produces invalid (negative) channel values outside it.

## [0.6.1] - 2026-09-25
### Fixed
- **Smooth return after manual control**: when the manual-control time has expired, the light returns to HCL with the documented 3-minute transition. Before, the next normal update (same cycle and the following ones) overwrote it with the 20-s update transition. A scenario change, a curve preview/save or switching the light off ends the smooth return early.
- **Own state reports counted as manual control**: a state report of a light caused by HCL's own command (e.g. a late or intermediate value during a transition) could pause the light. State changes that carry HCL's context are now ignored; changes by other commands and by the device (wall switch, manufacturer app) are detected as before.
- **Guest mode after a reload**: reloading the integration (e.g. after saving the options) sent one update with Auto values before the scenario was restored, even in Guest mode. The scenario is now restored before the first update (an ended timed scenario is restored as Auto).
- **Colour mode depended on earlier queries**: whether a light is driven with its native colour temperature or with the XY simulation was cached in 500-K steps, so e.g. 2600 K could stay native on a 2700–6500 K bulb after a query at 2800 K. The range is now checked for every target value.
- **RGBW and RGBWW lights** without a colour-temperature mode were treated as dimmers (brightness only). They now get the colour temperature through the XY simulation like RGB/XY lights.
- **Duplicate times**: `hcl_lighting.update_curve` rejects points with the same time instead of silently dropping one of them.
- **Dashboard card, saving**: Save waits for Home Assistant to confirm; if saving (or preview/revert) fails, the error is shown and the changes stay marked as unsaved. While the lights follow an unsaved preview, the card says so and Save stays highlighted (new sensor attribute `preview_active`).
- **Dashboard card, current time**: the "now" marker and values use the Home Assistant time zone instead of the browser's.
- **Dashboard card, night checks**: the "night too bright/cold" hints use the configured sleep and wake time instead of a fixed 22:00–06:00 window (new sensor attributes `sleep_time` and `wake_time`).
- **Dashboard card, preset "Default"**: now identical to the default curve of the integration (07:00 / 30 % … 22:00 / 10 %); before it started at 07:15 / 14 % and ended at 23:00 / 5 %.
- **Simulator** (`docs/hcl_simulator.html`): uses the current calculation (PCHIP, min/max as limits, 2000–7000 K, midday correction) instead of the logic of v0.3.0, and no longer claims to show custom curves.
- A test of the smooth return depended on the time of day and failed in CI between 10:00 and 12:00 (test time zone); the integration was not affected.

### Documentation
- README: hint to reload the browser page (Ctrl+F5) after an update so the new card is loaded.
- CHANGELOG 0.4.0: added the missing note that minimum/maximum brightness clip the curve since 0.4.0 instead of scaling it.

## [0.6.0] - 2026-09-23
### Added
- **Adapt brightness / Adapt colour temperature**: two switches per instance. With one of them off, HCL only controls the other attribute; changes of the attribute HCL does not adapt no longer pause the light. Sleep mode still switches lights off. Both switches keep their state across reloads and restarts.
- **Manual control through Home Assistant**: HCL sends its commands with its own context. Commands from apps, dashboards, scenes, automations or voice assistants that change brightness or colour of a light that is on now pause the light immediately (also inside the 22-s window after an HCL update, where such changes were missed before).
- **Option "Keep values of turn-on commands"** (default off): a light switched on through Home Assistant with its own values keeps them instead of receiving the HCL values.
- **Manual-control options**: time until HCL takes a paused light back (default 240 min as before, 0 = never), whether switching a light off ends manual control (default on as before), and whether manual control survives Home Assistant restarts (default off as before).
- **Attribute `manual_control`** on the HCL switch listing the paused lights.
- **Scenario options**: brightness and colour temperature of Focus, Relax and Cleaning (defaults unchanged) and an optional duration after which they return to Auto (attribute `until` on the scenario select; kept across restarts).
- **Update options**: update interval (default 27 s), transition of updates (default 20 s) and transition when a light is switched on (default 0 s).
- **Setup**: wake, midday and sleep time can be set when adding the integration; wake and sleep time must be more than 6 hours apart (also checked in the options).
- **Dashboard card**: add points (button or double-click), delete the selected point (button or Del), numeric input of time/brightness/colour temperature, undo (button or Ctrl+Z), a marker for the current time with the current values, the effective brightness under min/max limits as a dashed line, and scenario lines with the configured values.
- **Dashboard card**: German and English texts following the Home Assistant language; colours follow the active Home Assistant theme (light and dark).
- **Translations**: names of the scenario states, the new entities and options, and the `update_curve` service.
- German quick guide `README.de.md`; hassfest check in the CI workflow.

### Changed
- **Entity names**: the HCL switch is now called "HCL active" ("HCL aktiv") and the mode select "Scenario" ("Szenario"). Existing installations keep their entity IDs; new installations get IDs like `switch.<name>_hcl_active` and `select.<name>_scenario`. The scenario select is no longer a configuration entity, so it appears in auto-generated dashboards and can be exposed to voice assistants.
- **Targets** given as devices, areas, floors or labels are resolved again when the entity, device or area registry changes (e.g. a new light in a selected area).
- **Curve sensor**: the state is a timestamp (device class `timestamp`, time of the last curve/scenario change); the curve data attributes are no longer written to the recorder database.
- **Options** are split into three pages (curve and lights, updates and manual control, scenarios).
- The `update_curve` service is registered once for the integration and stays available while no entry is loaded; the card resource is registered once per Home Assistant run instead of on every reload.
- **Revert** in the card uses the anchor times entered at setup when no curve was saved and no anchor options exist.
- A paused light that is found switched off during an update cycle is released (if switching off ends manual control), e.g. after a switch-off that HCL did not see.
- README: descriptions of the default profile and presets corrected (midday dip is part of the default profile, not a norm requirement; there is no "Shift Work" preset).

### Fixed
- **Manifest**: `http` added as dependency and `lovelace` as after-dependency (the integration uses both); the invalid key `funding_url` was removed and `documentation`/`issue_tracker` point to the repository (hassfest).
- `tests/test_hcl_math_v4.py` runs again (no Windows path and module mocks).

## [0.5.1] - 2026-09-23
### Fixed
- **Sleep Mode**: A light switched on manually during Sleep mode is no longer switched off again by the next update cycle; it is treated as a manual override (as documented for 0.5.0-beta1).
- **Options lost the edited curve**: Saving the integration options replaced all options and silently deleted the curve saved in the dashboard card. Options are now merged; the saved curve is only discarded when Wake, Midday or Sleep Time is changed.
- **Manual colour changes right after an HCL update**: Colour temperature or colour changes made within the ignore window after an HCL update (22 s) were not detected and were reverted by the next cycle. Changes that move the light away from the HCL target are now detected for brightness, colour temperature and XY colour.
- **Endless updates**: Lights in XY mode (colour bulbs, XY simulation) and CT lights whose range does not cover the target (e.g. 2200–4000 K) were re-sent every 27 s. The comparison now uses the reachable colour temperature or the XY colour. This also prevents false manual-override detection on such lights.
- **Overrides lost on save**: Saving the curve or the options reloads the entry; manual overrides are now kept across the reload (still cleared by a Home Assistant restart).
- **Anchor times**: Wake/Midday/Sleep combinations that did not leave room for all sectors produced duplicate or out-of-order curve points (e.g. 07:00/14:00/21:00). Midday is now moved into its feasible range, and days shorter than ~11 h scale the default profile.
- **Curves with gaps longer than 12 h**: Interpolation crashed with a division by zero (e.g. two-point curves) or overshot and differed from the dashboard card. Slopes now use forward distances on the 24 h cycle.
- **Floor and label targets**: Floors and labels selected in the target selector were ignored. Label support was also proposed by @joneshf in #1 – thank you!
- **Startup race**: Light groups that finish loading after HCL were not expanded to their members until the switch was toggled. Targets are resolved again when Home Assistant has started.
- **Card mode chips**: The chips now show the actual mode of the select entity (also after restarts or changes by automations).
- **Card brightness limits**: The curve sensor now exposes `min_brightness`/`max_brightness`, so the card shades the clipped ranges again.
- **Lovelace resource registration**: Resources are loaded before they are checked or changed. Previously, depending on the Home Assistant version, the card resource was added again on each start or other stored dashboard resources were overwritten. YAML-mode resources are no longer touched (setup could fail when an old HCL resource URL was present).
- **Re-engagement**: After the 4-hour override timeout, HCL no longer switches on lights that are off.
- **Card styles**: A missing `:host` selector discarded the card's main style rules.
- **Card scenario line**: The horizontal line for the active scenario (announced in 0.5.0-beta1) is now drawn.
- **Translations**: English Repair Issue text and the name field label in the setup form were missing.
- **Service `update_curve`**: Input is validated (mode, at least two points with valid ranges); `revert` is listed in `services.yaml` and `points` is optional for it.
- **Repair Issue**: The card setup notice is removed when the integration entry is deleted.
- **Mode select without device**: The mode select entity was not assigned to the HCL device, so it was named `select.mode` (`select.mode_2`, … for further instances). New installations now get `select.<instance>_mode`; existing entity IDs are kept by the entity registry and the entity is attached to its HCL device.
- **Scenario chips after adding an instance**: The curve sensor did not know the mode select of a newly added instance (`mode_entity_id` stayed empty until the next curve/mode update), so the card chips did nothing. The sensor now follows the registration and renaming of its mode select.
- **Minimum Home Assistant version**: `hacs.json` now requires 2024.7.0 (needed for `StaticPathConfig`).

### Added
- Test suite based on `pytest-homeassistant-custom-component` (`tests/`) and Playwright browser tests for the card (`tests_frontend/`).
- GitHub Actions workflow running the tests against the minimum supported and the current Home Assistant release.

## [0.5.0-beta2] - 2026-02-04
### Fixed
- **Race Condition**: Resolved issue where "Scenario Chips" didn't work immediately after startup because the Select Entity wasn't found in time.
- **Diagnostics**: Added console warnings in Frontend if configuration is incomplete.

## [0.5.0-beta1] - 2026-02-04
### Added
- **Scenario Engine**: New `select.hcl_mode` entity allows robust switching between modes.
- **Fixed Scenarios**:
    - **Pro Modes**: Focus (5500K/100%), Relax (2700K/40%), Cleaning (4000K/100%).
    - **Guest Mode**: Pauses HCL updates completely, allowing manual control without fighting back.
    - **Sleep Mode**: Turns lights off, but allows manual override.
- **Frontend Upgrade**: `hcl-curve-card` now features "Chip" selectors for modes and visualizes the active scenario with a horizontal line in the chart.
- **Persistence**: Active mode is saved and restored after Home Assistant restarts.

## [0.4.1] - 2026-02-04
### Changed
- **Manual Preview Mode**: Dragging points in the graph no longer sends immediate updates to lights. This prevents "Time Paradox" flickering and reduces network traffic.
- **Visual Feedback**: The "PREVIEW" button now highlights (Yellow/Asterisk) to indicate unsaved changes.
- **Documentation**: Corrected the description of "Manual Override" behavior in README (it is per-light, not global).

### Fixed
- **Revert Logic**: The "REVERT" button now correctly and immediately resets the curve in the UI to the last saved state.
- **UI Consistency**: Renamed "VORSCHAU" button to "PREVIEW" to match the rest of the interface.

## [0.4.0] - 2026-02-02
### Added
- **Interactive Dashboard Card**: A fully interactive, touch-friendly Lovelace card (`custom:hcl-curve-card`) allowing drag-and-drop adjustment of Brightness and Color Temperature curves.
- **Visual Editor**: Integrated directly into the Dashboard card. Features include:
    - **Presets**: 12-point scientifically inspired profiles (Default, Focus, Relax, Early Bird, Night Owl).
    - **Validation Engine**: Real-time feedback on curve plausibility (e.g., "Night too bright") with visual warning zones.
    - **Live Preview**: "Test" button to temporarily apply the curve to lights without saving.
    - **Undo/Redo**: "Revert" button to discard unsaved changes.
- **Smart Onboarding**: Detects new installations and automatically creates a "Repair Issue" with a one-click guide to add the dashboard card.
- **Localization**: Full English and German translations for Configuration, Options, and Onboarding flows.

### Changed
- **Interpolation Engine**: Upgraded to **PCHIP** (Piecewise Cubic Hermite Interpolating Polynomial) for smoother, overshoot-free transitions between points.
- **Minimum/maximum brightness** *(note added in 0.6.1)*: the limits clip the curve (values below the minimum are raised to it, values above the maximum are lowered to it). Up to 0.3.0 the whole curve was scaled into the min–max range. This change was not listed in the 0.4.0 notes.
- **Performance**:
    - **Smart Traffic Control**: Reduced Zigbee/Z-Wave traffic by ~90% via intelligent debouncing and delta-checks.
    - **Frontend Optimization**: Hardware-accelerated rendering and efficient state synchronization to prevent UI lag.
- **Theming & Accessibility**:
    - **Light & Dark Mode**: Full support for Home Assistant themes with correct contrast handling.
    - **Accessibility**: High-contrast chart elements and full keyboard navigation (Arrow keys) with ARIA support.

### Fixed
- **Stability**: Resolved multiple race conditions during Home Assistant startup and dashboard navigation.
- **Memory**: Backend logic includes automated zombie-listener cleanup to prevent memory leaks after reload.
- **Smart Override**: Improved detection of manual light changes to effectively pause HCL when a user intervenes via wall switch or app.

## [0.3.0] - 2026-01-30
### Added
- **User-Customizable Schedule**:
    - **Dynamic Anchors**: Define your own `Wake Time`, `Midday (Dip)`, and `Sleep Time`.
    - **Shift Work Support**: Handles schedules that wrap around midnight seamlessly.
    - **Elastic Intervals**: Intelligent math prevents "impossible" curves.
- **Custom Instance Naming**: Assign unique names during setup.
- **Translations**: Added full English and German translations for all new configuration options.

### Changed
- **Refined Default Curve**: Tuned default generation to match the natural profile of v0.2.1 (Centered Midday Dip, Simpler Phases).
- **Math**: Improved Midnight wrapping logic to effectively handle day crossings.

### Fixed
- **Stability**: Fixed "Brightness Ping-Pong" where brightness would oscillate by ±1%.
- **Isolation**: Critical fix ensuring multiple HCL instances do not leak curve data to each other.
- **Null Safety**: Hardened `OverrideManager` against startup race conditions.


## [0.2.1] - 2026-01-28
### Added
- **Smart Override 2.0**:
    - **Divergence Detection**: Distinguishes between natural HCL transitions and manual interventions.
    - **Color Support**: Detects manual color changes via XY/RGB divergence check.
    - **Steep Slope Tolerance**: Intelligent logic prevents false positives during the aggressive 12:15 PM HCL dip.
- **Instant-On Performance**:
    - **Fast-Path HCL**: Lights receive settings *immediately* upon turning on, bypassing "Color Flash".
    - **Zero Latency**: Optimization of task scheduling ensures commands hit the network instantly.
- **Smart Traffic Control**:
    - **Dynamic Thresholds**: Updates are only sent if values change significantly (>100K or >2%).
    - **Timezone Awareness**: Calculations now strictly follow Local Time.

### Changed
- **Architecture**: Split monolithic code into modules (`hcl_math`, `light_controller`, `override_manager`).
- **Resilient Update Loop**: Parallel execution (asyncio) ensures one failing light doesn't block others.
- **Capabilities**: Enhanced auto-detection of light capabilities (XY vs CT) with safe caching.

### Fixed
- **Group Safety**: Automatic filtering of Zigbee/Hue groups to prevent "Double Control" conflicts.
- **Zombie Cleanup**: Strict timer management prevents ghost updates after reloads.
- **Memory Safety**: Automated cache pruning prevents long-term memory leaks.


## [0.1.0] - 2026-01-24
### Added
- Initial release of HCL Lighting integration.
- Automatic brightness and color temperature adjustment based on time of day.
- Cubic Hermite spline interpolation for smooth, natural transitions.
- Support for DIN SPEC 67600 inspired HCL curve (Morning, Midday, Evening).
- Flexible targeting system (Entities, Devices, Areas, Groups).
- Automatic light capability detection and Extended Warm White simulation (XY).
- Optional "Smart Transition" mode.
- Configurable brightness limits (min/max).
- Instant HCL application when lights turn on.
- State restoration after Home Assistant restart.
- Full UI configuration (no YAML required).
- German and English translations.

[0.6.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.6.0
[0.5.1]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.5.1
[0.4.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.4.0
[0.3.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.3.0
[0.2.1]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.2.1
[0.2.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.2.0
[0.1.0]: https://github.com/Ecronika/ha_hcl/releases/tag/v0.1.0
