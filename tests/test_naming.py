"""Tests for device structure and entity naming.

Loads the integration against a real controller's data (tests/fixtures/
easytouch2_8.json) and checks that each entity lands on the right device and
that Home Assistant composes a name that doesn't repeat the device's name.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, PropertyMock, patch

from awesomeversion import AwesomeVersion
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from screenlogicpy import ScreenLogicGateway

from custom_components.screenlogic.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

# These tests set the integration up, which needs Home Assistant 2026.11 (its
# minimum: child devices, and setup/unload returning None). Until the test
# harness ships a 2026.11 release, an older harness skips them.
if AwesomeVersion(HA_VERSION) < AwesomeVersion("2026.11.0"):
    pytest.skip(
        f"needs Home Assistant 2026.11 or later, harness has {HA_VERSION}",
        allow_module_level=True,
    )

from custom_components.screenlogic.entity import name_within_device  # noqa: E402

MAC = "00:c0:33:aa:bb:cc"
GATEWAY_NAME = "Pentair: AA-BB-CC"
FIXTURE = Path(__file__).parent / "fixtures" / "easytouch2_8.json"


def _int_keys(value: Any) -> Any:
    """Turn the fixture's numeric string keys back into the ints screenlogicpy uses."""
    if isinstance(value, dict):
        return {
            (int(key) if isinstance(key, str) and key.isdigit() else key): _int_keys(
                item
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_int_keys(item) for item in value]
    return value


@pytest.fixture
def gateway_data() -> dict:
    """Controller data from a real EasyTouch2 8."""
    return _int_keys(json.loads(FIXTURE.read_text())["data"])


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A local ScreenLogic config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        title=GATEWAY_NAME,
        data={"ip_address": "192.0.2.10", "port": 80},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def mock_gateway(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway_data: dict
):
    """Serve the fixture data from ScreenLogicGateway for the whole test.

    The entry is unloaded before the patches end, so unloading doesn't try
    to close a real connection.
    """

    async def fake_connect(self: ScreenLogicGateway, *args: Any, **kwargs: Any) -> bool:
        self._name = kwargs.get("name", GATEWAY_NAME)
        self._version = "POOL: 5.2 Build 738.0 Rel"
        self._data = gateway_data
        return True

    with (
        patch(
            "custom_components.screenlogic.async_get_connect_info",
            AsyncMock(return_value={"name": GATEWAY_NAME, "ip": "192.0.2.10", "port": 80}),
        ),
        patch.object(ScreenLogicGateway, "async_connect", fake_connect),
        patch.object(ScreenLogicGateway, "async_update", AsyncMock()),
        patch.object(ScreenLogicGateway, "async_disconnect", AsyncMock()),
        patch.object(
            ScreenLogicGateway, "async_subscribe_client", AsyncMock(return_value=lambda: None)
        ),
        patch.object(
            ScreenLogicGateway, "is_connected", new_callable=PropertyMock, return_value=True
        ),
    ):
        yield
        if config_entry.state is ConfigEntryState.LOADED:
            assert await hass.config_entries.async_unload(config_entry.entry_id)
            await hass.async_block_till_done()


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set the entry up against the mocked gateway."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


def _entity_id(hass: HomeAssistant, domain: str, unique_suffix: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{MAC}_{unique_suffix}"
    )
    assert entity_id, f"no {domain} entity with unique id suffix {unique_suffix}"
    return entity_id


def _shown_name(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.name


def _device(hass: HomeAssistant, entity_id: str) -> dr.AnyDeviceEntry:
    entry = er.async_get(hass).async_get(entity_id)
    assert entry and entry.device_id
    device = dr.async_get(hass).async_get(entry.device_id)
    assert device
    return device


@pytest.mark.parametrize(
    ("name", "device_name", "expected"),
    [
        ("Pool", "Pool", None),
        ("pool", "Pool", None),
        ("Pool Low", "Pool", "Low"),
        ("Cleaner", "Pool", "Cleaner"),
        ("Air Blower", "Spa", "Air Blower"),
        ("Poolside", "Pool", "Poolside"),
        ("Pool ", "Pool", None),
    ],
)
def test_name_within_device(name: str, device_name: str, expected: str | None) -> None:
    """A circuit name loses its body's name, and the body's own circuit has none."""
    assert name_within_device(name, device_name) == expected


async def test_bodies_are_child_devices(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_gateway: None
) -> None:
    """Pool and Spa are child devices of the controller."""
    await _setup(hass, config_entry)
    registry = dr.async_get(hass)

    controller = registry.async_get_device_by_identifier(
        (DOMAIN, MAC), config_entry.entry_id
    )
    assert controller is not None
    assert controller.name == GATEWAY_NAME

    for index, name in ((0, "Pool"), (1, "Spa")):
        body = registry.async_get_child_device_by_identifier(
            (DOMAIN, f"{MAC}_body_{index}"), config_entry.entry_id
        )
        assert isinstance(body, dr.ChildDeviceEntry)
        assert body.name == name
        assert body.parent_device_id == controller.id


async def test_pumps_are_named_by_the_controller(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_gateway: None
) -> None:
    """Pumps are separate equipment connected through the controller."""
    await _setup(hass, config_entry)
    registry = dr.async_get(hass)
    controller = registry.async_get_device_by_identifier(
        (DOMAIN, MAC), config_entry.entry_id
    )
    assert controller is not None

    for index, name in ((0, "Pool Pump"), (1, "Waterfall Pump")):
        pump = registry.async_get_device_by_identifier(
            (DOMAIN, f"{MAC}_pump_{index}"), config_entry.entry_id
        )
        assert isinstance(pump, dr.DeviceEntry)
        assert pump.name == name
        assert pump.via_device_id == controller.id


@pytest.mark.parametrize(
    ("domain", "unique_suffix", "device", "shown"),
    [
        # The body's own circuit is its main entity.
        ("switch", "505", "Pool", "Pool"),
        ("switch", "500", "Spa", "Spa"),
        # Circuits on a body's tab move to that body without repeating its name.
        ("switch", "510", "Pool", "Pool Low"),
        ("switch", "512", "Pool", "Pool Cleaner"),
        ("switch", "501", "Spa", "Spa Air Blower"),
        # Features, lights and hidden circuits stay on the controller.
        ("switch", "503", GATEWAY_NAME, f"{GATEWAY_NAME} Waterfall"),
        ("switch", "511", GATEWAY_NAME, f"{GATEWAY_NAME} Spillway"),
        ("light", "502", GATEWAY_NAME, f"{GATEWAY_NAME} Lights"),
        # Heaters and delays belong to their body.
        ("climate", "0", "Pool", "Pool Heat"),
        ("climate", "1", "Spa", "Spa Heat"),
        ("binary_sensor", "pool_delay", "Pool", "Pool Delay"),
        ("binary_sensor", "spa_delay", "Spa", "Spa Delay"),
        # System-wide sensors stay on the controller.
        ("sensor", "air_temperature", GATEWAY_NAME, f"{GATEWAY_NAME} Air Temperature"),
        ("binary_sensor", "freeze_mode", GATEWAY_NAME, f"{GATEWAY_NAME} Freeze Mode"),
        # Pump entities don't repeat the pump's name.
        ("binary_sensor", "pump_0_state", "Pool Pump", "Pool Pump"),
        ("sensor", "pump_0_watts_now", "Pool Pump", "Pool Pump Watts Now"),
        ("sensor", "pump_0_rpm_now", "Pool Pump", "Pool Pump RPM Now"),
        ("sensor", "pump_1_watts_now", "Waterfall Pump", "Waterfall Pump Watts Now"),
        ("number", "pump_0_preset_2_speed", "Pool Pump", "Pool Pump Pool Low Speed"),
    ],
)
async def test_entity_device_and_name(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_gateway: None,
    domain: str,
    unique_suffix: str,
    device: str,
    shown: str,
) -> None:
    """Each entity is on the right device and its shown name has no repeats."""
    await _setup(hass, config_entry)
    entity_id = _entity_id(hass, domain, unique_suffix)
    assert _device(hass, entity_id).name == device
    assert _shown_name(hass, entity_id) == shown


async def test_existing_entities_move_to_their_body(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_gateway: None
) -> None:
    """Upgrading moves an existing entity to its body and keeps its entity ID."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    controller = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, MAC)},
        connections={(dr.CONNECTION_NETWORK_MAC, MAC)},
        name="Backyard Pool",
    )
    old = entity_registry.async_get_or_create(
        "switch",
        DOMAIN,
        f"{MAC}_505",
        config_entry=config_entry,
        device_id=controller.id,
        suggested_object_id="backyard_pool_pool",
    )
    assert old.entity_id == "switch.backyard_pool_pool"

    await _setup(hass, config_entry)

    moved = entity_registry.async_get(old.entity_id)
    assert moved is not None
    pool = device_registry.async_get(moved.device_id)
    assert isinstance(pool, dr.ChildDeviceEntry)
    assert pool.name == "Pool"
    assert _shown_name(hass, old.entity_id) == "Pool"
