"""Constants for the Tado Schedule integration."""
from __future__ import annotations

DOMAIN = "tado_schedule"
PLATFORMS = ["number", "switch", "sensor", "button"]

# --- config_entry / options keys ---
CONF_CLIMATE_ENTITY = "climate_entity"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_ZONE_NAME = "zone_name"
CONF_GARMIN_ENABLED = "garmin_enabled"
CONF_GARMIN_EMAIL = "garmin_email"
CONF_GARMIN_PASSWORD = "garmin_password"
CONF_GARMIN_WEEKDAYS = "garmin_weekdays"  # weekdays the Garmin alarm should drive the wake block

# --- defaults, all overridable at runtime via number entities ---
DEFAULT_AWAY_TEMP = 16.0
DEFAULT_ECO_SETBACK = 2.0
DEFAULT_COMFORT_TEMP = 21.0
DEFAULT_WARMUP_MINUTES_PER_DEGREE = 12.0
DEFAULT_MAX_PREHEAT_MINUTES = 90
DEFAULT_OUTDOOR_BASELINE_C = 10.0
DEFAULT_OUTDOOR_SENSITIVITY = 0.03  # extra fraction of warmup time per degree colder than baseline
DEFAULT_WAKE_READY_BUFFER_MINUTES = 0  # how many minutes before the alarm the room should already be at temp

UPDATE_INTERVAL_SECONDS = 300  # scheduler tick (weather/eco/schedule evaluation)
GARMIN_UPDATE_INTERVAL_SECONDS = 1800  # alarm polling, keep well under Garmin rate limits

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = "tado_schedule_weekplan"

# Days of week keys as used throughout the schedule storage (ISO: 0=Monday)
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

SERVICE_SET_SCHEDULE = "set_schedule"
SERVICE_SYNC_GARMIN = "sync_garmin_now"
SERVICE_GET_SCHEDULE = "get_schedule"

ATTR_WEEKPLAN = "weekplan"
