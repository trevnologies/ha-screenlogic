"""DataUpdateCoordinator for ScreenLogic (with remote gateway support)."""
# This file replaces the built-in coordinator.py.
# async_get_connect_info, _apply_remote_keepalive, _on_connection_closed,
# and _async_update_data are changed for remote support. The local branch
# of async_get_connect_info mirrors core's rediscovery-first behavior
# exactly (see the "Local connection" comment below) -- everything else
# is original.

from __future__ import annotations

import logging
from datetime import timedelta

from screenlogicpy import ScreenLogicError, ScreenLogicGateway
from screenlogicpy.const.common import ScreenLogicConnectionError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_CONNECTION_TYPE,
    CONF_PASSWORD,
    CONF_SYSTEM_NAME,
    CONNECTION_REMOTE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .config_flow import (
    async_discover_gateways_by_unique_id,
    async_resolve_remote_gateway,
    name_for_mac,
)

_LOGGER = logging.getLogger(__name__)

type ScreenLogicConfigEntry = ConfigEntry[ScreenlogicDataUpdateCoordinator]


def _apply_remote_keepalive(gateway: ScreenLogicGateway, is_remote: bool) -> None:
    """
    Override screenlogicpy's default 300s keepalive for remote/relay connections.

    Pentair's relay enforces an idle-session timeout of ~30s -- far shorter
    than screenlogicpy's hardcoded COM_KEEPALIVE (300s), which never fires
    in time to stop the relay from resetting the connection. This reaches
    into private attributes (not part of screenlogicpy's public API) to
    re-arm the keepalive at a much shorter interval. If screenlogicpy's
    internals change in a future version, this degrades to a logged
    warning rather than a crash.
    """
    if not is_remote:
        return
    try:
        client_manager = gateway._client_manager
        protocol = client_manager._protocol
        if protocol is not None:
            protocol.enable_keepalive(client_manager._async_ping, 15)
            _LOGGER.debug("Applied 15s keepalive override for remote connection")
    except AttributeError as err:
        _LOGGER.warning(
            "Could not override keepalive interval for remote connection "
            "(screenlogicpy internals may have changed): %s",
            err,
        )


async def async_get_connect_info(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    """
    Build the kwargs dict for gateway.async_connect().

    Remote entries: contacts Pentair's servers to resolve the current
    IP/port for the system name, then adds the password.
    Local entries: same as core -- attempt rediscovery first to follow
    IP changes (DHCP lease renewals, etc.), and only fall back to the
    statically configured IP/port if this gateway's MAC isn't found by
    rediscovery.
    """
    if entry.data.get(CONF_CONNECTION_TYPE) == CONNECTION_REMOTE:
        system_name: str = entry.data[CONF_SYSTEM_NAME]
        password: str = entry.data.get(CONF_PASSWORD, "")

        resolved = await async_resolve_remote_gateway(system_name)
        if resolved is None:
            raise ScreenLogicConnectionError(
                f"Could not resolve remote ScreenLogic gateway for '{system_name}'"
            )

        _LOGGER.debug(
            "Remote ScreenLogic '%s' resolved to %s:%d",
            system_name,
            resolved["ip_address"],
            resolved["port"],
        )
        return {
            "name": system_name,
            "ip": resolved["ip_address"],
            "port": resolved["port"],
        }

    # Local connection -- mirrors core's async_get_connect_info: try to
    # rediscover the gateway by MAC first so a DHCP-changed IP is picked
    # up automatically, and only fall back to the IP/port stored at setup
    # time if rediscovery doesn't find this gateway.
    mac = entry.unique_id
    discovered_gateways = await async_discover_gateways_by_unique_id()
    if mac in discovered_gateways:
        return discovered_gateways[mac]

    _LOGGER.debug("Gateway rediscovery failed for %s", entry.title)
    return {
        "name": name_for_mac(mac) if mac else entry.title,
        "ip": entry.data[CONF_IP_ADDRESS],
        "port": entry.data.get(CONF_PORT, 80),
    }


class ScreenlogicDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching ScreenLogic data."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        config_entry: ScreenLogicConfigEntry,
        gateway: ScreenLogicGateway,
    ) -> None:
        """Initialize."""
        self.config_entry = config_entry
        self.gateway = gateway

        scan_interval = config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    def _on_connection_closed(self, *args, **kwargs) -> None:
        """Called by screenlogicpy the moment the socket closes.

        Instead of waiting up to scan_interval (600s) for the next
        scheduled poll to notice the gateway is disconnected, request an
        immediate refresh so the reconnect (and remote re-resolve) happens
        within a second or two of the drop, not up to 10 minutes later.
        """
        _LOGGER.debug("ScreenLogic connection closed -- requesting immediate refresh")
        self.hass.async_create_task(self.async_request_refresh())

    async def _async_update_data(self):
        """Fetch data from ScreenLogic gateway, reconnecting if needed."""
        try:
            if not self.gateway.is_connected:
                connect_info = await async_get_connect_info(
                    self.hass, self.config_entry
                )
                is_remote = (
                    self.config_entry.data.get(CONF_CONNECTION_TYPE)
                    == CONNECTION_REMOTE
                )
                await self.gateway.async_connect(
                    connection_closed_callback=self._on_connection_closed,
                    **connect_info,
                )
                _apply_remote_keepalive(self.gateway, is_remote)

            await self.gateway.async_update()
        except (ScreenLogicConnectionError, ScreenLogicError) as err:
            raise UpdateFailed(str(err)) from err

        return self.gateway.get_data()
