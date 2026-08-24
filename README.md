# Pentair ScreenLogic (Remote Support)

[![Validate with hassfest](https://github.com/trevnologies/ha-screenlogic/actions/workflows/hassfest.yml/badge.svg)](https://github.com/trevnologies/ha-screenlogic/actions/workflows/hassfest.yml)
[![Validate with HACS](https://github.com/trevnologies/ha-screenlogic/actions/workflows/hacs.yml/badge.svg)](https://github.com/trevnologies/ha-screenlogic/actions/workflows/hacs.yml)

A Home Assistant custom integration for Pentair ScreenLogic-connected pool
and spa controllers (EasyTouch / IntelliTouch), forked from Home Assistant
core's built-in `screenlogic` integration.

## Why this exists

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
  client and drifts over time ([home-assistant/discussions#4126](https://github.com/orgs/home-assistant/discussions/4126))

## Attribution

This repository's history is extracted directly from
[home-assistant/core](https://github.com/home-assistant/core)'s
`homeassistant/components/screenlogic` — commit history for anything
unmodified traces back to its original authors. See [NOTICE](NOTICE) and
[LICENSE](LICENSE) for full attribution. This project is not affiliated
with or endorsed by Home Assistant, Nabu Casa, or Pentair.

## Installation

### Via HACS (custom repository)

1. HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/trevnologies/ha-screenlogic`, category "Integration"
3. Install "Pentair ScreenLogic (Remote Support)"
4. Restart Home Assistant
5. Settings → Devices & Services → Add Integration → search "ScreenLogic"

Because this uses the same `screenlogic` domain as core's built-in
integration, installing it is a drop-in replacement — it takes over for
core's version rather than running alongside it.

### Manual

Copy `custom_components/screenlogic/` into your Home Assistant `config/custom_components/` directory and restart.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
