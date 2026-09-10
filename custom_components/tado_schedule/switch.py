"""Eco mode and away mode toggles."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import TadoScheduleCoordinator, TunableSettings


@dataclass(frozen=True, kw_only=True)
class TadoSwitchDescription(SwitchEntityDescription):
    attr: str = ""


SWITCHES: tuple[TadoSwitchDescription, ...] = (
    TadoSwitchDescription(key="eco_mode", attr="eco_active", translation_key="eco_mode", icon="mdi:leaf"),
    TadoSwitchDescription(key="away_mode", attr="away_active", translation_key="away_mode", icon="mdi:airplane"),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        TadoScheduleSwitch(entry.entry_id, entry_data["coordinator"], entry_data["settings"], entry_data["device_info"], description)
        for description in SWITCHES
    )


class TadoScheduleSwitch(SwitchEntity):
    entity_description: TadoSwitchDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        entry_id: str,
        coordinator: TadoScheduleCoordinator,
        settings: TunableSettings,
        device_info,
        description: TadoSwitchDescription,
    ) -> None:
        self.entity_description = description
        self._coordinator = coordinator
        self._settings = settings
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = device_info

    @property
    def is_on(self) -> bool:
        return bool(getattr(self._settings, self.entity_description.attr))

    async def async_turn_on(self, **kwargs) -> None:
        setattr(self._settings, self.entity_description.attr, True)
        self.async_write_ha_state()
        await self._coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        setattr(self._settings, self.entity_description.attr, False)
        self.async_write_ha_state()
        await self._coordinator.async_request_refresh()
