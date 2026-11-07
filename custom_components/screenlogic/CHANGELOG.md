# Changelog

## 1.3.0 - 2026-11-07

**Requires Home Assistant 2026.11 or later.** HACS won't offer this release
to older installs.

### Changed
- Names follow Home Assistant 2026.11's naming, where a name is built from the
  device name and the entity name, so they no longer repeat each other:
  - **Pool and Spa are now their own devices**, as child devices of the
    controller (they take its area unless you give them one). Each body's
    circuit is that device's main entity, so it shows as just "Pool" or
    "Spa". Circuits on a body's tab in the controller move with it and lose
    the repeated name: "Pool Low" stays "Pool Low" instead of becoming
    "<controller> Pool Low", "Cleaner" becomes "Pool Cleaner", "Air Blower"
    becomes "Spa Air Blower". The heaters ("Pool Heat", "Spa Heat"), the
    pool and spa delay sensors and the chlorinator setpoints move to their
    body as well. Features, lights and hidden circuits stay on the
    controller.
  - **Pump devices are named by the controller** ("Pool Pump", "Waterfall
    Pump") instead of "Pump 1" / "Pump 2". The running sensor is the pump's
    main entity and the rest drop the repeated pump name ("Pool Pump Watts
    Now" instead of "Pump 1 Pool Pump Watts Now"). Pumps stay separate
    devices connected through the controller.
- Entity IDs don't change: existing entities move to their new device and
  keep their IDs and history.
- A name you set on an entity yourself is kept. If you renamed one to tell
  two entities apart (for example "Heat Pool" and "Heat Spa"), clear that name
  in the entity's settings to use the new one.

### Ported from upstream (#30)
- home-assistant/core#186199: `async_setup_entry` and `async_unload_entry`
  return `None`, and unloading uses `async_unload_platforms_or_raise`.
- home-assistant/core#187045: manifest `categories` (`water.pools_spas`).
- home-assistant/core#189910: manifest `connectivity`. Core lists only
  `network`; this fork also connects through Pentair's cloud relay, so it
  lists `cloud` and `network`.

### Added
- Tests for the device structure and every changed name, run against a real
  EasyTouch2 8's data. They need Home Assistant 2026.11 and are skipped on
  the current test harness (2026.10.4) until its 2026.11 release.

## 1.2.4 - 2026-10-07

### Changed
- Ported two upstream Home Assistant core changes to the ScreenLogic
  integration (tracked in #19):
  - home-assistant/core#180161: services now look up their target config
    entry with core's shared `async_get_config_entry` helper, so "entry not
    found / not loaded / wrong integration" errors use Home Assistant's
    standard translated messages.
  - home-assistant/core#182112: config flow, options flow, and service
    schemas use probatio, Home Assistant's replacement for voluptuous,
    when the running release does (2026.10+), and voluptuous on earlier
    releases.
- Minimum Home Assistant version in `hacs.json` is now 2026.7.0. The
  integration already required it (it uses `UnitOfRatio`, added in
  2026.7); HACS was still advertising 2024.1.0, which would install on
  releases where it can't load.

### Added
- Test suite (`tests/`) and a `Tests` workflow, run against Home Assistant
  2026.7, 2026.9 and 2026.10 for this release.

## 1.2.3 - 2026-10-07

### Fixed
- Hassfest validation failing on the `screenlogicpy` requirement.
  Home Assistant core depends on the same package, and hassfest now
  rejects exact (`==`) pins on core dependencies. The requirement is
  now `screenlogicpy>=0.10.2`, so the integration follows whatever
  version Home Assistant ships instead of conflicting with it when
  core updates the library.

## 1.2.2

### Fixed
- Pump sensor, binary_sensor, and number entities failing to load
  ("Error adding entity None for domain ... with platform
  screenlogic") on recent Home Assistant core versions. Caused by
  the deprecated `via_device` device-registry parameter now raising
  instead of warning. Pump devices are now linked to the gateway
  device via `via_device_id`, resolved once at setup.

## 1.2.1 - 2026-08-27

### Fixed

- Diagnostics no longer leak the remote-access password — `diagnostics.py`
  was untouched from core (which has no password field at all), so
  `config_entry.as_dict()` was shipping it in plaintext in every export.
  Now redacted.
- Restored DHCP auto-discovery — `manifest.json` had dropped the `dhcp`
  matcher block even though `async_step_dhcp` was still fully implemented,
  so local gateways never triggered the "Discovered" prompt
- Restored automatic gateway rediscovery for local connections, matching
  core's behavior of following IP changes (DHCP lease renewals, etc.)
  instead of only using the IP stored at setup time. Remote connections
  are unaffected
- Climate preset mode (Heater / Solar / Solar preferred / Don't change)
  now shows proper labels instead of raw internal values
- Local setup steps (gateway selection, manual IP entry) show their
  descriptive help text again
- Restored `loggers: ["screenlogicpy"]` in `manifest.json` so "Enable
  debug logging" also captures the underlying library's debug output
- CI: `validate.yml`'s `push` trigger is now scoped to `main` (matching
  `codeql.yml`), so Hassfest/HACS no longer run twice per PR
- Replace deprecated HA constants (`PERCENTAGE`, `CONCENTRATION_PARTS_PER_MILLION`)
  ahead of their removal in HA Core 2027.8
- Add explicit job-level permissions to CI workflows

### Changed

- Renamed to "Pentair ScreenLogic (w/ Remote Support)" and clarified in
  the README/FAQ that local network connections are fully supported and
  remain the default — remote/cloud is purely additive

## 1.2.0 - 2026-08-24

### Added

- Pump preset speed control — a `number` entity per configured pump
  preset (Pool/Spa/Pool Low/Spillway/Cleaner), letting you set any speed
  within the supported range (450-3450 RPM or 20-140 GPM, per official
  Pentair IntelliFlo specs) instead of only picking among fixed presets.
  Not yet supported by screenlogicpy — implemented by calling its
  internal request machinery directly, with the message structure
  confirmed against parnic/node-screenlogic's `setPumpFlowAsync`, until
  this can be contributed upstream
- Controller Time and Controller Time Drift sensors, surfacing date/time
  data screenlogicpy already polls on every update cycle but never
  exposed — useful for confirming whether the Sync Controller Time button
  actually did anything

## 1.1.0 - 2026-08-24

### Added

- Remote/cloud connectivity — connect over Pentair's cloud relay, not just
  local network (this fork's core differentiator from Home Assistant core's
  built-in `screenlogic` integration)
- Pump diagnostics split onto their own device — GPM/RPM/Watts now live on
  a dedicated "Pump N" device page instead of the main gateway's
  diagnostics list
- An "active program" sensor for pumps shared across multiple circuits
  (e.g. Pool/Spa/Pool Low/Spillway/Cleaner on one physical pump), reporting
  which program is actually driving the pump right now
- IntelliBrite/ColorLogic light effects — select show/color modes (Party,
  Romance, Caribbean, Sunset, solid colors, etc.) on controllers that
  report IntelliBrite equipment, instead of on/off only
- A controller time-sync button, since the EasyTouch/IntelliTouch
  controller has no NTP client and drifts over time
  ([home-assistant/discussions#4126](https://github.com/orgs/home-assistant/discussions/4126))
- `services.yaml` for the three services `services.py` registers
  (`set_color_mode`, `start_super_chlorination`, `stop_super_chlorination`),
  so they show up in Developer Tools > Services with real field
  descriptions and validation instead of no schema at all

### Fixed

- `strings.json`/`translations/en.json` had no `entity` translation block
  at all, so every `translation_key`-based entity (most of
  `binary_sensor`, `sensor`, `number`, `climate`) fell back to showing
  just the device name with no distinguishing label