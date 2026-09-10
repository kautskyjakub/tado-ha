"""Services used by the Lovelace card to read/write the weekly schedule and
to force an immediate Garmin alarm refresh."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_MFA_CODE,
    ATTR_WEEKPLAN,
    DOMAIN,
    SERVICE_GET_SCHEDULE,
    SERVICE_SET_SCHEDULE,
    SERVICE_SUBMIT_GARMIN_MFA_CODE,
    SERVICE_SYNC_GARMIN,
)

ATTR_CONFIG_ENTRY_ID = "config_entry_id"

SET_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_WEEKPLAN): dict,
    }
)
ENTRY_ONLY_SCHEMA = vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string})
SUBMIT_MFA_CODE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_MFA_CODE): cv.string,
    }
)


def _entry_data(hass: HomeAssistant, entry_id: str) -> dict:
    domain_data = hass.data.get(DOMAIN, {})
    if entry_id not in domain_data:
        raise ServiceValidationError(f"Unknown tado_schedule config_entry_id: {entry_id}")
    return domain_data[entry_id]


def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SET_SCHEDULE):
        return  # services are global, only register once across all config entries

    async def handle_set_schedule(call: ServiceCall) -> None:
        entry = _entry_data(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        await entry["weekplan_store"].async_set_weekplan(call.data[ATTR_WEEKPLAN])
        await entry["coordinator"].async_request_refresh()

    async def handle_get_schedule(call: ServiceCall) -> ServiceResponse:
        entry = _entry_data(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        return {ATTR_WEEKPLAN: entry["weekplan_store"].weekplan}

    async def handle_sync_garmin(call: ServiceCall) -> None:
        entry = _entry_data(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        if entry["garmin_coordinator"] is None:
            raise ServiceValidationError("This zone has no Garmin account configured")
        await entry["garmin_coordinator"].async_request_refresh()
        await entry["coordinator"].async_request_refresh()

    async def handle_submit_garmin_mfa_code(call: ServiceCall) -> None:
        entry = _entry_data(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        if entry["garmin_coordinator"] is None:
            raise ServiceValidationError("This zone has no Garmin account configured")
        await entry["garmin_coordinator"].async_submit_mfa_code(call.data[ATTR_MFA_CODE])
        await entry["coordinator"].async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_SET_SCHEDULE, handle_set_schedule, schema=SET_SCHEDULE_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SCHEDULE,
        handle_get_schedule,
        schema=ENTRY_ONLY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(DOMAIN, SERVICE_SYNC_GARMIN, handle_sync_garmin, schema=ENTRY_ONLY_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_SUBMIT_GARMIN_MFA_CODE, handle_submit_garmin_mfa_code, schema=SUBMIT_MFA_CODE_SCHEMA
    )
