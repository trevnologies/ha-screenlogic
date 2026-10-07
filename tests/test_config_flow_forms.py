"""The config and options forms render through the real HTTP API.

Catches schemas built with a library the running Home Assistant can't
serialize (voluptuous vs probatio, core #182112).
"""

from __future__ import annotations

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.screenlogic.config_flow  # noqa: F401
from custom_components.screenlogic.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component


async def _names(resp) -> tuple[str, list[str]]:
    assert resp.status == 200, await resp.text()
    data = await resp.json()
    return data["step_id"], [f["name"] for f in data["data_schema"]]


async def test_forms(hass: HomeAssistant, hass_client) -> None:
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()

    with patch(
        "custom_components.screenlogic.config_flow.discovery.async_discover",
        return_value=[],
    ):
        resp = await client.post(
            "/api/config/config_entries/flow", json={"handler": DOMAIN}
        )
        step, names = await _names(resp)
        assert step == "user"

        # Local path with no gateways discovered -> manual entry form.
        resp = await client.post(
            "/api/config/config_entries/flow", json={"handler": DOMAIN}
        )
        flow_id = (await resp.json())["flow_id"]
        resp = await client.post(
            f"/api/config/config_entries/flow/{flow_id}",
            json={names[0]: "local"},
        )
        step, fields = await _names(resp)
        assert step in ("gateway_select", "gateway_entry")

    # Remote path form.
    resp = await client.post(
        "/api/config/config_entries/flow", json={"handler": DOMAIN}
    )
    flow_id = (await resp.json())["flow_id"]
    resp = await client.post(
        f"/api/config/config_entries/flow/{flow_id}", json={names[0]: "remote"}
    )
    step, fields = await _names(resp)
    assert step == "remote"

    # Options form.
    entry = MockConfigEntry(domain=DOMAIN, title="Pool", data={}, unique_id="aa")
    entry.add_to_hass(hass)
    resp = await client.post(
        "/api/config/config_entries/options/flow", json={"handler": entry.entry_id}
    )
    step, fields = await _names(resp)
    assert step == "init"
    assert "scan_interval" in fields
