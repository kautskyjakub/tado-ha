"""Manual 'sync Garmin alarms now' button, for right after you change an alarm."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    if entry_data["garmin_coordinator"] is None:
        return
    async_add_entities([SyncGarminButton(entry.entry_id, entry_data)])


class SyncGarminButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "sync_garmin_now"
    _attr_icon = "mdi:sync"

    def __init__(self, entry_id: str, entry_data: dict) -> None:
        self._garmin_coordinator = entry_data["garmin_coordinator"]
        self._coordinator = entry_data["coordinator"]
        self._attr_unique_id = f"{entry_id}_sync_garmin_now"
        self._attr_device_info = entry_data["device_info"]

    async def async_press(self) -> None:
        await self._garmin_coordinator.async_request_refresh()
        await self._coordinator.async_request_refresh()
