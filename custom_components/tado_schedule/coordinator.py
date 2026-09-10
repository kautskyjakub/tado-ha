"""Coordinators: one fast tick that drives the thermostat, one slow poll for Garmin."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.components.persistent_notification import async_create, async_dismiss
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_AWAY_TEMP,
    DEFAULT_ECO_SETBACK,
    DEFAULT_FROST_PROTECT_TEMP,
    DEFAULT_GARMIN_SYNC_HOUR_1,
    DEFAULT_GARMIN_SYNC_HOUR_2,
    DEFAULT_MAX_PREHEAT_MINUTES,
    DEFAULT_MILD_OUTDOOR_THRESHOLD,
    DEFAULT_MILD_SETBACK,
    DEFAULT_OUTDOOR_BASELINE_C,
    DEFAULT_OUTDOOR_SENSITIVITY,
    DEFAULT_SEASON_END_MONTH,
    DEFAULT_SEASON_START_MONTH,
    DEFAULT_WAKE_BOOST_TEMP,
    DEFAULT_WAKE_READY_BUFFER_MINUTES,
    DEFAULT_WAKE_TARGET_TEMP,
    DEFAULT_WARMUP_MINUTES_PER_DEGREE,
    DOMAIN,
    UPDATE_INTERVAL_SECONDS,
)
from .decision import HeatingDecision, compute_decision
from .garmin import GarminAlarm, GarminAlarmClient, GarminMfaRequired
from .schedule_store import WeekplanStore

_LOGGER = logging.getLogger(__name__)


@dataclass
class TunableSettings:
    """Live values backing the number/switch entities - mutated in place by them."""

    away_active: bool = False
    away_temp: float = DEFAULT_AWAY_TEMP
    eco_active: bool = False
    eco_setback: float = DEFAULT_ECO_SETBACK
    warmup_minutes_per_degree: float = DEFAULT_WARMUP_MINUTES_PER_DEGREE
    max_preheat_minutes: int = DEFAULT_MAX_PREHEAT_MINUTES
    outdoor_baseline_c: float = DEFAULT_OUTDOOR_BASELINE_C
    outdoor_sensitivity: float = DEFAULT_OUTDOOR_SENSITIVITY
    wake_ready_buffer_minutes: int = DEFAULT_WAKE_READY_BUFFER_MINUTES
    wake_target_temp: float = DEFAULT_WAKE_TARGET_TEMP
    wake_boost_temp: float = DEFAULT_WAKE_BOOST_TEMP
    season_start_month: int = DEFAULT_SEASON_START_MONTH
    season_end_month: int = DEFAULT_SEASON_END_MONTH
    frost_protect_temp: float = DEFAULT_FROST_PROTECT_TEMP
    mild_outdoor_threshold: float = DEFAULT_MILD_OUTDOOR_THRESHOLD
    mild_setback: float = DEFAULT_MILD_SETBACK
    garmin_sync_hour_1: int = DEFAULT_GARMIN_SYNC_HOUR_1
    garmin_sync_hour_2: int = DEFAULT_GARMIN_SYNC_HOUR_2


class GarminAlarmCoordinator(DataUpdateCoordinator[list[GarminAlarm]]):
    """Fetches Garmin Connect alarms - on demand only (see __init__.py's hourly
    trigger, which calls async_request_refresh() at the configured sync hours),
    not on a fixed polling interval. A wake time set at bedtime doesn't need
    checking every 30 minutes all day, and Garmin's API is easy to over-poll."""

    def __init__(self, hass: HomeAssistant, entry_id: str, email: str, password: str, tokenstore_path: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="tado_schedule_garmin_alarms",
            update_interval=None,
        )
        self._entry_id = entry_id
        self._client = GarminAlarmClient(email, password, tokenstore_path)

    @property
    def _mfa_notification_id(self) -> str:
        return f"{DOMAIN}_garmin_mfa_{self._entry_id}"

    async def _async_update_data(self) -> list[GarminAlarm]:
        try:
            alarms = await self.hass.async_add_executor_job(self._client.fetch_alarms)
        except GarminMfaRequired:
            async_create(
                self.hass,
                (
                    "Garmin Connect potřebuje jednorázový kód, který ti právě poslal "
                    "e-mailem/SMS, aby dokončil přihlášení. Zavolej službu "
                    f"`tado_schedule.submit_garmin_mfa_code` s `config_entry_id: {self._entry_id}` "
                    "a `code: <kód>`."
                ),
                title="Tado Schedule – Garmin potřebuje kód",
                notification_id=self._mfa_notification_id,
            )
            return self.data or []
        async_dismiss(self.hass, self._mfa_notification_id)
        return alarms

    async def async_submit_mfa_code(self, code: str) -> None:
        await self.hass.async_add_executor_job(self._client.submit_mfa_code, code)
        async_dismiss(self.hass, self._mfa_notification_id)
        await self.async_request_refresh()


class TadoScheduleCoordinator(DataUpdateCoordinator[HeatingDecision]):
    """Evaluates the weekplan + eco/away/weather/Garmin state and drives the climate entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        climate_entity_id: str,
        weather_entity_id: str | None,
        wake_sensor_entity_id: str | None,
        weekplan_store: WeekplanStore,
        settings: TunableSettings,
        garmin_coordinator: GarminAlarmCoordinator | None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="tado_schedule",
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.climate_entity_id = climate_entity_id
        self.weather_entity_id = weather_entity_id
        self.wake_sensor_entity_id = wake_sensor_entity_id
        self.weekplan_store = weekplan_store
        self.settings = settings
        self.garmin_coordinator = garmin_coordinator

    async def _async_update_data(self) -> HeatingDecision:
        now = dt_util.now()
        current_indoor_temp = self._current_indoor_temp()
        outdoor_forecast_temp = await self._async_outdoor_forecast_temp()
        garmin_alarms = self.garmin_coordinator.data if self.garmin_coordinator else []

        decision = compute_decision(
            now,
            self.weekplan_store.weekplan,
            garmin_alarms or [],
            away_active=self.settings.away_active,
            away_temp=self.settings.away_temp,
            eco_active=self.settings.eco_active,
            eco_setback=self.settings.eco_setback,
            current_indoor_temp=current_indoor_temp,
            outdoor_forecast_temp=outdoor_forecast_temp,
            warmup_minutes_per_degree=self.settings.warmup_minutes_per_degree,
            max_preheat_minutes=self.settings.max_preheat_minutes,
            outdoor_baseline_c=self.settings.outdoor_baseline_c,
            outdoor_sensitivity=self.settings.outdoor_sensitivity,
            wake_ready_buffer_minutes=self.settings.wake_ready_buffer_minutes,
            wake_sensor_temp=self._wake_sensor_temp(),
            wake_target_temp=self.settings.wake_target_temp if self.wake_sensor_entity_id else None,
            wake_boost_temp=self.settings.wake_boost_temp,
            season_start_month=self.settings.season_start_month,
            season_end_month=self.settings.season_end_month,
            frost_protect_temp=self.settings.frost_protect_temp,
            mild_outdoor_threshold=self.settings.mild_outdoor_threshold,
            mild_setback=self.settings.mild_setback,
        )
        await self._async_apply_decision(decision)
        return decision

    def _current_indoor_temp(self) -> float | None:
        state = self.hass.states.get(self.climate_entity_id)
        if state is None:
            return None
        value = state.attributes.get("current_temperature")
        return float(value) if value is not None else None

    def _wake_sensor_temp(self) -> float | None:
        if not self.wake_sensor_entity_id:
            return None
        state = self.hass.states.get(self.wake_sensor_entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    async def _async_outdoor_forecast_temp(self) -> float | None:
        if not self.weather_entity_id:
            return None
        try:
            result = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": self.weather_entity_id, "type": "hourly"},
                blocking=True,
                return_response=True,
            )
            forecasts = (result or {}).get(self.weather_entity_id, {}).get("forecast", [])
            if forecasts:
                temp = forecasts[0].get("temperature")
                if temp is not None:
                    return float(temp)
        except Exception:  # noqa: BLE001 - not every weather integration supports hourly forecasts
            _LOGGER.debug("Hourly forecast unavailable for %s, using current reading", self.weather_entity_id, exc_info=True)

        state = self.hass.states.get(self.weather_entity_id)
        if state is not None:
            value = state.attributes.get("temperature")
            if value is not None:
                return float(value)
        return None

    async def _async_apply_decision(self, decision: HeatingDecision) -> None:
        state = self.hass.states.get(self.climate_entity_id)
        if state is None:
            _LOGGER.warning("Climate entity %s not found, cannot apply schedule", self.climate_entity_id)
            return

        if decision.hvac_mode == "off":
            if state.state != "off":
                await self.hass.services.async_call(
                    "climate", "set_hvac_mode", {"entity_id": self.climate_entity_id, "hvac_mode": "off"}, blocking=True
                )
            return

        if state.state == "off":
            await self.hass.services.async_call(
                "climate", "set_hvac_mode", {"entity_id": self.climate_entity_id, "hvac_mode": "heat"}, blocking=True
            )

        current_target = state.attributes.get("temperature")
        if current_target is None or abs(float(current_target) - decision.target_temp) >= 0.1:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": self.climate_entity_id, "temperature": decision.target_temp},
                blocking=True,
            )
