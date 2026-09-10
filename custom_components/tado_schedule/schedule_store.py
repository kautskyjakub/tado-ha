"""Persistence and lookup helpers for the weekly heating schedule.

The weekplan is a plain JSON-serialisable structure so it can be sent to /
edited by the Lovelace card as-is, without any translation layer:

    {
      "mon": [{"start": "00:00", "temp": 18.0, "mode": "eco"},
              {"start": "06:30", "temp": 21.0, "mode": "comfort"},
              {"start": "22:00", "temp": 17.0, "mode": "eco"}],
      "tue": [...],
      ...
    }

Each day's block list is kept sorted by "start" and is expected to start at
"00:00" - the last block implicitly runs until midnight.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DEFAULT_COMFORT_TEMP, STORAGE_KEY_PREFIX, STORAGE_VERSION, WEEKDAYS


def _default_weekplan() -> dict[str, list[dict[str, Any]]]:
    """A sane starting schedule: comfort 06:30-22:00, eco overnight, every day."""
    day = [
        {"start": "00:00", "temp": DEFAULT_COMFORT_TEMP - 3, "mode": "eco"},
        {"start": "06:30", "temp": DEFAULT_COMFORT_TEMP, "mode": "comfort"},
        {"start": "22:00", "temp": DEFAULT_COMFORT_TEMP - 4, "mode": "eco"},
    ]
    return {wd: [block.copy() for block in day] for wd in WEEKDAYS}


class WeekplanStore:
    """Loads/saves one zone's weekplan under Home Assistant's .storage."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}_{entry_id}"
        )
        self._weekplan: dict[str, list[dict[str, Any]]] | None = None

    async def async_load(self) -> dict[str, list[dict[str, Any]]]:
        data = await self._store.async_load()
        self._weekplan = data if data else _default_weekplan()
        return self._weekplan

    @property
    def weekplan(self) -> dict[str, list[dict[str, Any]]]:
        if self._weekplan is None:
            raise RuntimeError("WeekplanStore.async_load() was not awaited yet")
        return self._weekplan

    async def async_set_weekplan(self, weekplan: dict[str, list[dict[str, Any]]]) -> None:
        _validate_weekplan(weekplan)
        self._weekplan = weekplan
        await self._store.async_save(self._weekplan)

    def block_for(self, when: datetime) -> dict[str, Any]:
        """Return the schedule block that is active at the given local time."""
        weekday = WEEKDAYS[when.weekday()]
        blocks = self.weekplan.get(weekday) or _default_weekplan()[weekday]
        current_time = when.time()
        active = blocks[0]
        for block in blocks:
            block_time = time.fromisoformat(block["start"])
            if block_time <= current_time:
                active = block
            else:
                break
        return active

    def next_change(self, when: datetime) -> tuple[datetime, dict[str, Any]] | None:
        """Return (datetime, block) for the next schedule transition after `when`."""
        midnight = when.replace(hour=0, minute=0, second=0, microsecond=0)
        for day_offset in range(8):  # scan up to a full week ahead
            check_day = midnight + timedelta(days=day_offset)
            weekday = WEEKDAYS[check_day.weekday()]
            blocks = self.weekplan.get(weekday) or []
            for block in blocks:
                block_time = time.fromisoformat(block["start"])
                candidate = check_day.replace(
                    hour=block_time.hour, minute=block_time.minute, second=0, microsecond=0
                )
                if candidate > when:
                    return candidate, block
        return None


def _validate_weekplan(weekplan: dict[str, list[dict[str, Any]]]) -> None:
    if set(weekplan.keys()) - set(WEEKDAYS):
        raise ValueError(f"weekplan keys must be a subset of {WEEKDAYS}")
    for day, blocks in weekplan.items():
        if not blocks:
            raise ValueError(f"day '{day}' has no schedule blocks")
        if blocks[0]["start"] != "00:00":
            raise ValueError(f"day '{day}' must start with a 00:00 block")
        for block in blocks:
            time.fromisoformat(block["start"])  # raises ValueError if malformed
            float(block["temp"])
            if block.get("mode") not in ("comfort", "eco", "off"):
                raise ValueError(f"block mode must be comfort/eco/off, got {block.get('mode')!r}")
