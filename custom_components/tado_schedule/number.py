"""Number entities exposing every tunable heating parameter to the HA UI -
no code edits needed to adjust preheat aggressiveness, eco setback, etc."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import TadoScheduleCoordinator, TunableSettings


@dataclass(frozen=True, kw_only=True)
class TadoNumberDescription(NumberEntityDescription):
    attr: str = ""


NUMBERS: tuple[TadoNumberDescription, ...] = (
    TadoNumberDescription(
        key="away_temperature",
        attr="away_temp",
        translation_key="away_temperature",
        native_min_value=4,
        native_max_value=25,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.BOX,
        icon="mdi:airplane",
    ),
    TadoNumberDescription(
        key="eco_setback",
        attr="eco_setback",
        translation_key="eco_setback",
        native_min_value=0,
        native_max_value=8,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.BOX,
        icon="mdi:leaf",
        entity_category=EntityCategory.CONFIG,
    ),
    TadoNumberDescription(
        key="warmup_minutes_per_degree",
        attr="warmup_minutes_per_degree",
        translation_key="warmup_minutes_per_degree",
        native_min_value=1,
        native_max_value=60,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode=NumberMode.BOX,
        icon="mdi:thermometer-chevron-up",
        entity_category=EntityCategory.CONFIG,
    ),
    TadoNumberDescription(
        key="max_preheat_minutes",
        attr="max_preheat_minutes",
        translation_key="max_preheat_minutes",
        native_min_value=0,
        native_max_value=240,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode=NumberMode.BOX,
        icon="mdi:clock-fast",
        entity_category=EntityCategory.CONFIG,
    ),
    TadoNumberDescription(
        key="outdoor_baseline_temp",
        attr="outdoor_baseline_c",
        translation_key="outdoor_baseline_temp",
        native_min_value=-10,
        native_max_value=20,
        native_step=1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.BOX,
        icon="mdi:weather-partly-cloudy",
        entity_category=EntityCategory.CONFIG,
    ),
    TadoNumberDescription(
        key="outdoor_sensitivity",
        attr="outdoor_sensitivity",
        translation_key="outdoor_sensitivity",
        native_min_value=0,
        native_max_value=0.2,
        native_step=0.01,
        mode=NumberMode.BOX,
        icon="mdi:tune-variant",
        entity_category=EntityCategory.CONFIG,
    ),
    TadoNumberDescription(
        key="wake_ready_buffer_minutes",
        attr="wake_ready_buffer_minutes",
        translation_key="wake_ready_buffer_minutes",
        native_min_value=0,
        native_max_value=60,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode=NumberMode.BOX,
        icon="mdi:alarm",
        entity_category=EntityCategory.CONFIG,
    ),
    TadoNumberDescription(
        key="wake_target_temperature",
        attr="wake_target_temp",
        translation_key="wake_target_temperature",
        native_min_value=10,
        native_max_value=28,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.BOX,
        icon="mdi:bed",
    ),
    TadoNumberDescription(
        key="wake_boost_temperature",
        attr="wake_boost_temp",
        translation_key="wake_boost_temperature",
        native_min_value=15,
        native_max_value=35,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.BOX,
        icon="mdi:fire",
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        TadoScheduleNumber(entry.entry_id, entry_data["coordinator"], entry_data["settings"], entry_data["device_info"], description)
        for description in NUMBERS
    )


class TadoScheduleNumber(NumberEntity):
    entity_description: TadoNumberDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        entry_id: str,
        coordinator: TadoScheduleCoordinator,
        settings: TunableSettings,
        device_info,
        description: TadoNumberDescription,
    ) -> None:
        self.entity_description = description
        self._coordinator = coordinator
        self._settings = settings
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> float:
        return getattr(self._settings, self.entity_description.attr)

    async def async_set_native_value(self, value: float) -> None:
        setattr(self._settings, self.entity_description.attr, value)
        self.async_write_ha_state()
        await self._coordinator.async_request_refresh()
