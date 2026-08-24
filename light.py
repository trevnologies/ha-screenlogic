"""Support for a ScreenLogic light 'circuit' switch."""

from dataclasses import dataclass
import logging
from typing import Any

from screenlogicpy.const.common import ScreenLogicCommunicationError, ScreenLogicError
from screenlogicpy.const.data import ATTR, DEVICE, GROUP
from screenlogicpy.const.msg import CODE
from screenlogicpy.device_const.circuit import GENERIC_CIRCUIT_NAMES, INTERFACE
from screenlogicpy.device_const.system import COLOR_MODE, EQUIPMENT_FLAG

from homeassistant.components.light import (
    ColorMode,
    LightEntity,
    LightEntityDescription,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import LIGHT_CIRCUIT_FUNCTIONS
from .entity import ScreenLogicCircuitEntity, ScreenLogicPushEntityDescription
from .types import ScreenLogicConfigEntry

_LOGGER = logging.getLogger(__name__)

# Named light "shows" a user can select. Excludes the utility/one-shot
# commands (ALL_OFF, ALL_ON, SAVE, RECALL, NEXT_MODE, RESET, HOLD) which
# aren't really "pick and stay" effects.
COLOR_MODE_EFFECTS = (
    COLOR_MODE.COLOR_SET,
    COLOR_MODE.COLOR_SYNC,
    COLOR_MODE.COLOR_SWIM,
    COLOR_MODE.PARTY,
    COLOR_MODE.ROMANCE,
    COLOR_MODE.CARIBBEAN,
    COLOR_MODE.AMERICAN,
    COLOR_MODE.SUNSET,
    COLOR_MODE.ROYAL,
    COLOR_MODE.BLUE,
    COLOR_MODE.GREEN,
    COLOR_MODE.RED,
    COLOR_MODE.WHITE,
    COLOR_MODE.MAGENTA,
)

EFFECT_TO_COLOR_MODE = {mode.title: mode for mode in COLOR_MODE_EFFECTS}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ScreenLogicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up entry."""
    entities: list[ScreenLogicLight] = []
    coordinator = config_entry.runtime_data
    gateway = coordinator.gateway
    supports_color = EQUIPMENT_FLAG.INTELLIBRITE in gateway.equipment_flags
    for circuit_index, circuit_data in gateway.get_data(DEVICE.CIRCUIT).items():
        if (
            not circuit_data
            or ((circuit_function := circuit_data.get(ATTR.FUNCTION)) is None)
            or circuit_function not in LIGHT_CIRCUIT_FUNCTIONS
        ):
            continue
        circuit_name = circuit_data[ATTR.NAME]
        circuit_interface = INTERFACE(circuit_data[ATTR.INTERFACE])
        light_description = ScreenLogicLightDescription(
            subscription_code=CODE.STATUS_CHANGED,
            data_root=(DEVICE.CIRCUIT,),
            key=circuit_index,
            entity_registry_enabled_default=(
                circuit_name not in GENERIC_CIRCUIT_NAMES
                and circuit_interface != INTERFACE.DONT_SHOW
            ),
        )
        entities.append(
            ScreenLogicColorLight(coordinator, light_description)
            if supports_color
            else ScreenLogicLight(coordinator, light_description)
        )

    async_add_entities(entities)


@dataclass(frozen=True, kw_only=True)
class ScreenLogicLightDescription(
    LightEntityDescription, ScreenLogicPushEntityDescription
):
    """Describes a ScreenLogic light entity."""


class ScreenLogicLight(ScreenLogicCircuitEntity, LightEntity):
    """Class to represent a ScreenLogic Light."""

    entity_description: ScreenLogicLightDescription
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}


class ScreenLogicColorLight(ScreenLogicLight):
    """ScreenLogic light with IntelliBrite/ColorLogic show support.

    Only used when the pool equipment set reports EQUIPMENT_FLAG.INTELLIBRITE.
    These lights don't support arbitrary RGB - the gateway instead exposes a
    fixed set of named "shows"/colors sent via a single all-lights command
    (there's no per-light addressing), so this is modeled as EFFECT rather
    than a color mode.
    """

    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = list(EFFECT_TO_COLOR_MODE)

    @property
    def effect(self) -> str | None:
        """Return the current light show, if known.

        The gateway only reports color-mode changes while one is actively
        transitioning (via GROUP.COLOR_LIGHTS push updates), not a durable
        "current show" state, so this is best-effort and may read back None
        between updates.
        """
        color_state = self.gateway.get_data(DEVICE.CONTROLLER, GROUP.COLOR_LIGHTS)
        if not color_state:
            return None
        try:
            mode = COLOR_MODE(color_state.get(ATTR.COLOR_MODE))
        except ValueError:
            return None
        return mode.title if mode in COLOR_MODE_EFFECTS else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light, optionally selecting a show/color."""
        if not self.is_on:
            await super().async_turn_on(**kwargs)
        if (effect := kwargs.get("effect")) is not None:
            await self._async_set_color_mode(effect)

    async def _async_set_color_mode(self, effect: str) -> None:
        color_mode = EFFECT_TO_COLOR_MODE.get(effect)
        if color_mode is None:
            raise HomeAssistantError(f"Unknown light effect: {effect}")
        try:
            await self.gateway.async_set_color_lights(color_mode.value)
        except (ScreenLogicCommunicationError, ScreenLogicError) as sle:
            raise HomeAssistantError(
                f"Failed to set light color mode {color_mode.name}: {sle.msg}"
            ) from sle
        _LOGGER.debug("Set color lights %s", color_mode.name)
        await self._async_refresh()
