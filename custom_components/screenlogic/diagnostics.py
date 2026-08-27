"""Diagnostics for Screenlogic."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_PASSWORD
from .types import ScreenLogicConfigEntry

# CONF_PASSWORD holds the plaintext Pentair remote-access password for
# remote/cloud config entries. Core's screenlogic integration has no
# credential field at all, so this file was otherwise byte-identical to
# core's version -- which meant `config_entry.as_dict()` was shipping that
# password unredacted in every diagnostics export. Redact it here.
TO_REDACT = {CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ScreenLogicConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = config_entry.runtime_data

    return {
        "config_entry": async_redact_data(config_entry.as_dict(), TO_REDACT),
        "data": coordinator.gateway.get_data(),
        "debug": coordinator.gateway.get_debug(),
    }
