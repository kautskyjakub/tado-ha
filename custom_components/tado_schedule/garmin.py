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

import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

_LOGGER = logging.getLogger(__name__)


class GarminMfaRequired(Exception):
    """Garmin is asking for the one-time code it just emailed/texted.

    Raised by connect()/fetch_alarms() when a login is blocked on that code.
    The caller is expected to surface this to the user (see coordinator.py)
    and later call GarminAlarmClient.submit_mfa_code() with what they typed in.
    """

# Garmin encodes alarm weekdays as 1=Monday..7=Sunday in most firmware builds.
_GARMIN_WEEKDAY_TO_INDEX = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6}


@dataclass
class GarminAlarm:
    enabled: bool
    time_of_day: time
    weekdays: set[int]  # 0=Monday..6=Sunday, matching WEEKDAYS in const.py


class GarminAlarmClient:
    """Logs into Garmin Connect and exposes enabled alarms per weekday.

    Login is two-phase because Garmin routinely challenges a login from a
    new device (our HA server) with an emailed/texted one-time code:

      1. connect() attempts the login. If a stored session in
         `tokenstore_path` is still valid, this succeeds outright - no code
         needed. Otherwise Garmin may demand MFA, in which case connect()
         raises GarminMfaRequired and remembers where the login was paused.
      2. submit_mfa_code() resumes that paused login with the code the user
         read out of their email, and - importantly - saves the resulting
         session to `tokenstore_path` so future restarts don't need MFA
         again (until Garmin invalidates the session).
    """

    def __init__(self, email: str, password: str, tokenstore_path: str) -> None:
        self._email = email
        self._password = password
        self._tokenstore_path = tokenstore_path
        self._api: Any | None = None
        self._mfa_pending: bool = False
        # Passed through to resume_login() for older garminconnect releases
        # that actually used it; recent releases (>=0.3.x) ignore this
        # argument and keep the real pending-login state on the Client
        # object itself (self._api.client), which is why mfa_pending above
        # is tracked as its own bool instead of "this value is not None" -
        # the library now always hands back None here even while a login
        # genuinely is stuck waiting on a code.
        self._mfa_client_state: Any | None = None

    @property
    def mfa_pending(self) -> bool:
        return self._mfa_pending

    def connect(self) -> None:
        """Blocking login - must be run in an executor. Raises GarminMfaRequired
        if Garmin wants a one-time code before the login can complete."""
        from garminconnect import Garmin  # imported lazily, only used off the event loop

        api = Garmin(self._email, self._password, return_on_mfa=True)
        mfa_status, state_or_token = api.login(tokenstore=self._tokenstore_path)
        self._api = api
        if mfa_status == "needs_mfa":
            self._mfa_pending = True
            self._mfa_client_state = state_or_token
            raise GarminMfaRequired()
        self._mfa_pending = False
        self._mfa_client_state = None

    def submit_mfa_code(self, code: str) -> None:
        """Blocking - must be run in an executor. Resumes the login connect()
        paused on, and persists the resulting session so this is only ever
        needed once."""
        if self._api is None or not self._mfa_pending:
            raise GarminMfaRequired("No pending Garmin login to resume")
        self._api.resume_login(self._mfa_client_state, code)
        self._mfa_pending = False
        self._mfa_client_state = None
        # resume_login() (unlike a plain login()) does not persist the new
        # session by itself - without this, the next restart would ask for
        # another MFA code even though we just completed one.
        with contextlib.suppress(Exception):
            self._api.client.dump(self._tokenstore_path)

    def fetch_alarms(self) -> list[GarminAlarm]:
        """Blocking fetch - must be run in an executor.

        Raises GarminMfaRequired if a login is paused on a one-time code -
        never silently starts a *second* login attempt while one is already
        pending, which would just email out another code and confuse things.
        """
        if self._mfa_pending:
            raise GarminMfaRequired()
        if self._api is None:
            self.connect()
        assert self._api is not None

        try:
            raw_alarms = self._api.get_device_alarms()
        except Exception:  # noqa: BLE001 - Garmin session can expire at any time
            _LOGGER.warning("Garmin alarm fetch failed, retrying with a fresh login", exc_info=True)
            self._api = None
            self.connect()
            raw_alarms = self._api.get_device_alarms()

        _LOGGER.debug("Garmin get_device_alarms() returned %d raw entries: %s", len(raw_alarms or []), raw_alarms)

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
