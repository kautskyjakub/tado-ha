"""Thin wrapper around the garminconnect library for reading watch alarms.

Garmin does not expose a documented "next alarm" field directly - devices
return a list of configured alarms (potentially several, one per repeating
pattern) and each alarm carries an enabled flag, a minutes-since-midnight
time, and a weekday bitmask/list. The exact key names have shifted between
garminconnect releases, so parsing here is defensive: unknown/missing keys
are skipped rather than raising, and a device with no readable alarms simply
contributes nothing to the schedule.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Garmin encodes alarm weekdays as 1=Monday..7=Sunday in most firmware builds.
_GARMIN_WEEKDAY_TO_INDEX = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6}


@dataclass
class GarminAlarm:
    enabled: bool
    time_of_day: time
    weekdays: set[int]  # 0=Monday..6=Sunday, matching WEEKDAYS in const.py


class GarminAlarmClient:
    """Logs into Garmin Connect and exposes enabled alarms per weekday."""

    def __init__(self, email: str, password: str) -> None:
        self._email = email
        self._password = password
        self._api: Any | None = None

    def connect(self) -> None:
        """Blocking login - must be run in an executor."""
        from garminconnect import Garmin  # imported lazily, only used off the event loop

        api = Garmin(self._email, self._password)
        api.login()
        self._api = api

    def fetch_alarms(self) -> list[GarminAlarm]:
        """Blocking fetch - must be run in an executor. Returns [] on any failure."""
        if self._api is None:
            self.connect()
        assert self._api is not None

        try:
            raw_alarms = self._api.get_device_alarms()
        except Exception:  # noqa: BLE001 - Garmin session can expire at any time
            _LOGGER.warning("Garmin alarm fetch failed, retrying with a fresh login", exc_info=True)
            self.connect()
            raw_alarms = self._api.get_device_alarms()

        alarms: list[GarminAlarm] = []
        for raw in raw_alarms or []:
            alarm = _parse_alarm(raw)
            if alarm is not None:
                alarms.append(alarm)
        return alarms


def _parse_alarm(raw: dict[str, Any]) -> GarminAlarm | None:
    enabled = bool(raw.get("alarmEnabled") or raw.get("enabled") or raw.get("alarmStatus") == "ENABLED")
    if not enabled:
        return None

    minutes = raw.get("alarmTime")
    if minutes is None:
        minutes = raw.get("alarmTimeMinutes")
    if minutes is None:
        _LOGGER.debug("Garmin alarm without a recognizable time field: %s", raw)
        return None

    try:
        minutes = int(minutes)
        time_of_day = time(hour=(minutes // 60) % 24, minute=minutes % 60)
    except (TypeError, ValueError):
        _LOGGER.debug("Garmin alarm with unparseable time field: %s", raw)
        return None

    weekdays_raw = raw.get("alarmDays") or raw.get("days") or []
    weekdays: set[int] = set()
    for wd in weekdays_raw:
        if isinstance(wd, int) and wd in _GARMIN_WEEKDAY_TO_INDEX:
            weekdays.add(_GARMIN_WEEKDAY_TO_INDEX[wd])
        elif isinstance(wd, str):
            wd_norm = wd.strip().lower()[:3]
            for idx, name in enumerate(["mon", "tue", "wed", "thu", "fri", "sat", "sun"]):
                if wd_norm == name:
                    weekdays.add(idx)
    if not weekdays:
        # A one-shot alarm ("tomorrow only") - Garmin's app treats it as every
        # day until dismissed; do the same so it still drives the wake block.
        weekdays = set(range(7))

    return GarminAlarm(enabled=True, time_of_day=time_of_day, weekdays=weekdays)


def earliest_alarm_for_weekday(alarms: list[GarminAlarm], weekday_index: int) -> time | None:
    """Among all enabled alarms active on the given weekday, the earliest one wins."""
    candidates = [a.time_of_day for a in alarms if weekday_index in a.weekdays]
    return min(candidates) if candidates else None


def next_alarm_datetime(alarms: list[GarminAlarm], now: datetime) -> datetime | None:
    """The next point in time (today or up to a week out) an enabled alarm fires."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for day_offset in range(8):
        check_day = midnight + timedelta(days=day_offset)
        alarm_time = earliest_alarm_for_weekday(alarms, check_day.weekday())
        if alarm_time is None:
            continue
        candidate = check_day.replace(hour=alarm_time.hour, minute=alarm_time.minute, second=0, microsecond=0)
        if candidate > now:
            return candidate
    return None
