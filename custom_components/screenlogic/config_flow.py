"""Config flow for ScreenLogic (with remote gateway support)."""

from __future__ import annotations

import asyncio
import logging
import socket
import struct
from typing import Any

from screenlogicpy import ScreenLogicError, discovery
from screenlogicpy.const.common import SL_GATEWAY_IP, SL_GATEWAY_NAME, SL_GATEWAY_PORT
from screenlogicpy.requests import login
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_IP_ADDRESS, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .const import (
    CONF_CONNECTION_TYPE,
    CONF_PASSWORD,
    CONF_SYSTEM_NAME,
    CONNECTION_LOCAL,
    CONNECTION_REMOTE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    PENTAIR_SERVER_HOST,
    PENTAIR_SERVER_PORT,
)

_LOGGER = logging.getLogger(__name__)

GATEWAY_SELECT_KEY = "selected_gateway"
GATEWAY_MANUAL_ENTRY = "manual"
GATEWAY_REMOTE_ENTRY = "remote"

PENTAIR_OUI = "00-C0-33"


# ── Remote resolution helpers ─────────────────────────────────────────────────


async def async_resolve_remote_gateway(system_name: str) -> dict[str, Any] | None:
    """
    Contact Pentair's discovery server and resolve IP/port for a system name.

    Protocol (same as the Pentair app and node-screenlogic):
      • TCP connect to screenlogicserver.pentair.com:500
      • Send 8-byte header (senderId=0, msgId=18003, payload length) +
        payload (system-name SLString, sent twice)
      • Response header: senderId, msgId (18004 == request msgId + 1), payload length
      • Response payload:
          [0]        gatewayFound  (0/1)
          [1]        licenseOK     (0/1)
          [2:]       ipAddr        SLString (4-byte LE length + utf-8 bytes,
                                    padded so the *string* ends on a 4-byte
                                    boundary)
          next 2B    port          little-endian
          next 1B    portOpen      (0/1) — whether the gateway's port is
                                    directly reachable from the internet
          next 1B    relayOn       (0/1) — whether Pentair's relay is active
                                    for this gateway
    Returns {"ip_address": str, "port": int, "port_open": bool, "relay_on": bool}
    or None on failure.
    """

    def _read_full_response(sock: socket.socket) -> bytes:
        """Read until we have the full 8-byte header + declared payload length.

        A single recv() call is not guaranteed to return the whole message
        for a TCP stream, especially over the internet rather than LAN.
        """
        buf = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
            if len(buf) >= 8:
                _, _, plen = struct.unpack_from("<HHI", buf, 0)
                if len(buf) >= 8 + plen:
                    break
        return buf

    def _resolve() -> dict[str, Any] | None:
        try:
            # Build request: 8-byte header + payload (system name as SLString, sent twice)
            name_field = _sl_string(system_name)
            payload = name_field + name_field
            MSG_ID = 18003
            EXPECTED_RESPONSE_ID = MSG_ID + 1  # 18004

            header = struct.pack("<HHI", 0, MSG_ID, len(payload))
            request = header + payload

            with socket.create_connection(
                (PENTAIR_SERVER_HOST, PENTAIR_SERVER_PORT), timeout=10
            ) as sock:
                sock.sendall(request)
                resp = _read_full_response(sock)

            if len(resp) < 8:
                _LOGGER.error("ScreenLogic remote: response too short")
                return None

            _, msg_id, plen = struct.unpack_from("<HHI", resp, 0)

            if msg_id != EXPECTED_RESPONSE_ID:
                _LOGGER.error(
                    "ScreenLogic remote: unexpected response id %d (expected %d)",
                    msg_id,
                    EXPECTED_RESPONSE_ID,
                )
                return None

            data = resp[8:8 + plen]

            if len(data) < 2 or data[0] == 0:
                _LOGGER.warning(
                    "ScreenLogic remote: gateway not found for '%s'", system_name
                )
                return None

            # Parse IP (SLString starting at offset 2)
            str_len = struct.unpack_from("<I", data, 2)[0]
            ip_address = data[6:6 + str_len].decode("utf-8")

            # Pad the *string length* up to the next 4-byte boundary (matches
            # node-screenlogic's SLMessage.slackForAlignment: (4 - len % 4) % 4).
            # NOTE: previously this was computed as (str_len + 4) & ~3, which
            # overshoots by 4 bytes whenever str_len is already a multiple of
            # 4 — that bug is what produced the bogus port value.
            slack = (4 - str_len % 4) % 4
            offset = 2 + 4 + str_len + slack

            port, port_open, relay_on = struct.unpack_from("<H??", data, offset)

            _LOGGER.debug(
                "ScreenLogic remote resolved '%s' -> %s:%d "
                "(port_open=%s relay_on=%s)",
                system_name,
                ip_address,
                port,
                port_open,
                relay_on,
            )
            return {
                "ip_address": ip_address,
                "port": port,
                "port_open": port_open,
                "relay_on": relay_on,
            }

        except (OSError, struct.error, ValueError) as err:
            _LOGGER.error("ScreenLogic remote discovery error: %s", err)
            return None

    return await asyncio.get_event_loop().run_in_executor(None, _resolve)


def _sl_string(s: str) -> bytes:
    """Encode a string in ScreenLogic SLString format: 4-byte LE length + bytes + null padding to 4-byte boundary."""
    b = s.encode("utf-8")
    length = len(b)
    padded_len = (length + 4) & ~3
    return struct.pack("<I", length) + b + b'\x00' * (padded_len - length)


# ── Original helpers (unchanged) ──────────────────────────────────────────────


async def async_discover_gateways_by_unique_id() -> dict[str, dict[str, Any]]:
    """Discover gateways and return a dict of them by unique id."""
    discovered_gateways: dict[str, dict[str, Any]] = {}
    try:
        hosts = await discovery.async_discover()
        _LOGGER.debug("Discovered hosts: %s", hosts)
    except ScreenLogicError as ex:
        _LOGGER.debug(ex)
        return discovered_gateways

    for host in hosts:
        if (name := host[SL_GATEWAY_NAME]).startswith("Pentair:"):
            mac = _extract_mac_from_name(name)
            discovered_gateways[mac] = host

    _LOGGER.debug("Discovered gateways: %s", discovered_gateways)
    return discovered_gateways


def _extract_mac_from_name(name: str) -> str:
    return format_mac(f"{PENTAIR_OUI}-{name.split(':')[1].strip()}")


def short_mac(mac: str) -> str:
    """Short version of the mac as seen in the app."""
    return "-".join(mac.split(":")[3:]).upper()


def name_for_mac(mac: str) -> str:
    """Derive the gateway name from the mac."""
    return f"Pentair: {short_mac(mac)}"


# ── Config flow ───────────────────────────────────────────────────────────────


class ScreenlogicConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow to setup ScreenLogic devices (local or remote)."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize ScreenLogic ConfigFlow."""
        self.discovered_gateways: dict[str, dict[str, Any]] = {}
        self.discovered_ip: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> ScreenLogicOptionsFlowHandler:
        """Get the options flow for ScreenLogic."""
        return ScreenLogicOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the start of the config flow — offer local or remote."""
        if user_input is not None:
            if user_input[CONF_CONNECTION_TYPE] == CONNECTION_REMOTE:
                return await self.async_step_remote()
            # Local: proceed with original discovery flow
            self.discovered_gateways = await async_discover_gateways_by_unique_id()
            return await self.async_step_gateway_select()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONNECTION_TYPE, default=CONNECTION_LOCAL
                    ): vol.In(
                        {
                            CONNECTION_LOCAL: "Local network (auto-discover or enter IP)",
                            CONNECTION_REMOTE: "Remote via Pentair cloud (System Name + Password)",
                        }
                    )
                }
            ),
        )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle dhcp discovery."""
        mac = format_mac(discovery_info.macaddress)
        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured(
            updates={CONF_IP_ADDRESS: discovery_info.ip}
        )
        self.discovered_ip = discovery_info.ip
        self.context["title_placeholders"] = {"name": discovery_info.hostname}
        return await self.async_step_gateway_entry()

    # ── Local steps (original, unchanged) ────────────────────────────────────

    async def async_step_gateway_select(self, user_input=None) -> ConfigFlowResult:
        """Handle the selection of a discovered ScreenLogic gateway."""
        existing = self._async_current_ids(include_ignore=False)
        unconfigured_gateways = {
            mac: gateway[SL_GATEWAY_NAME]
            for mac, gateway in self.discovered_gateways.items()
            if mac not in existing
        }

        if not unconfigured_gateways:
            return await self.async_step_gateway_entry()

        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[GATEWAY_SELECT_KEY] == GATEWAY_MANUAL_ENTRY:
                return await self.async_step_gateway_entry()

            mac = user_input[GATEWAY_SELECT_KEY]
            selected_gateway = self.discovered_gateways[mac]
            await self.async_set_unique_id(mac, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=name_for_mac(mac),
                data={
                    CONF_CONNECTION_TYPE: CONNECTION_LOCAL,
                    CONF_IP_ADDRESS: selected_gateway[SL_GATEWAY_IP],
                    CONF_PORT: selected_gateway[SL_GATEWAY_PORT],
                },
            )

        return self.async_show_form(
            step_id="gateway_select",
            data_schema=vol.Schema(
                {
                    vol.Required(GATEWAY_SELECT_KEY): vol.In(
                        {
                            **unconfigured_gateways,
                            GATEWAY_MANUAL_ENTRY: (
                                "Manually configure a ScreenLogic gateway"
                            ),
                        }
                    )
                }
            ),
            errors=errors,
            description_placeholders={},
        )

    async def async_step_gateway_entry(self, user_input=None) -> ConfigFlowResult:
        """Handle the manual entry of a ScreenLogic gateway."""
        errors: dict[str, str] = {}
        ip_address = self.discovered_ip
        port = 80

        if user_input is not None:
            ip_address = user_input[CONF_IP_ADDRESS]
            port = user_input[CONF_PORT]
            try:
                mac = format_mac(await login.async_get_mac_address(ip_address, port))
            except ScreenLogicError as ex:
                _LOGGER.debug(ex)
                errors[CONF_IP_ADDRESS] = "cannot_connect"

            if not errors:
                await self.async_set_unique_id(mac, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=name_for_mac(mac),
                    data={
                        CONF_CONNECTION_TYPE: CONNECTION_LOCAL,
                        CONF_IP_ADDRESS: ip_address,
                        CONF_PORT: port,
                    },
                )

        return self.async_show_form(
            step_id="gateway_entry",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IP_ADDRESS, default=ip_address): str,
                    vol.Required(CONF_PORT, default=port): int,
                }
            ),
            errors=errors,
            description_placeholders={},
        )

    # ── Remote step (new) ─────────────────────────────────────────────────────

    async def async_step_remote(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle remote cloud-based setup (System Name + Password)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            system_name: str = user_input[CONF_SYSTEM_NAME].strip()
            password: str = user_input.get(CONF_PASSWORD, "")

            resolved = await async_resolve_remote_gateway(system_name)
            if resolved is None:
                errors["base"] = "cannot_connect"
            else:
                # Use system_name as the unique id for remote entries
                await self.async_set_unique_id(
                    format_mac(
                        f"{PENTAIR_OUI}-{system_name.split(':')[1].strip()}"
                    ),
                    raise_on_progress=False,
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=system_name,
                    data={
                        CONF_CONNECTION_TYPE: CONNECTION_REMOTE,
                        CONF_SYSTEM_NAME: system_name,
                        CONF_PASSWORD: password,
                    },
                )

        return self.async_show_form(
            step_id="remote",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SYSTEM_NAME): str,
                    vol.Optional(CONF_PASSWORD, default=""): str,
                }
            ),
            description_placeholders={"example": "Pentair: XX-XX-XX"},
            errors=errors,
        )


# ── Options flow (original, unchanged) ───────────────────────────────────────


class ScreenLogicOptionsFlowHandler(OptionsFlow):
    """Handles the options for the ScreenLogic integration."""

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                title=self.config_entry.title, data=user_input
            )

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=current_interval,
                    ): vol.All(cv.positive_int, vol.Clamp(min=MIN_SCAN_INTERVAL))
                }
            ),
            description_placeholders={"gateway_name": self.config_entry.title},
        )
