"""Turns weekplan + eco/away state + weather + Garmin alarms into one target.

Kept separate from schedule_store.py on purpose: schedule_store is the plain
"what did the user paint on the calendar" storage the card reads/writes
as-is, while this module is the runtime logic that merges in Garmin's wake
time and decides whether we're in a preheat window right now. Nothing here
is persisted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from .const import WEEKDAYS
from .garmin import GarminAlarm, earliest_alarm_for_weekday


@dataclass
class HeatingDecision:
    target_temp: float
    hvac_mode: str  # "heat" or "off"
    reason: str


def _effective_day_blocks(
    weekplan: dict[str, list[dict[str, Any]]], weekday_index: int, garmin_wake: time | None
) -> list[dict[str, Any]]:
    """Return the day's blocks, with the first comfort block's start swapped
    to the Garmin alarm time, if one is configured for that day.

    Only the *first* comfort block is treated as "the wake block" - later
    comfort blocks (e.g. an evening one) are left exactly as scheduled.
    """
    blocks = weekplan.get(WEEKDAYS[weekday_index]) or []
    if garmin_wake is None:
        return blocks

    result: list[dict[str, Any]] = []
    swapped = False
    for block in blocks:
        if not swapped and block.get("mode") == "comfort":
            result.append({**block, "start": garmin_wake.strftime("%H:%M")})
            swapped = True
        else:
            result.append(block)
    if not swapped:
        return blocks
    return sorted(result, key=lambda b: b["start"])


def block_for(
    weekplan: dict[str, list[dict[str, Any]]], now: datetime, garmin_alarms: list[GarminAlarm]
) -> dict[str, Any]:
    weekday_index = now.weekday()
    garmin_wake = earliest_alarm_for_weekday(garmin_alarms, weekday_index)
    blocks = _effective_day_blocks(weekplan, weekday_index, garmin_wake)
    if not blocks:
        return {"start": "00:00", "temp": 20.0, "mode": "comfort"}

    current_time = now.time()
    active = blocks[0]
    for block in blocks:
        if time.fromisoformat(block["start"]) <= current_time:
            active = block
        else:
            break
    return active


def next_comfort_transition(
    weekplan: dict[str, list[dict[str, Any]]],
    now: datetime,
    garmin_alarms: list[GarminAlarm],
    horizon_minutes: int,
) -> tuple[datetime, dict[str, Any]] | None:
    """Earliest upcoming switch into a "comfort" block within the horizon."""
    horizon = now + timedelta(minutes=horizon_minutes)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for day_offset in range(2):  # today + tomorrow comfortably covers any sane preheat horizon
        check_day = midnight + timedelta(days=day_offset)
        weekday_index = check_day.weekday()
        garmin_wake = earliest_alarm_for_weekday(garmin_alarms, weekday_index)
        blocks = _effective_day_blocks(weekplan, weekday_index, garmin_wake)
        for block in blocks:
            if block.get("mode") != "comfort":
                continue
            block_time = time.fromisoformat(block["start"])
            candidate = check_day.replace(hour=block_time.hour, minute=block_time.minute)
            if now < candidate <= horizon:
                return candidate, block
    return None


def estimate_preheat_minutes(
    target_temp: float,
    current_indoor_temp: float | None,
    outdoor_forecast_temp: float | None,
    warmup_minutes_per_degree: float,
    outdoor_baseline_c: float,
    outdoor_sensitivity: float,
    max_preheat_minutes: int,
) -> int:
    if current_indoor_temp is None:
        return 0
    deficit = max(0.0, target_temp - current_indoor_temp)
    if deficit == 0:
        return 0
    rate = warmup_minutes_per_degree
    if outdoor_forecast_temp is not None:
        # Colder outside air steals heat faster than it's added, so a radiator
        # needs proportionally longer to close the same indoor gap.
        coldness = max(0.0, outdoor_baseline_c - outdoor_forecast_temp)
        rate *= 1 + coldness * outdoor_sensitivity
    return min(max_preheat_minutes, round(deficit * rate))


def compute_decision(
    now: datetime,
    weekplan: dict[str, list[dict[str, Any]]],
    garmin_alarms: list[GarminAlarm],
    *,
    away_active: bool,
    away_temp: float,
    eco_active: bool,
    eco_setback: float,
    current_indoor_temp: float | None,
    outdoor_forecast_temp: float | None,
    warmup_minutes_per_degree: float,
    max_preheat_minutes: int,
    outdoor_baseline_c: float,
    outdoor_sensitivity: float,
    wake_ready_buffer_minutes: int,
) -> HeatingDecision:
    if away_active:
        return HeatingDecision(away_temp, "heat", "away")

    upcoming = next_comfort_transition(weekplan, now, garmin_alarms, max_preheat_minutes + wake_ready_buffer_minutes)
    if upcoming is not None:
        next_dt, next_block = upcoming
        target_temp = float(next_block["temp"])
        lead = estimate_preheat_minutes(
            target_temp,
            current_indoor_temp,
            outdoor_forecast_temp,
            warmup_minutes_per_degree,
            outdoor_baseline_c,
            outdoor_sensitivity,
            max_preheat_minutes,
        )
        preheat_start = next_dt - timedelta(minutes=lead + wake_ready_buffer_minutes)
        if preheat_start <= now < next_dt:
            return HeatingDecision(target_temp, "heat", f"preheating for {next_dt:%H:%M}")

    block = block_for(weekplan, now, garmin_alarms)
    mode = block.get("mode", "comfort")
    temp = float(block["temp"])
    if eco_active:
        temp -= eco_setback

    if mode == "off":
        return HeatingDecision(temp, "off", "scheduled off")
    return HeatingDecision(temp, "heat", f"scheduled {mode}")
