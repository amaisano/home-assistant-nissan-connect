"""Local mynissan.refresh service (asks the car to publish fresh data)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mynissan.const import DOMAIN
from custom_components.mynissan.models import NissanRuntimeData

VIN = "JN1TESTVIN0000001"


def _client(success=True):
    result = SimpleNamespace(is_success=success, status=SimpleNamespace(value="FAILED") if not success else None)
    return SimpleNamespace(
        async_refresh_battery_status=AsyncMock(return_value=True),
        async_refresh_climate_status=AsyncMock(return_value=True),
        async_refresh_vehicle_status=AsyncMock(return_value="req-status"),
        async_locate_vehicle=AsyncMock(return_value="req-locate"),
        async_wait_for_service_request=AsyncMock(return_value=result),
    )


async def _setup(hass, client):
    assert await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    coordinator = SimpleNamespace(async_request_refresh=AsyncMock())
    entry.runtime_data = NissanRuntimeData(
        client=client, vehicles=(SimpleNamespace(vin=VIN),), capabilities={}, coordinator=coordinator
    )
    return coordinator


async def test_battery_and_climate(hass):
    client = _client()
    coord = await _setup(hass, client)
    await hass.services.async_call(DOMAIN, "refresh", {"kinds": ["battery", "climate"]}, blocking=True)
    client.async_refresh_battery_status.assert_awaited_once_with(VIN)
    client.async_refresh_climate_status.assert_awaited_once_with(VIN)
    client.async_refresh_vehicle_status.assert_not_awaited()
    coord.async_request_refresh.assert_awaited_once()


async def test_default_is_status_and_waits(hass):
    client = _client()
    await _setup(hass, client)
    await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    client.async_refresh_vehicle_status.assert_awaited_once_with(VIN)
    client.async_wait_for_service_request.assert_awaited_once_with(VIN, "req-status")


async def test_location_failure_raises_readable_error(hass):
    client = _client(success=False)
    coord = await _setup(hass, client)
    with pytest.raises(HomeAssistantError, match="location refresh ended with status FAILED"):
        await hass.services.async_call(DOMAIN, "refresh", {"kinds": "location"}, blocking=True)
    client.async_locate_vehicle.assert_awaited_once_with(VIN)
    coord.async_request_refresh.assert_awaited_once()  # still refreshes what it can


async def test_not_loaded(hass):
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)


async def test_bad_kind_rejected(hass):
    await _setup(hass, _client())
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(DOMAIN, "refresh", {"kinds": ["horn"]}, blocking=True)
