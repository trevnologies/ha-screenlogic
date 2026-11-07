"""Base ScreenLogicEntity definitions."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any

from screenlogicpy import ScreenLogicGateway
from screenlogicpy.const.common import (
    ON_OFF,
    ScreenLogicCommunicationError,
    ScreenLogicError,
)
from screenlogicpy.const.data import ATTR, DEVICE, VALUE
from screenlogicpy.const.msg import CODE
from screenlogicpy.device_const.circuit import FUNCTION, INTERFACE
from screenlogicpy.device_const.system import BODY_TYPE

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import ChildDeviceInfo, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ScreenLogicDataPath
from .coordinator import ScreenlogicDataUpdateCoordinator
from .util import generate_unique_id

_LOGGER = logging.getLogger(__name__)

# Circuit functions that *are* a body's own circuit (the "Pool" or "Spa"
# circuit that turns that body on).
_BODY_FUNCTIONS: dict[int, BODY_TYPE] = {
    FUNCTION.POOL: BODY_TYPE.POOL,
    FUNCTION.SECOND_POOL: BODY_TYPE.POOL,
    FUNCTION.SPA: BODY_TYPE.SPA,
    FUNCTION.SECOND_SPA: BODY_TYPE.SPA,
}

# The controller's UI tab a circuit is shown on. Circuits on the Pool or Spa
# tab (e.g. "Pool Low", "Cleaner", "Air Blower") belong with that body.
_BODY_INTERFACES: dict[int, BODY_TYPE] = {
    INTERFACE.POOL: BODY_TYPE.POOL,
    INTERFACE.SPA: BODY_TYPE.SPA,
}

# screenlogicpy names a pump after the first circuit in its presets, or
# "Default Pump" when none of them match a known circuit.
_UNNAMED_PUMP = "Default Pump"


def body_index_for_type(
    gateway: ScreenLogicGateway, body_type: BODY_TYPE | int
) -> int | None:
    """Return the index of the first body of the given type, if any."""
    for body_index, body_data in (gateway.get_data(DEVICE.BODY) or {}).items():
        if body_data and body_data.get(ATTR.BODY_TYPE) == body_type:
            return body_index
    return None


def body_index_for_circuit(
    gateway: ScreenLogicGateway, circuit_data: dict
) -> int | None:
    """Return the body a circuit belongs to, or None for a system-wide circuit.

    A circuit belongs to a body when it is that body's own circuit (its
    function is Pool or Spa) or when the controller shows it on that body's
    tab (its interface is Pool or Spa). Features, lights and hidden circuits
    stay on the controller device.
    """
    body_type = _BODY_FUNCTIONS.get(circuit_data.get(ATTR.FUNCTION))
    if body_type is None:
        body_type = _BODY_INTERFACES.get(circuit_data.get(ATTR.INTERFACE))
    if body_type is None:
        return None
    return body_index_for_type(gateway, body_type)


def name_within_device(name: str, device_name: str) -> str | None:
    """Return an entity name with its device's name taken off the front.

    Home Assistant shows an entity as "<device> <entity>", so a circuit named
    "Pool Low" on the "Pool" device is named "Low" (shown as "Pool Low"),
    and a circuit that has the device's own name is the device's main
    entity (None, shown as just "Pool").
    """
    stripped = name.strip()
    if stripped.casefold() == device_name.strip().casefold():
        return None
    prefix = f"{device_name.strip()} "
    if stripped.casefold().startswith(prefix.casefold()) and len(stripped) > len(
        prefix
    ):
        return stripped[len(prefix) :].strip()
    return stripped


def pump_name(gateway: ScreenLogicGateway, pump_index: int) -> str:
    """Return the controller's name for a pump, e.g. "Pool Pump"."""
    name = (
        gateway.get_data(DEVICE.PUMP, pump_index, VALUE.STATE, ATTR.NAME) or ""
    ).strip()
    if not name or name == _UNNAMED_PUMP:
        return f"Pump {pump_index + 1}"
    return name


@dataclass(frozen=True, kw_only=True)
class ScreenLogicEntityDescription(EntityDescription):
    """Base class for a ScreenLogic entity description."""

    data_root: ScreenLogicDataPath
    enabled_lambda: Callable[..., bool] | None = None
    # Put the entity on this body's device (Pool or Spa) instead of the
    # controller's, when the system has that body.
    body_type: BODY_TYPE | None = None


class ScreenLogicEntity(CoordinatorEntity[ScreenlogicDataUpdateCoordinator]):
    """Base class for all ScreenLogic entities."""

    entity_description: ScreenLogicEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ScreenlogicDataUpdateCoordinator,
        entity_description: ScreenLogicEntityDescription,
    ) -> None:
        """Initialize of the entity."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._data_key = self.entity_description.key
        self._data_path = (*self.entity_description.data_root, self._data_key)
        mac = self.mac
        self._attr_unique_id = f"{mac}_{generate_unique_id(*self._data_path)}"
        if not entity_description.translation_key:
            self._attr_name = self.entity_data[ATTR.NAME]
        assert mac is not None
        self._attr_device_info: DeviceInfo | ChildDeviceInfo = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            connections={(dr.CONNECTION_NETWORK_MAC, mac)},
            manufacturer="Pentair",
            model=self.gateway.controller_model,
            name=self.gateway.name,
            sw_version=self.gateway.version,
        )
        if entity_description.body_type is not None and (
            body_index := body_index_for_type(
                self.gateway, entity_description.body_type
            )
        ) is not None:
            self._attr_device_info = self._body_device_info(body_index)

    @property
    def mac(self) -> str | None:
        """Mac address."""
        assert self.coordinator.config_entry is not None
        return self.coordinator.config_entry.unique_id

    @property
    def gateway(self) -> ScreenLogicGateway:
        """Return the gateway."""
        return self.coordinator.gateway

    async def _async_refresh(self) -> None:
        """Refresh the data from the gateway."""
        await self.coordinator.async_refresh()
        # Second debounced refresh to catch any secondary
        # changes in the device
        await self.coordinator.async_request_refresh()

    async def _async_refresh_timed(self, now: datetime) -> None:
        """Refresh from a timed called."""
        await self.coordinator.async_request_refresh()

    @property
    def entity_data(self) -> dict:
        """Shortcut to the data for this entity."""
        try:
            return self.gateway.get_data(*self._data_path, strict=True)
        except KeyError as ke:
            raise HomeAssistantError(f"Data not found: {self._data_path}") from ke

    def _body_device_info(self, body_index: int) -> ChildDeviceInfo:
        """Build the device info for a body (Pool or Spa).

        A body is a logical part of the controller, not separate equipment,
        so it is a child device of the controller rather than a device
        connected through it. Child devices take their area from the
        controller unless they are given one of their own.
        """
        mac = self.mac
        assert mac is not None
        return ChildDeviceInfo(
            identifiers={(DOMAIN, f"{mac}_body_{body_index}")},
            parent_device_id=self.coordinator.gateway_device_id,
            name=self.body_name(body_index),
        )

    def body_name(self, body_index: int) -> str:
        """Return the controller's name for a body, e.g. "Pool"."""
        return (
            self.gateway.get_data(DEVICE.BODY, body_index, ATTR.NAME)
            or f"Body {body_index + 1}"
        )

    def _pump_device_info(self, pump_index: int, pump_model: str | None) -> DeviceInfo:
        """Build a DeviceInfo for a pump, split out from the main gateway device.

        Pump diagnostics (GPM/RPM/Watts, running state) are physically
        separate equipment from the gateway/controller diagnostics, so they
        get their own device page via `via_device_id` rather than piling
        everything under one "Diagnostic" list.

        `via_device_id` (the resolved device registry id) replaces the
        deprecated `via_device` identifiers-tuple shortcut, which HA now
        raises on instead of just warning about when it can't cleanly
        attribute the call to an integration frame. The id is resolved
        once in __init__.py's async_setup_entry and handed to us via the
        coordinator, so this stays a plain, order-independent lookup.
        """
        mac = self.mac
        assert mac is not None
        return DeviceInfo(
            identifiers={(DOMAIN, f"{mac}_pump_{pump_index}")},
            via_device_id=self.coordinator.gateway_device_id,
            manufacturer="Pentair",
            model=pump_model or "IntelliFlo Pump",
            name=pump_name(self.gateway, pump_index),
        )


@dataclass(frozen=True, kw_only=True)
class ScreenLogicPushEntityDescription(ScreenLogicEntityDescription):
    """Base class for a ScreenLogic push entity description."""

    subscription_code: CODE


class ScreenLogicPushEntity(ScreenLogicEntity):
    """Base class for all ScreenLogic push entities."""

    entity_description: ScreenLogicPushEntityDescription

    def __init__(
        self,
        coordinator: ScreenlogicDataUpdateCoordinator,
        entity_description: ScreenLogicPushEntityDescription,
    ) -> None:
        """Initialize of the entity."""
        super().__init__(coordinator, entity_description)
        self._subscription_code = entity_description.subscription_code
        self._last_update_success = True

    @callback
    def _async_data_updated(self) -> None:
        """Handle data updates."""
        self._last_update_success = self.coordinator.last_update_success
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            await self.gateway.async_subscribe_client(
                self._async_data_updated,
                self._subscription_code,
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # For push entities, only take updates from the coordinator if availability changes.
        if self.coordinator.last_update_success != self._last_update_success:
            self._async_data_updated()


class ScreenLogicSwitchingEntity(ScreenLogicEntity):
    """Base class for all switchable entities."""

    @property
    def is_on(self) -> bool:
        """Get whether the switch is in on state."""
        return self.entity_data[ATTR.VALUE] == ON_OFF.ON

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Send the ON command."""
        await self._async_set_state(ON_OFF.ON)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Send the OFF command."""
        await self._async_set_state(ON_OFF.OFF)

    async def _async_set_state(self, state: ON_OFF) -> None:
        raise NotImplementedError


class ScreenLogicCircuitEntity(ScreenLogicSwitchingEntity, ScreenLogicPushEntity):
    """Base class for all ScreenLogic circuit switch and light entities."""

    def __init__(
        self,
        coordinator: ScreenlogicDataUpdateCoordinator,
        entity_description: ScreenLogicPushEntityDescription,
    ) -> None:
        """Initialize a circuit, on its body's device when it has one."""
        super().__init__(coordinator, entity_description)
        if (
            body_index := body_index_for_circuit(self.gateway, self.entity_data)
        ) is not None:
            self._attr_device_info = self._body_device_info(body_index)
            self._attr_name = name_within_device(
                self.entity_data[ATTR.NAME], self.body_name(body_index)
            )

    async def _async_set_state(self, state: ON_OFF) -> None:
        try:
            await self.gateway.async_set_circuit(self._data_key, state.value)
        except (ScreenLogicCommunicationError, ScreenLogicError) as sle:
            raise HomeAssistantError(
                f"Failed to set_circuit {self._data_key} {state.value}: {sle.msg}"
            ) from sle
        _LOGGER.debug("Set circuit %s %s", self._data_key, state.value)