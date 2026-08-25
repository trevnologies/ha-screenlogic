# Changelog

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