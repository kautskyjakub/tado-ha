"""Config flow: pick the local Matter climate entity, weather entity, Garmin login."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_GARMIN_EMAIL,
    CONF_GARMIN_PASSWORD,
    CONF_GARMIN_WEEKDAYS,
    CONF_WAKE_SENSOR_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_ZONE_NAME,
    DOMAIN,
    WEEKDAYS,
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ZONE_NAME): selector.TextSelector(),
        vol.Required(CONF_CLIMATE_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="climate")
        ),
        vol.Optional(CONF_WEATHER_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="weather")
        ),
        vol.Optional(CONF_WAKE_SENSOR_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
        ),
        vol.Optional(CONF_GARMIN_EMAIL): selector.TextSelector(),
        vol.Optional(CONF_GARMIN_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
        vol.Optional(CONF_GARMIN_WEEKDAYS, default=WEEKDAYS): selector.SelectSelector(
            selector.SelectSelectorConfig(options=WEEKDAYS, multiple=True)
        ),
    }
)


class TadoScheduleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            if bool(user_input.get(CONF_GARMIN_EMAIL)) != bool(user_input.get(CONF_GARMIN_PASSWORD)):
                errors["base"] = "garmin_credentials_incomplete"
            else:
                await self.async_set_unique_id(f"{DOMAIN}_{user_input[CONF_CLIMATE_ENTITY]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input[CONF_ZONE_NAME], data=user_input)

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "TadoScheduleOptionsFlow":
        return TadoScheduleOptionsFlow(config_entry)


class TadoScheduleOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self._config_entry.data, **self._config_entry.options}
        schema = vol.Schema(
            {
                vol.Optional(CONF_WEATHER_ENTITY, default=current.get(CONF_WEATHER_ENTITY)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="weather")
                ),
                vol.Optional(
                    CONF_WAKE_SENSOR_ENTITY, default=current.get(CONF_WAKE_SENSOR_ENTITY)
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature")),
                vol.Optional(CONF_GARMIN_EMAIL, default=current.get(CONF_GARMIN_EMAIL, "")): selector.TextSelector(),
                vol.Optional(
                    CONF_GARMIN_PASSWORD, default=current.get(CONF_GARMIN_PASSWORD, "")
                ): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
                vol.Optional(
                    CONF_GARMIN_WEEKDAYS, default=current.get(CONF_GARMIN_WEEKDAYS, WEEKDAYS)
                ): selector.SelectSelector(selector.SelectSelectorConfig(options=WEEKDAYS, multiple=True)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
