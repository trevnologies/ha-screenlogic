"""Support for a ScreenLogic 'sync controller time' button."""

from dataclasses import dataclass
import logging

from screenlogicpy.const.common import ScreenLogicCommunicationError, ScreenLogicError
from screenlogicpy.const.data import DEVICE, GROUP, VALUE

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import ScreenLogicEntity, ScreenLogicEntityDescription
from .types import ScreenLogicConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ScreenLogicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up entry."""
    coordinator = config_entry.runtime_data
    async_add_entities(
        [
            ScreenLogicSyncTimeButton(
                coordinator,
                ScreenLogicButtonDescription(
                    # No single native value backs this entity (it's an
                    # action, not a state) - data_root/key only exist here
                    # to generate a stable unique_id, mirroring the
                    # controller's date/time data this button acts on.
                    data_root=(DEVICE.CONTROLLER, GROUP.DATE_TIME),
                    key=VALUE.TIMESTAMP,
                    translation_key="sync_time",
                    entity_category=EntityCategory.CONFIG,
                ),
            )
        ]
    )


@dataclass(frozen=True, kw_only=True)
class ScreenLogicButtonDescription(
    ButtonEntityDescription, ScreenLogicEntityDescription
):
    """Describes a ScreenLogic button entity."""


class ScreenLogicSyncTimeButton(ScreenLogicEntity, ButtonEntity):
    """Button to sync the controller's clock to this Home Assistant instance.

    The EasyTouch/IntelliTouch controller has no NTP client, so its RTC
    drifts over time with no way to correct it from the panel itself.
    Requested in home-assistant/discussions#4126. screenlogicpy already
    implements the underlying protocol call
    (gateway.async_synchronize_date_time()) - this just exposes it as a
    pressable entity instead of requiring a manual service call.
    """

    entity_description: ScreenLogicButtonDescription

    async def async_press(self) -> None:
        """Set the controller's date/time to this instance's current time."""
        try:
            await self.gateway.async_synchronize_date_time()
        except (ScreenLogicCommunicationError, ScreenLogicError) as sle:
            raise HomeAssistantError(
                f"Failed to sync controller date/time: {sle.msg}"
            ) from sle
        _LOGGER.debug("Synchronized controller date/time")
