from datetime import datetime, time

from custom_components.tado_schedule.decision import (
    block_for,
    compute_decision,
    estimate_preheat_minutes,
    next_comfort_transition,
)
from custom_components.tado_schedule.garmin import GarminAlarm

BASE_KWARGS = dict(
    away_active=False,
    away_temp=16.0,
    eco_active=False,
    eco_setback=2.0,
    current_indoor_temp=19.0,
    outdoor_forecast_temp=5.0,
    warmup_minutes_per_degree=12.0,
    max_preheat_minutes=90,
    outdoor_baseline_c=10.0,
    outdoor_sensitivity=0.03,
    wake_ready_buffer_minutes=0,
)


def weekday_plan(comfort_start="06:30", comfort_temp=21.0, eco_temp=17.0):
    day = [
        {"start": "00:00", "temp": eco_temp, "mode": "eco"},
        {"start": comfort_start, "temp": comfort_temp, "mode": "comfort"},
        {"start": "22:00", "temp": eco_temp, "mode": "eco"},
    ]
    return {wd: [b.copy() for b in day] for wd in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}


def test_block_for_returns_current_active_block():
    weekplan = weekday_plan()
    # Monday 2026-09-14 08:00 -> inside the comfort block
    now = datetime(2026, 9, 14, 8, 0)
    block = block_for(weekplan, now, [])
    assert block["mode"] == "comfort"
    assert block["temp"] == 21.0


def test_block_for_before_first_transition_uses_first_block():
    weekplan = weekday_plan()
    now = datetime(2026, 9, 14, 3, 0)
    block = block_for(weekplan, now, [])
    assert block["mode"] == "eco"


def test_eco_mode_applies_setback_outside_preheat_window():
    weekplan = weekday_plan()
    # Well inside the eco block, far from the next comfort transition.
    now = datetime(2026, 9, 14, 23, 30)
    decision = compute_decision(
        now, weekplan, [], **{**BASE_KWARGS, "eco_active": True, "current_indoor_temp": 17.0}
    )
    assert decision.target_temp == 17.0 - 2.0
    assert decision.hvac_mode == "heat"


def test_away_mode_overrides_everything():
    weekplan = weekday_plan()
    now = datetime(2026, 9, 14, 8, 0)
    decision = compute_decision(now, weekplan, [], **{**BASE_KWARGS, "away_active": True})
    assert decision.target_temp == 16.0
    assert decision.reason == "away"


def test_off_block_turns_off_regardless_of_eco():
    weekplan = weekday_plan()
    weekplan["mon"][0]["mode"] = "off"
    weekplan["mon"][0]["temp"] = 10.0
    now = datetime(2026, 9, 14, 1, 0)
    decision = compute_decision(now, weekplan, [], **{**BASE_KWARGS, "eco_active": True})
    assert decision.hvac_mode == "off"


def test_preheat_window_ignores_eco_setback():
    weekplan = weekday_plan(comfort_start="07:00", comfort_temp=21.0)
    # deficit = 21 - 17 = 4 degrees; colder-than-baseline outdoor (5C vs 10C
    # baseline) raises the rate: 12 * (1 + 5*0.03) = 13.8 min/deg -> ~55 min lead.
    now = datetime(2026, 9, 14, 6, 10)  # 50 minutes before 07:00
    decision = compute_decision(
        now,
        weekplan,
        [],
        **{**BASE_KWARGS, "eco_active": True, "current_indoor_temp": 17.0, "outdoor_forecast_temp": 5.0},
    )
    assert decision.hvac_mode == "heat"
    assert decision.target_temp == 21.0  # full comfort temp, not eco-setback
    assert "preheating" in decision.reason


def test_preheat_lead_time_grows_when_colder_outside():
    mild = estimate_preheat_minutes(21.0, 17.0, 10.0, 12.0, 10.0, 0.03, 90)
    cold = estimate_preheat_minutes(21.0, 17.0, -5.0, 12.0, 10.0, 0.03, 90)
    assert cold > mild


def test_preheat_lead_time_is_capped():
    lead = estimate_preheat_minutes(30.0, 5.0, -20.0, 12.0, 10.0, 0.03, 45)
    assert lead == 45


def test_no_preheat_needed_once_at_target():
    lead = estimate_preheat_minutes(21.0, 21.0, 5.0, 12.0, 10.0, 0.03, 90)
    assert lead == 0


def test_garmin_alarm_overrides_only_the_first_comfort_block():
    weekplan = weekday_plan(comfort_start="06:30", comfort_temp=21.0)
    # Monday 2026-09-14, alarm set for 05:45, active every weekday.
    alarms = [GarminAlarm(enabled=True, time_of_day=time(5, 45), weekdays={0, 1, 2, 3, 4})]
    now = datetime(2026, 9, 14, 5, 40)
    block = block_for(weekplan, now, alarms)
    # 5:40 is still before the (shifted) 5:45 wake block -> still the overnight eco block.
    assert block["mode"] == "eco"

    now2 = datetime(2026, 9, 14, 5, 50)
    block2 = block_for(weekplan, now2, alarms)
    assert block2["mode"] == "comfort"


def test_garmin_alarm_does_not_affect_weekend_without_that_weekday():
    weekplan = weekday_plan(comfort_start="06:30", comfort_temp=21.0)
    alarms = [GarminAlarm(enabled=True, time_of_day=time(5, 45), weekdays={0, 1, 2, 3, 4})]
    # Saturday 2026-09-19, no alarm configured for Saturday -> falls back to 06:30.
    now = datetime(2026, 9, 19, 6, 0)
    block = block_for(weekplan, now, alarms)
    assert block["mode"] == "eco"


def test_next_comfort_transition_finds_tomorrow_when_today_already_past():
    weekplan = weekday_plan(comfort_start="06:30", comfort_temp=21.0)
    now = datetime(2026, 9, 14, 23, 0)  # Monday night, well past today's comfort start
    result = next_comfort_transition(weekplan, now, [], horizon_minutes=600)
    assert result is not None
    next_dt, block = result
    assert next_dt.date() == datetime(2026, 9, 15).date()
    assert block["mode"] == "comfort"


def test_next_comfort_transition_respects_horizon():
    weekplan = weekday_plan(comfort_start="06:30", comfort_temp=21.0)
    now = datetime(2026, 9, 14, 23, 0)
    result = next_comfort_transition(weekplan, now, [], horizon_minutes=30)
    assert result is None
