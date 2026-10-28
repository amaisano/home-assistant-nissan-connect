"""MyNISSAN integration for Home Assistant."""

import asyncio
import logging
from collections.abc import Mapping
from typing import cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
import voluptuous as vol
from pynissan import AuthenticationError, NetworkError, NissanError, Tokens, Vehicle

from .api import create_client, tokens_from_data, tokens_to_data
from .const import (
    CONF_AUTH_PROFILE,
    CONF_COUNTRY,
    CONF_OAUTH_DEVICE_ID,
    CONF_TOKENS,
    DOMAIN,
    MANUFACTURER,
    MOBILE_AUTH_PROFILE,
    country_from_value,
)
from .coordinator import NissanDataUpdateCoordinator
from .models import NissanConfigData, NissanConfigEntry, NissanRuntimeData

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LOGGER = logging.getLogger(__name__)

# Local addition (not upstream): ask the car to publish fresh data, which the
# coordinator alone never does (it only reads Nissan's cloud cache).
SERVICE_REFRESH = "refresh"
ATTR_KINDS = "kinds"
REFRESH_KINDS = ("battery", "climate", "status", "location")
REFRESH_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_KINDS, default=["status"]): vol.All(
            cv.ensure_list, [vol.In(REFRESH_KINDS)]
        )
    }
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the mynissan.refresh service."""

    async def _async_refresh(call: ServiceCall) -> None:
        entries = [
            entry
            for entry in hass.config_entries.async_loaded_entries(DOMAIN)
            if isinstance(getattr(entry, "runtime_data", None), NissanRuntimeData)
        ]
        if not entries:
            raise ServiceValidationError("MyNISSAN is not loaded")
        failures: list[str] = []
        for entry in entries:
            runtime = entry.runtime_data
            for vehicle in runtime.vehicles:
                for kind in call.data[ATTR_KINDS]:
                    try:
                        await _async_refresh_kind(runtime.client, vehicle.vin, kind)
                    except (NissanError, TimeoutError) as error:
                        failures.append(f"{kind}: {error}")
            await runtime.coordinator.async_request_refresh()
        if failures:
            raise HomeAssistantError("MyNISSAN refresh failed - " + "; ".join(failures))

    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, _async_refresh, schema=REFRESH_SCHEMA
    )
    return True


async def _async_refresh_kind(client, vin: str, kind: str) -> None:
    """Send one refresh request and wait for the car's answer."""
    if kind in ("battery", "climate"):
        refresh = (
            client.async_refresh_battery_status
            if kind == "battery"
            else client.async_refresh_climate_status
        )
        if not await refresh(vin):
            raise NissanError(f"{kind} refresh was not accepted")
        return
    request = await (
        client.async_refresh_vehicle_status(vin)
        if kind == "status"
        else client.async_locate_vehicle(vin)
    )
    result = await client.async_wait_for_service_request(vin, request)
    if not result.is_success:
        status = result.status.value if result.status is not None else "unknown"
        raise NissanError(f"{kind} refresh ended with status {status}")
    _LOGGER.debug("MyNISSAN %s refresh succeeded for %s", kind, vin)
PLATFORMS: tuple[Platform, ...] = (
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
)


async def async_setup_entry(hass: HomeAssistant, entry: NissanConfigEntry) -> bool:
    """Set up a MyNISSAN account from a config entry."""
    data = cast(NissanConfigData, entry.data)
    if data.get(CONF_AUTH_PROFILE) != MOBILE_AUTH_PROFILE:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="invalid_auth",
        )

    @callback
    def async_store_tokens(tokens: Tokens) -> None:
        """Persist refreshed OAuth tokens in the config entry."""
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_TOKENS: tokens_to_data(tokens)},
        )

    try:
        country = country_from_value(data[CONF_COUNTRY])
        tokens_data = cast(Mapping[str, object], data[CONF_TOKENS])
        client = create_client(
            hass,
            country=country,
            tokens=tokens_from_data(tokens_data),
            oauth_device_id=data[CONF_OAUTH_DEVICE_ID],
            token_listener=async_store_tokens,
        )
        vehicles = await client.async_get_vehicles()
    except AuthenticationError as error:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="invalid_auth",
        ) from error
    except NetworkError as error:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
        ) from error
    except NissanError as error:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="api_error",
        ) from error
    except ValueError as error:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="api_error",
        ) from error

    if not vehicles:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="no_vehicles",
        )

    coordinator = NissanDataUpdateCoordinator(hass, entry, client, vehicles)
    try:
        vehicle_capabilities = await asyncio.gather(
            *(
                client.async_get_vehicle_capabilities(
                    vehicle.vin,
                    coordinator.temperature_unit,
                )
                for vehicle in vehicles
            )
        )
    except AuthenticationError as error:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="invalid_auth",
        ) from error
    except NetworkError as error:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
        ) from error
    except NissanError as error:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="api_error",
        ) from error

    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = NissanRuntimeData(
        client=client,
        vehicles=vehicles,
        capabilities={capabilities.vin: capabilities for capabilities in vehicle_capabilities},
        coordinator=coordinator,
    )
    _register_vehicles(hass, entry, vehicles)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a MyNISSAN config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


@callback
def _register_vehicles(
    hass: HomeAssistant,
    entry: NissanConfigEntry,
    vehicles: tuple[Vehicle, ...],
) -> None:
    """Register every discovered vehicle as a Home Assistant device."""
    registry = dr.async_get(hass)
    for vehicle in vehicles:
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, vehicle.vin)},
            manufacturer=MANUFACTURER,
            model=vehicle.model,
            name=_vehicle_name(vehicle),
            serial_number=vehicle.vin,
        )


def _vehicle_name(vehicle: Vehicle) -> str:
    """Build a useful device name from known vehicle data."""
    if vehicle.nickname:
        return vehicle.nickname

    year_and_model = " ".join(part for part in (vehicle.year, vehicle.model) if part is not None)
    if year_and_model:
        return year_and_model
    return f"Nissan {vehicle.vin[-4:]}"
