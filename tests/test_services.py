"""Tests for the ScreenLogic services (ported from core #180161 / #182112)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from screenlogicpy.device_const.system import EQUIPMENT_FLAG

from custom_components.screenlogic.const import (
    ATTR_COLOR_MODE,
    ATTR_CONFIG_ENTRY,
    ATTR_RUNTIME,
    DOMAIN,
    SERVICE_SET_COLOR_MODE,
    SERVICE_START_SUPER_CHLORINATION,
    SERVICE_STOP_SUPER_CHLORINATION,
    SUPPORTED_COLOR_MODES,
)
from custom_components.screenlogic.services import async_setup_services
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError


def _coordinator(chlorinator: bool = True) -> MagicMock:
    coordinator = MagicMock()
    coordinator.gateway.name = "Pentair: AA-BB-CC"
    coordinator.gateway.equipment_flags = (
        EQUIPMENT_FLAG.CHLORINATOR if chlorinator else EQUIPMENT_FLAG(0)
    )
    coordinator.gateway.async_set_color_lights = AsyncMock()
    coordinator.gateway.async_set_scg_config = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


@pytest.fixture
def loaded_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Pool", data={})
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = _coordinator()
    async_setup_services(hass)
    return entry


async def test_set_color_mode(hass: HomeAssistant, loaded_entry) -> None:
    mode = next(iter(SUPPORTED_COLOR_MODES))
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_COLOR_MODE,
        {ATTR_CONFIG_ENTRY: loaded_entry.entry_id, ATTR_COLOR_MODE: mode},
        blocking=True,
    )
    gateway = loaded_entry.runtime_data.gateway
    gateway.async_set_color_lights.assert_awaited_once_with(SUPPORTED_COLOR_MODES[mode])
    loaded_entry.runtime_data.async_request_refresh.assert_awaited_once()


async def test_super_chlorination_start_stop(hass: HomeAssistant, loaded_entry) -> None:
    gateway = loaded_entry.runtime_data.gateway
    await hass.services.async_call(
        DOMAIN,
        SERVICE_START_SUPER_CHLORINATION,
        {ATTR_CONFIG_ENTRY: loaded_entry.entry_id, ATTR_RUNTIME: 12},
        blocking=True,
    )
    gateway.async_set_scg_config.assert_awaited_with(
        super_chlor_timer=12, super_chlorinate=True
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_STOP_SUPER_CHLORINATION,
        {ATTR_CONFIG_ENTRY: loaded_entry.entry_id},
        blocking=True,
    )
    gateway.async_set_scg_config.assert_awaited_with(
        super_chlor_timer=None, super_chlorinate=False
    )


async def test_runtime_default_and_clamp(hass: HomeAssistant, loaded_entry) -> None:
    gateway = loaded_entry.runtime_data.gateway
    await hass.services.async_call(
        DOMAIN,
        SERVICE_START_SUPER_CHLORINATION,
        {ATTR_CONFIG_ENTRY: loaded_entry.entry_id},
        blocking=True,
    )
    gateway.async_set_scg_config.assert_awaited_with(
        super_chlor_timer=24, super_chlorinate=True
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_START_SUPER_CHLORINATION,
        {ATTR_CONFIG_ENTRY: loaded_entry.entry_id, ATTR_RUNTIME: 500},
        blocking=True,
    )
    gateway.async_set_scg_config.assert_awaited_with(
        super_chlor_timer=72, super_chlorinate=True
    )


async def test_no_chlorinator(hass: HomeAssistant, loaded_entry) -> None:
    loaded_entry.runtime_data = _coordinator(chlorinator=False)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_START_SUPER_CHLORINATION,
            {ATTR_CONFIG_ENTRY: loaded_entry.entry_id},
            blocking=True,
        )


async def test_unknown_entry(hass: HomeAssistant, loaded_entry) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_STOP_SUPER_CHLORINATION,
            {ATTR_CONFIG_ENTRY: "does_not_exist"},
            blocking=True,
        )


async def test_entry_not_loaded(hass: HomeAssistant, loaded_entry) -> None:
    loaded_entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_STOP_SUPER_CHLORINATION,
            {ATTR_CONFIG_ENTRY: loaded_entry.entry_id},
            blocking=True,
        )


async def test_wrong_domain_entry(hass: HomeAssistant, loaded_entry) -> None:
    other = MockConfigEntry(domain="sun", title="Sun", data={})
    other.add_to_hass(hass)
    other.mock_state(hass, ConfigEntryState.LOADED)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_STOP_SUPER_CHLORINATION,
            {ATTR_CONFIG_ENTRY: other.entry_id},
            blocking=True,
        )
