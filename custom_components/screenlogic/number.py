"""Support for a ScreenLogic number entity."""

from dataclasses import dataclass
import logging
import struct

from screenlogicpy.const.common import (
    ScreenLogicCommunicationError,
    ScreenLogicError,
    ScreenLogicResponseError,
)
from screenlogicpy.const.data import ATTR, DEVICE, GROUP, VALUE
from screenlogicpy.const.msg import CODE
from screenlogicpy.device_const.pump import PUMP_TYPE
from screenlogicpy.device_const.system import EQUIPMENT_FLAG
from screenlogicpy.requests.protocol import ScreenLogicProtocol
from screenlogicpy.requests.request import async_make_request

from homeassistant.components.number import (
    DOMAIN as NUMBER_DOMAIN,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ScreenlogicDataUpdateCoordinator
from .entity import (
    ScreenLogicEntity,
    ScreenLogicEntityDescription,
    ScreenLogicPushEntity,
    ScreenLogicPushEntityDescription,
)
from .types import ScreenLogicConfigEntry
from .util import cleanup_excluded_entity, get_ha_unit

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

# --------------------------------------------------------------------------
# Pump preset speed - NOT YET IN screenlogicpy. Message code and payload
# structure confirmed against parnic/node-screenlogic's setPumpFlowAsync
# (PumpMessage.ts: ResponseIDs.SetPumpSpeed = 12587; request = response - 1,
# same convention as every other ScreenLogic message pair). Official
# Pentair IntelliFlo range per the VS/i1 installation manuals: 450-3450 RPM;
# VSF flow range per spec sheet: 20-140 GPM.
#
# TODO: contribute this to screenlogicpy as gateway.async_set_pump_speed(),
# then delete this block and call that instead.
SETPUMPSPEED_QUERY = 12586
PUMP_RPM_MIN, PUMP_RPM_MAX, PUMP_RPM_STEP = 450, 3450, 10
PUMP_GPM_MIN, PUMP_GPM_MAX, PUMP_GPM_STEP = 20, 140, 1


async def async_request_set_pump_speed(
    protocol: ScreenLogicProtocol,
    pump_id: int,
    preset_index: int,
    speed: int,
    is_rpm: bool,
    max_retries: int | None = None,
) -> None:
    """Set one pump preset's target speed (RPM or GPM)."""
    if (
        response := await async_make_request(
            protocol,
            SETPUMPSPEED_QUERY,
            struct.pack(
                "<IIIII", 0, pump_id, preset_index, int(speed), 1 if is_rpm else 0
            ),
            max_retries,
        )
    ) != b"":
        raise ScreenLogicResponseError(
            f"Set pump speed failed. Unexpected response: {response}"
        )


# --------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ScreenLogicNumberDescription(
    NumberEntityDescription,
    ScreenLogicEntityDescription,
):
    """Describes a ScreenLogic number entity."""


@dataclass(frozen=True, kw_only=True)
class ScreenLogicPushNumberDescription(
    ScreenLogicNumberDescription,
    ScreenLogicPushEntityDescription,
):
    """Describes a ScreenLogic push number entity."""


SUPPORTED_INTELLICHEM_NUMBERS = [
    ScreenLogicPushNumberDescription(
        subscription_code=CODE.CHEMISTRY_CHANGED,
        data_root=(DEVICE.INTELLICHEM, GROUP.CONFIGURATION),
        key=VALUE.CALCIUM_HARDNESS,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        translation_key="calcium_hardness",
    ),
    ScreenLogicPushNumberDescription(
        subscription_code=CODE.CHEMISTRY_CHANGED,
        data_root=(DEVICE.INTELLICHEM, GROUP.CONFIGURATION),
        key=VALUE.CYA,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        translation_key="cya",
    ),
    ScreenLogicPushNumberDescription(
        subscription_code=CODE.CHEMISTRY_CHANGED,
        data_root=(DEVICE.INTELLICHEM, GROUP.CONFIGURATION),
        key=VALUE.TOTAL_ALKALINITY,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        translation_key="total_alkalinity",
    ),
    ScreenLogicPushNumberDescription(
        subscription_code=CODE.CHEMISTRY_CHANGED,
        data_root=(DEVICE.INTELLICHEM, GROUP.CONFIGURATION),
        key=VALUE.SALT_TDS_PPM,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        translation_key="salt_tds_ppm",
    ),
]

SUPPORTED_SCG_NUMBERS = [
    ScreenLogicNumberDescription(
        data_root=(DEVICE.SCG, GROUP.CONFIGURATION),
        key=VALUE.POOL_SETPOINT,
        entity_category=EntityCategory.CONFIG,
        translation_key="pool_setpoint",
    ),
    ScreenLogicNumberDescription(
        data_root=(DEVICE.SCG, GROUP.CONFIGURATION),
        key=VALUE.SPA_SETPOINT,
        entity_category=EntityCategory.CONFIG,
        translation_key="spa_setpoint",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ScreenLogicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up entry."""
    entities: list[ScreenLogicNumber] = []
    coordinator = config_entry.runtime_data
    gateway = coordinator.gateway

    for chem_number_description in SUPPORTED_INTELLICHEM_NUMBERS:
        chem_number_data_path = (
            *chem_number_description.data_root,
            chem_number_description.key,
        )
        if EQUIPMENT_FLAG.INTELLICHEM not in gateway.equipment_flags:
            cleanup_excluded_entity(coordinator, NUMBER_DOMAIN, chem_number_data_path)
            continue
        if gateway.get_data(*chem_number_data_path):
            entities.append(
                ScreenLogicChemistryNumber(coordinator, chem_number_description)
            )

    for scg_number_description in SUPPORTED_SCG_NUMBERS:
        scg_number_data_path = (
            *scg_number_description.data_root,
            scg_number_description.key,
        )
        if EQUIPMENT_FLAG.CHLORINATOR not in gateway.equipment_flags:
            cleanup_excluded_entity(coordinator, NUMBER_DOMAIN, scg_number_data_path)
            continue
        if gateway.get_data(*scg_number_data_path):
            entities.append(ScreenLogicSCGNumber(coordinator, scg_number_description))

    entities.extend(_build_pump_speed_entities(coordinator))

    async_add_entities(entities)


def _resolve_circuit_name(gateway, device_id: int) -> str:
    """Look up a circuit's display name from its device_id."""
    for circuit_data in gateway.get_data(DEVICE.CIRCUIT).values():
        if circuit_data and circuit_data.get(ATTR.DEVICE_ID) == device_id:
            return circuit_data[ATTR.NAME]
    return f"Circuit {device_id}"


def _build_pump_speed_entities(
    coordinator: ScreenlogicDataUpdateCoordinator,
) -> list["ScreenLogicPumpSpeedNumber"]:
    """Build pump preset speed number entities.

    Kept as its own function (rather than inlined into async_setup_entry)
    only so the pump-speed block - marked for removal once this lands in
    screenlogicpy - stays easy to find and delete as one unit later.
    """
    gateway = coordinator.gateway
    entities: list[ScreenLogicPumpSpeedNumber] = []

    for pump_index, pump_data in gateway.get_data(DEVICE.PUMP).items():
        if not pump_data or not pump_data.get(VALUE.DATA):
            continue
        pump_type = pump_data.get(VALUE.TYPE)
        for preset_index, preset in pump_data.get(VALUE.PRESET, {}).items():
            device_id = preset.get(ATTR.DEVICE_ID)
            if not device_id:
                continue
            is_rpm = preset.get(ATTR.IS_RPM, True)
            circuit_name = _resolve_circuit_name(gateway, device_id)
            entities.append(
                ScreenLogicPumpSpeedNumber(
                    coordinator,
                    ScreenLogicNumberDescription(
                        data_root=(DEVICE.PUMP, pump_index, VALUE.PRESET),
                        key=preset_index,
                        entity_category=EntityCategory.CONFIG,
                        mode=NumberMode.BOX,
                        native_min_value=(
                            PUMP_RPM_MIN if is_rpm else PUMP_GPM_MIN
                        ),
                        native_max_value=(
                            PUMP_RPM_MAX if is_rpm else PUMP_GPM_MAX
                        ),
                        native_step=(
                            PUMP_RPM_STEP if is_rpm else PUMP_GPM_STEP
                        ),
                        native_unit_of_measurement="rpm" if is_rpm else "gpm",
                        translation_key="pump_preset_speed",
                        translation_placeholders={"circuit": circuit_name},
                    ),
                    pump_index,
                    preset_index,
                    pump_type,
                )
            )

    return entities


class ScreenLogicNumber(ScreenLogicEntity, NumberEntity):
    """Base class to represent a ScreenLogic Number entity."""

    entity_description: ScreenLogicNumberDescription

    def __init__(
        self,
        coordinator: ScreenlogicDataUpdateCoordinator,
        entity_description: ScreenLogicNumberDescription,
    ) -> None:
        """Initialize a ScreenLogic number entity."""
        super().__init__(coordinator, entity_description)

        self._attr_native_unit_of_measurement = get_ha_unit(
            self.entity_data.get(ATTR.UNIT)
        )
        if entity_description.native_max_value is None and isinstance(
            max_val := self.entity_data.get(ATTR.MAX_SETPOINT), int | float
        ):
            self._attr_native_max_value = max_val
        if entity_description.native_min_value is None and isinstance(
            min_val := self.entity_data.get(ATTR.MIN_SETPOINT), int | float
        ):
            self._attr_native_min_value = min_val
        if entity_description.native_step is None and isinstance(
            step := self.entity_data.get(ATTR.STEP), int | float
        ):
            self._attr_native_step = step

    @property
    def native_value(self) -> float:
        """Return the current value."""
        return self.entity_data[ATTR.VALUE]

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        raise NotImplementedError


class ScreenLogicPushNumber(ScreenLogicPushEntity, ScreenLogicNumber):
    """Base class to preresent a ScreenLogic Push Number entity."""

    entity_description: ScreenLogicPushNumberDescription


class ScreenLogicChemistryNumber(ScreenLogicPushNumber):
    """Class to represent a ScreenLogic Chemistry Number entity."""

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""

        # Current API requires int values for the currently supported numbers.
        value = int(value)

        try:
            await self.gateway.async_set_chem_data(**{self._data_key: value})
        except (ScreenLogicCommunicationError, ScreenLogicError) as sle:
            raise HomeAssistantError(
                f"Failed to set '{self._data_key}' to {value}: {sle.msg}"
            ) from sle
        _LOGGER.debug("Set '%s' to %s", self._data_key, value)
        await self._async_refresh()


class ScreenLogicSCGNumber(ScreenLogicNumber):
    """Class to represent a ScreenLoigic SCG Number entity."""

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""

        # Current API requires int values for the currently supported numbers.
        value = int(value)

        try:
            await self.gateway.async_set_scg_config(**{self._data_key: value})
        except (ScreenLogicCommunicationError, ScreenLogicError) as sle:
            raise HomeAssistantError(
                f"Failed to set '{self._data_key}' to {value}: {sle.msg}"
            ) from sle
        _LOGGER.debug("Set '%s' to %s", self._data_key, value)
        await self._async_refresh()


class ScreenLogicPumpSpeedNumber(ScreenLogicNumber):
    """Set one pump preset's target speed (RPM or GPM).

    Not currently supported by screenlogicpy - see the SETPUMPSPEED_QUERY
    block near the top of this file for details and the upstream TODO.
    Behaves like the SCG setpoint numbers above: type or drag a value
    directly, same UX as the heater/SCG setpoint entities, rather than
    picking from a fixed list of presets.
    """

    def __init__(
        self,
        coordinator: ScreenlogicDataUpdateCoordinator,
        entity_description: ScreenLogicNumberDescription,
        pump_index: int,
        preset_index: int,
        pump_type: int | None,
    ) -> None:
        """Initialize of the entity."""
        super().__init__(coordinator, entity_description)
        self._pump_index = pump_index
        self._preset_index = preset_index
        self._attr_device_info = self._pump_device_info(
            pump_index, PUMP_TYPE(pump_type).title if pump_type is not None else None
        )
        # ScreenLogicNumber.__init__ unconditionally overwrites this from
        # ATTR.UNIT on entity_data (absent here, unlike the min/max/step
        # fields which correctly defer to the description if already set)
        # - restore the description's value explicitly.
        self._attr_native_unit_of_measurement = (
            entity_description.native_unit_of_measurement
        )

    @property
    def native_value(self) -> float:
        """Current target speed for this preset."""
        return self.entity_data[ATTR.SETPOINT]

    async def async_set_native_value(self, value: float) -> None:
        """Set this preset's target speed."""
        is_rpm = self.entity_data[ATTR.IS_RPM]
        try:
            await self.gateway._async_connected_request(  # noqa: SLF001
                async_request_set_pump_speed,
                self._pump_index,
                self._preset_index,
                value,
                is_rpm,
                reconnect_delay=1,
            )
        except (ScreenLogicCommunicationError, ScreenLogicError) as sle:
            raise HomeAssistantError(f"Failed to set pump speed: {sle.msg}") from sle
        _LOGGER.debug(
            "Set pump %s preset %s speed to %s",
            self._pump_index,
            self._preset_index,
            value,
        )
        await self._async_refresh()