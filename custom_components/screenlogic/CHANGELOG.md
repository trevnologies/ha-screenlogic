# Changelog

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