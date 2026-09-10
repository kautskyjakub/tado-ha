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
from homeassistant.helpers.event import async_track_time_change

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_GARMIN_EMAIL,
    CONF_GARMIN_PASSWORD,
    CONF_WAKE_SENSOR_ENTITY,
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
        tokenstore_path = hass.config.path(f".storage/{DOMAIN}_garmin_{entry.entry_id}")
        garmin_coordinator = GarminAlarmCoordinator(
            hass, entry.entry_id, data[CONF_GARMIN_EMAIL], data[CONF_GARMIN_PASSWORD], tokenstore_path
        )
        try:
            await garmin_coordinator.async_config_entry_first_refresh()
        except Exception:  # noqa: BLE001 - a bad Garmin login must not block the thermostat
            _LOGGER.warning("Initial Garmin alarm fetch failed, will retry on schedule", exc_info=True)

    coordinator = TadoScheduleCoordinator(
        hass,
        climate_entity_id=data[CONF_CLIMATE_ENTITY],
        weather_entity_id=data.get(CONF_WEATHER_ENTITY),
        wake_sensor_entity_id=data.get(CONF_WAKE_SENSOR_ENTITY),
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

    if garmin_coordinator is not None:
        entry.async_on_unload(
            async_track_time_change(
                hass, _make_garmin_hourly_check(garmin_coordinator, settings), minute=0, second=0
            )
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _make_garmin_hourly_check(garmin_coordinator: GarminAlarmCoordinator, settings: TunableSettings):
    """An hourly tick that only actually syncs Garmin at the configured hours.

    Reading settings.garmin_sync_hour_1/2 fresh on every tick (rather than
    scheduling two fixed-hour triggers) means changing those number entities
    takes effect immediately, no reload required - a wake time set at bedtime
    is checked once after midnight and once more shortly before a typical
    wake-up, as a cheap guard against a last-minute change, instead of
    polling Garmin all day.
    """

    async def _check(now):
        if now.hour in (settings.garmin_sync_hour_1, settings.garmin_sync_hour_2):
            await garmin_coordinator.async_request_refresh()

    return _check


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
