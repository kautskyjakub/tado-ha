"""The Tado Schedule integration.

Drives a Matter-exposed tado X climate entity from a locally-stored weekly
schedule, with eco/away setback, weather-anticipated preheating, and an
optional Garmin Connect alarm feed that overrides the morning wake time -
all without any tado° cloud account.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_GARMIN_EMAIL,
    CONF_GARMIN_PASSWORD,
    CONF_WEATHER_ENTITY,
    CONF_ZONE_NAME,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import GarminAlarmCoordinator, TadoScheduleCoordinator, TunableSettings
from .schedule_store import WeekplanStore
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = {**entry.data, **entry.options}
    zone_name = data[CONF_ZONE_NAME]

    weekplan_store = WeekplanStore(hass, entry.entry_id)
    await weekplan_store.async_load()

    settings = TunableSettings()

    garmin_coordinator: GarminAlarmCoordinator | None = None
    if data.get(CONF_GARMIN_EMAIL) and data.get(CONF_GARMIN_PASSWORD):
        garmin_coordinator = GarminAlarmCoordinator(hass, data[CONF_GARMIN_EMAIL], data[CONF_GARMIN_PASSWORD])
        try:
            await garmin_coordinator.async_config_entry_first_refresh()
        except Exception:  # noqa: BLE001 - a bad Garmin login must not block the thermostat
            _LOGGER.warning("Initial Garmin alarm fetch failed, will retry on schedule", exc_info=True)

    coordinator = TadoScheduleCoordinator(
        hass,
        climate_entity_id=data[CONF_CLIMATE_ENTITY],
        weather_entity_id=data.get(CONF_WEATHER_ENTITY),
        weekplan_store=weekplan_store,
        settings=settings,
        garmin_coordinator=garmin_coordinator,
    )
    await coordinator.async_config_entry_first_refresh()

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=zone_name,
        manufacturer="tado_schedule (community, local-only)",
        model="Virtual schedule controller",
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "garmin_coordinator": garmin_coordinator,
        "weekplan_store": weekplan_store,
        "settings": settings,
        "zone_name": zone_name,
        "device_info": device_info,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
