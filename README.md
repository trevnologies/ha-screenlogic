# Pentair ScreenLogic (Remote Support)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/trevnologies/ha-screenlogic/actions/workflows/validate.yml/badge.svg)](https://github.com/trevnologies/ha-screenlogic/actions/workflows/validate.yml)
[![CodeQL](https://github.com/trevnologies/ha-screenlogic/actions/workflows/codeql.yml/badge.svg)](https://github.com/trevnologies/ha-screenlogic/actions/workflows/codeql.yml)

A Home Assistant custom integration for Pentair ScreenLogic-connected pool
and spa controllers (EasyTouch / IntelliTouch), forked from Home Assistant
core's built-in `screenlogic` integration.

## Why This Fork Exists

Core's `screenlogic` integration is solid but has a few real gaps this fork
closes:

- **Remote/cloud connectivity** — connect over Pentair's cloud relay, not
  just local network (`iot_class: cloud_polling` instead of `local_push`)
- **Correct entity naming** — core's translation strings for several
  diagnostic entities (delay flags, controller state, chemistry/SCG
  entities) were incomplete, so they fell back to showing just the device
  name with no distinguishing label. Fixed here.
- **Pump diagnostics split onto their own device** — pump GPM/RPM/Watts
  now live on a dedicated "Pump N" device page instead of the main
  gateway's diagnostics list
- **An "active program" sensor** — for pumps shared across multiple
  circuits (e.g. Pool/Spa/Pool Low/Spillway/Cleaner on one physical pump),
  reports which program is actually driving the pump right now, instead of
  a static, sometimes-misleading circuit name
- **IntelliBrite / ColorLogic light effects** — select show/color modes
  (Party, Romance, Caribbean, Sunset, solid colors, etc.) instead of
  on/off only, on controllers that report IntelliBrite equipment
- **Controller time sync** — a button to sync the EasyTouch/IntelliTouch's
  clock to Home Assistant's current time, since the controller has no NTP
  client and drifts over time
  ([home-assistant/discussions#4126](https://github.com/orgs/home-assistant/discussions/4126))
- **Controller Time and Time Drift sensors** — surfaces date/time data the
  underlying library already polls but never exposed, so you can see
  drift at a glance and confirm the sync button actually worked
- **Pump preset speed control** — a `number` entity per configured pump
  preset (Pool/Spa/Pool Low/Spillway/Cleaner), letting you set any speed
  within the supported range instead of only picking among fixed presets

## Installation

### HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=trevnologies&repository=ha-screenlogic&category=integration)

1. Click the badge above — opens your HA instance directly to the "add
   custom repository" dialog with this repo pre-filled (requires
   [My Home Assistant](https://www.home-assistant.io/integrations/my/),
   on by default for most setups)
2. Confirm, then find "Pentair ScreenLogic (Remote Support)" in HACS and
   install
3. Restart Home Assistant

Or manually:

1. HACS → Integrations → ⋮ (top right) → Custom repositories
2. Repository: `https://github.com/trevnologies/ha-screenlogic`, Category: Integration
3. Search for "Pentair ScreenLogic (Remote Support)" and install
4. Restart Home Assistant

### Manual (no HACS)

Copy `custom_components/screenlogic/` into your Home Assistant
`config/custom_components/` directory and restart.

Because this uses the same `screenlogic` domain as core's built-in
integration, installing it is a drop-in replacement — it takes over for
core's version rather than running alongside it. If core's `screenlogic`
is currently configured, no need to remove it first; this fork's config
flow will find and reuse the existing config entry on setup.

## Entities Created

Exact set depends on your equipment configuration — chemistry (IntelliChem)
and salt cell (SCG) entities only appear if that equipment is present.

### Sensors
- Air Temperature, Controller State, Controller Time, Controller Time Drift
- Per-pump GPM/RPM/Watts, and an Active Program sensor for pumps shared
  across multiple circuits
- IntelliChem: ORP/pH now and supply level, saturation index, salt/TDS,
  dose state, last dose time/volume, super chlorination timer

### Binary Sensors
- Problem (overall alert), Cleaner/Pool/Spa Delay, Freeze Mode
- IntelliChem alarms: flow, ORP/pH high/low/supply, probe fault, pH
  lockout, corrosive, scaling, salt cell state

### Switches
Every configured circuit (Pool, Spa, and whatever else is programmed at
your panel) as its own switch.

### Light
Pool/spa lights — plain on/off, or full effect selection (Party, Romance,
Caribbean, and more) on controllers reporting IntelliBrite equipment.

### Climate
Pool and spa heat, each as its own climate entity.

### Number
- SCG output setpoints (Pool/Spa %)
- IntelliChem config: calcium hardness, cyanuric acid, total alkalinity
- Pump preset speed — one per configured pump preset, free entry within
  the supported range

### Button
Sync Controller Time — pushes Home Assistant's current time to the
controller.

### Services
- `set_color_mode` — full IntelliBrite/ColorLogic command set, including
  utility commands (Save/Recall/Reset/etc.) the light entity's effect list
  doesn't expose
- `start_super_chlorination` / `stop_super_chlorination`

## Troubleshooting

### Integration not found after install
1. Confirm files are in `config/custom_components/screenlogic/`
2. Check `manifest.json` exists in that folder
3. Restart Home Assistant fully — a config-entry reload isn't enough for
   changed Python code
4. Clear your browser cache

### Entities show generic or duplicate names
If you're upgrading from a version before the entity-naming fix, old
orphaned entities with different IDs can linger alongside the corrected
ones. Settings → Devices & Services → Entities, filter for the affected
domain, remove anything showing "unavailable" with a near-duplicate name.

### Can't connect
Check the controller's IP/port are reachable from Home Assistant, and
that nothing else (the official ScreenLogic app, another integration
instance) is monopolizing the connection — the protocol adapter only
accepts a limited number of concurrent clients.

### Enable debug logging
Add to `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.screenlogic: debug
    screenlogicpy: debug
```
Then restart and check Settings → System → Logs.

## FAQ

**Will this replace the built-in integration?**
Yes, automatically — same domain, so installing this fork takes over from
core's version rather than running alongside it.

**Will this be merged into Home Assistant core?**
Unclear. Core's `screenlogic` is deliberately local-only by design; the
cloud/remote connectivity this fork adds is an architectural difference,
not just a bug fix, so it may not be something core wants regardless of
code quality. Worth pursuing eventually, not something to count on.

**Does this work alongside the official ScreenLogic app?**
Yes — same as core's integration, any number of clients (this integration,
the mobile app, etc.) can talk to the same controller, subject to the
adapter's own connection limits.

**Can I switch back to the built-in integration?**
Yes — remove this custom component, restart, and re-add the integration
normally; core will set up its own config entry the same as it would from
a clean install.

## Attribution

This repository's history is extracted directly from
[home-assistant/core](https://github.com/home-assistant/core)'s
`homeassistant/components/screenlogic` — commit history for anything
unmodified traces back to its original authors. This project is not
affiliated with or endorsed by Home Assistant, Nabu Casa, or Pentair.

## Contributing

Issues and pull requests welcome — [GitHub Issues](https://github.com/trevnologies/ha-screenlogic/issues).

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Changelog

See [CHANGELOG.md](custom_components/screenlogic/CHANGELOG.md) for version history.