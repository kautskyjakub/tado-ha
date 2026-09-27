"""Read-only sensors: what's the coordinator doing right now, and why."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import ATTR_WEEKPLAN, DOMAIN
from .garmin import next_alarm_datetime


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            CurrentDecisionSensor(entry.entry_id, entry_data),
            NextScheduleChangeSensor(entry.entry_id, entry_data),
            NextGarminWakeSensor(entry.entry_id, entry_data),
            WeekplanSensor(entry.entry_id, entry_data),
        ]
    )


class CurrentDecisionSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "current_decision"
    _attr_icon = "mdi:thermostat"

    def __init__(self, entry_id: str, entry_data: dict) -> None:
        super().__init__(entry_data["coordinator"])
        self._attr_unique_id = f"{entry_id}_current_decision"
        self._attr_device_info = entry_data["device_info"]

    @property
    def native_value(self) -> str | None:
        decision = self.coordinator.data
        return decision.reason if decision else None

    @property
    def extra_state_attributes(self) -> dict:
        decision = self.coordinator.data
        if not decision:
            return {}
        return {"target_temperature": decision.target_temp, "hvac_mode": decision.hvac_mode}


class NextScheduleChangeSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "next_schedule_change"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, entry_id: str, entry_data: dict) -> None:
        super().__init__(entry_data["coordinator"])
        self._store = entry_data["weekplan_store"]
        self._attr_unique_id = f"{entry_id}_next_schedule_change"
        self._attr_device_info = entry_data["device_info"]

    @property
    def native_value(self) -> datetime | None:
        result = self._store.next_change(dt_util.now())
        return result[0] if result else None


class NextGarminWakeSensor(CoordinatorEntity, SensorEntity):
    """Next Garmin alarm.

    The Garmin coordinator only refreshes at the configured sync hours, so
    without its own timer the state would keep showing an alarm that has
    already gone off until the next sync. Each state write therefore also
    schedules a re-evaluation at the alarm time itself, which rolls the
    sensor over to the following alarm the moment the current one passes.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "next_garmin_wake"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:alarm"

    def __init__(self, entry_id: str, entry_data: dict) -> None:
        garmin_coordinator = entry_data["garmin_coordinator"]
        super().__init__(garmin_coordinator or entry_data["coordinator"])
        self._garmin_coordinator = garmin_coordinator
        self._attr_unique_id = f"{entry_id}_next_garmin_wake"
        self._attr_device_info = entry_data["device_info"]
        self._attr_available = garmin_coordinator is not None
        self._unsub_rollover: CALLBACK_TYPE | None = None

    @property
    def native_value(self) -> datetime | None:
        if self._garmin_coordinator is None:
            return None
        alarms = self._garmin_coordinator.data or []
        return next_alarm_datetime(alarms, dt_util.now())

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._schedule_rollover()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_rollover()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        super()._handle_coordinator_update()
        self._schedule_rollover()

    @callback
    def _cancel_rollover(self) -> None:
        if self._unsub_rollover is not None:
            self._unsub_rollover()
            self._unsub_rollover = None

    @callback
    def _schedule_rollover(self) -> None:
        self._cancel_rollover()
        alarm = self.native_value
        if alarm is None:
            return
        # One second past the alarm so next_alarm_datetime's strict "> now" skips it.
        self._unsub_rollover = async_track_point_in_time(
            self.hass, self._handle_rollover, alarm + timedelta(seconds=1)
        )

    @callback
    def _handle_rollover(self, _now: datetime) -> None:
        self._unsub_rollover = None
        self.async_write_ha_state()
        self._schedule_rollover()


class WeekplanSensor(CoordinatorEntity, SensorEntity):
    """Exposes the raw weekplan as an attribute so the card can read it without
    a service round-trip; writes still go through the set_schedule service."""

    _attr_has_entity_name = True
    _attr_translation_key = "weekplan"
    _attr_icon = "mdi:calendar-week"

    def __init__(self, entry_id: str, entry_data: dict) -> None:
        super().__init__(entry_data["coordinator"])
        self._store = entry_data["weekplan_store"]
        self._attr_unique_id = f"{entry_id}_weekplan"
        self._attr_device_info = entry_data["device_info"]

    @property
    def native_value(self) -> str:
        block_count = sum(len(blocks) for blocks in self._store.weekplan.values())
        return f"{block_count} blocks"

    @property
    def extra_state_attributes(self) -> dict:
        return {ATTR_WEEKPLAN: self._store.weekplan}
