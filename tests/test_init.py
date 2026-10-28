"""Tests for MyNISSAN config entry setup."""

from collections.abc import Callable
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_EMAIL,
    PERCENTAGE,
    STATE_OFF,
    STATE_ON,
    Platform,
    UnitOfLength,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pynissan import (
    AccessoryCapability,
    AuthenticationError,
    BatteryStatus,
    ClimateStatus,
    DistanceReading,
    HvacTemperatureCapabilities,
    NetworkError,
    NissanError,
    ServiceCapability,
    TemperatureReading,
    Tokens,
    Vehicle,
    VehicleAccessoriesDetails,
    VehicleCapabilities,
    VehicleLocation,
    VehicleStatus,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mynissan import async_setup_entry
from custom_components.mynissan.const import (
    CONF_AUTH_PROFILE,
    CONF_COUNTRY,
    CONF_OAUTH_DEVICE_ID,
    CONF_TOKENS,
    DOMAIN,
    MOBILE_AUTH_PROFILE,
)
from custom_components.mynissan.coordinator import NissanVehicleData
from custom_components.mynissan.sensor import (
    _climate_temperature,
    _climate_temperature_unit,
)

VEHICLE = Vehicle("JN1TESTVIN0000001", "2025", "ARIYA", None, "Family Ariya", None, None, None)
VEHICLE_STATUS = VehicleStatus(
    vin=VEHICLE.vin,
    vehicle_type="ElectricAVK2Vehicle",
    battery=BatteryStatus(
        level=73,
        is_plugged_in=True,
        is_charging=False,
        remaining_charge_time=42,
        remaining_mileage=DistanceReading(181, "KILOMETER"),
    ),
    climate=ClimateStatus("OFF", TemperatureReading(55.0, "CELSIUS")),
    doors=None,
    fuel_range=None,
    mileage=None,
    tire_pressure=None,
    maintenance_indicators=(),
)
VEHICLE_LOCATION = VehicleLocation(VEHICLE.vin, 32.7157, -117.1611, None)
VEHICLE_CAPABILITIES = VehicleCapabilities(
    vin=VEHICLE.vin,
    telematics_program="NISSAN_CONNECT",
    enrollment_status="ENROLLED",
    services=(ServiceCapability("REMOTE_CLIMATE_CONTROL", True, True),),
    accessories_details=VehicleAccessoriesDetails(
        seat_heater=None,
        steering_heat=AccessoryCapability(True),
        sun_roof=None,
        window_status=None,
        way_point=None,
        hvac_temperatures=HvacTemperatureCapabilities(
            unit="CELSIUS",
            default=22.0,
            minimum=16.0,
            maximum=30.0,
            resolution=0.5,
        ),
    ),
)


def test_reported_cabin_temperature_is_available() -> None:
    """A reported cabin temperature is exposed with its native unit."""
    status = VehicleStatus(
        vin=VEHICLE.vin,
        vehicle_type="ElectricAVK2Vehicle",
        battery=None,
        climate=ClimateStatus("ON", TemperatureReading(22.0, "CELSIUS")),
        doors=None,
        fuel_range=None,
        mileage=None,
        tire_pressure=None,
        maintenance_indicators=(),
    )

    assert _climate_temperature(status) == 22.0
    assert _climate_temperature_unit(status) == UnitOfTemperature.CELSIUS


async def test_setup_registers_vehicle_and_persists_refreshed_tokens(
    hass: HomeAssistant,
) -> None:
    """Setup creates runtime data, a device, and a working token listener."""
    entry = _entry()
    entry.add_to_hass(hass)
    client = MagicMock()
    client.async_get_vehicles = AsyncMock(return_value=(VEHICLE,))
    client.async_get_vehicle_capabilities = AsyncMock(return_value=VEHICLE_CAPABILITIES)
    client.async_get_vehicle_status = AsyncMock(return_value=VEHICLE_STATUS)
    client.async_get_vehicle_location = AsyncMock(return_value=VEHICLE_LOCATION)
    token_listener: Callable[[Tokens], None] | None = None

    def create_client(_hass: HomeAssistant, **kwargs: object) -> MagicMock:
        nonlocal token_listener
        token_listener = kwargs["token_listener"]  # type: ignore[assignment]
        return client

    with patch(
        "custom_components.mynissan.create_client",
        side_effect=create_client,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.client is client
    assert entry.runtime_data.vehicles == (VEHICLE,)
    assert entry.runtime_data.coordinator.data == {
        VEHICLE.vin: NissanVehicleData(VEHICLE_STATUS, VEHICLE_LOCATION)
    }

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, VEHICLE.vin), entry.entry_id
    )
    assert device is not None
    assert device.name == "Family Ariya"
    assert device.manufacturer == "Nissan"
    assert device.model == "ARIYA"
    assert device.serial_number == VEHICLE.vin

    battery_level = _entity_state(hass, Platform.SENSOR, "battery_level")
    assert battery_level.state == "73"
    assert battery_level.attributes["unit_of_measurement"] == PERCENTAGE

    vehicle_range = _entity_state(hass, Platform.SENSOR, "range")
    assert vehicle_range.state == "181"
    assert vehicle_range.attributes["unit_of_measurement"] == UnitOfLength.KILOMETERS

    climate_status = _entity_state(hass, Platform.SENSOR, "climate_status")
    assert climate_status.state == "OFF"

    climate_temperature = _entity_state(hass, Platform.SENSOR, "climate_temperature")
    assert climate_temperature.state == "55.0"
    assert climate_temperature.attributes["unit_of_measurement"] == UnitOfTemperature.CELSIUS

    climate_control = _entity_state(hass, Platform.CLIMATE, "climate_control")
    assert climate_control.state == "off"
    assert climate_control.attributes["temperature"] == 22.0
    assert climate_control.attributes["current_temperature"] == 55.0

    location = _entity_state(hass, Platform.DEVICE_TRACKER, "location")
    assert location.attributes["latitude"] == 32.7157
    assert location.attributes["longitude"] == -117.1611

    charging = _entity_state(hass, Platform.BINARY_SENSOR, "charging")
    assert charging.state == STATE_OFF

    plugged_in = _entity_state(hass, Platform.BINARY_SENSOR, "plugged_in")
    assert plugged_in.state == STATE_ON

    assert token_listener is not None
    token_listener(Tokens("new-access", "new-refresh", "new-id"))
    assert entry.data[CONF_TOKENS] == {
        "access_token": "new-access",
        "refresh_token": "new-refresh",
        "id_token": "new-id",
    }

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert _entry_state(entry) is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize(
    ("error", "expected_exception"),
    [
        (AuthenticationError(401, "Unauthorized"), ConfigEntryAuthFailed),
        (NetworkError(), ConfigEntryNotReady),
        (NissanError(), ConfigEntryNotReady),
    ],
)
async def test_setup_translates_client_errors(
    hass: HomeAssistant,
    error: NissanError,
    expected_exception: type[Exception],
) -> None:
    """Setup translates SDK failures to Home Assistant entry errors."""
    entry = _entry()
    entry.add_to_hass(hass)
    client = MagicMock()
    client.async_get_vehicles = AsyncMock(side_effect=error)

    with (
        patch("custom_components.mynissan.create_client", return_value=client),
        pytest.raises(expected_exception),
    ):
        await async_setup_entry(hass, entry)


async def test_setup_retries_capability_response_errors(hass: HomeAssistant) -> None:
    """A temporary capability response failure leaves the entry retryable."""
    entry = _entry()
    entry.add_to_hass(hass)
    client = MagicMock()
    client.async_get_vehicles = AsyncMock(return_value=(VEHICLE,))
    client.async_get_vehicle_capabilities = AsyncMock(side_effect=NissanError())

    with (
        patch("custom_components.mynissan.create_client", return_value=client),
        pytest.raises(ConfigEntryNotReady),
    ):
        await async_setup_entry(hass, entry)


async def test_setup_rejects_account_without_vehicles(hass: HomeAssistant) -> None:
    """Setup fails clearly when the account no longer contains vehicles."""
    entry = _entry()
    entry.add_to_hass(hass)
    client = MagicMock()
    client.async_get_vehicles = AsyncMock(return_value=())

    with (
        patch("custom_components.mynissan.create_client", return_value=client),
        pytest.raises(ConfigEntryError),
    ):
        await async_setup_entry(hass, entry)


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="US:driver@example.com",
        title="driver@example.com",
        data={
            CONF_AUTH_PROFILE: MOBILE_AUTH_PROFILE,
            CONF_COUNTRY: "US",
            CONF_EMAIL: "driver@example.com",
            CONF_OAUTH_DEVICE_ID: "oauth-device-id",
            CONF_TOKENS: {
                "access_token": "access",
                "refresh_token": "refresh",
                "id_token": "id",
            },
        },
    )


def _entry_state(entry: MockConfigEntry) -> ConfigEntryState:
    return cast(ConfigEntryState, entry.state)


def _entity_state(hass: HomeAssistant, platform: Platform, key: str) -> State:
    entity_id = er.async_get(hass).async_get_entity_id(
        platform,
        DOMAIN,
        f"{VEHICLE.vin}_{key}",
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    return state
