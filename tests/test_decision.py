from datetime import datetime, time

from custom_components.tado_schedule.decision import (
    block_for,
    compute_decision,
    compute_wake_decision,
    estimate_preheat_minutes,
    in_heating_season,
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


# ---------- wake sensor (e.g. a bedroom ThermoPro) ----------

WAKE_KWARGS = dict(
    outdoor_forecast_temp=5.0,
    warmup_minutes_per_degree=12.0,
    max_preheat_minutes=90,
    outdoor_baseline_c=10.0,
    outdoor_sensitivity=0.03,
    wake_ready_buffer_minutes=0,
)


def test_wake_sensor_boosts_thermostat_while_bedroom_is_cold():
    alarm_dt = datetime(2026, 9, 14, 6, 30)
    # lead = 12 * (1 + 5*0.03) * (24-18) = 82.8 -> 83 min -> preheat starts 05:07
    now = datetime(2026, 9, 14, 5, 30)
    decision = compute_wake_decision(now, alarm_dt, 18.0, 24.0, 26.0, **WAKE_KWARGS)
    assert decision is not None
    assert decision.target_temp == 26.0  # boost temp, to force a heat call from the living room thermostat
    assert decision.hvac_mode == "heat"
    assert "preheating bedroom" in decision.reason


def test_wake_sensor_holds_target_once_bedroom_is_warm_enough():
    alarm_dt = datetime(2026, 9, 14, 6, 30)
    now = datetime(2026, 9, 14, 6, 15)  # still before the alarm
    decision = compute_wake_decision(now, alarm_dt, 24.5, 24.0, 26.0, **WAKE_KWARGS)
    assert decision is not None
    assert decision.target_temp == 24.0  # holds the wake target, not the boost temp
    assert "holding bedroom" in decision.reason


def test_wake_sensor_stops_applying_once_the_alarm_fires():
    alarm_dt = datetime(2026, 9, 14, 6, 30)
    assert compute_wake_decision(alarm_dt, alarm_dt, 18.0, 24.0, 26.0, **WAKE_KWARGS) is None
    later = datetime(2026, 9, 14, 6, 45)
    assert compute_wake_decision(later, alarm_dt, 18.0, 24.0, 26.0, **WAKE_KWARGS) is None


def test_wake_sensor_does_nothing_before_its_preheat_window_starts():
    alarm_dt = datetime(2026, 9, 14, 6, 30)
    now = datetime(2026, 9, 14, 2, 0)  # far earlier than the ~83 minute lead needs
    assert compute_wake_decision(now, alarm_dt, 18.0, 24.0, 26.0, **WAKE_KWARGS) is None


def test_compute_decision_prefers_wake_sensor_over_visual_schedule_before_alarm():
    weekplan = weekday_plan(comfort_start="06:30", comfort_temp=21.0)
    alarms = [GarminAlarm(enabled=True, time_of_day=time(6, 30), weekdays={0, 1, 2, 3, 4})]
    now = datetime(2026, 9, 14, 6, 0)  # inside the wake preheat window, before the alarm
    decision = compute_decision(
        now,
        weekplan,
        alarms,
        **{
            **BASE_KWARGS,
            "current_indoor_temp": 21.0,  # living room is already fine...
            "wake_sensor_temp": 17.0,  # ...but the bedroom is still cold
            "wake_target_temp": 24.0,
            "wake_boost_temp": 26.0,
        },
    )
    assert decision.target_temp == 26.0
    assert "bedroom" in decision.reason


def test_compute_decision_reverts_to_normal_schedule_after_alarm_fires():
    weekplan = weekday_plan(comfort_start="06:30", comfort_temp=21.0)
    alarms = [GarminAlarm(enabled=True, time_of_day=time(6, 30), weekdays={0, 1, 2, 3, 4})]
    now = datetime(2026, 9, 14, 7, 0)  # after the alarm
    decision = compute_decision(
        now,
        weekplan,
        alarms,
        **{
            **BASE_KWARGS,
            "current_indoor_temp": 21.0,
            "wake_sensor_temp": 17.0,  # bedroom sensor no longer consulted post-alarm
            "wake_target_temp": 24.0,
            "wake_boost_temp": 26.0,
        },
    )
    assert decision.target_temp == 21.0
    assert decision.reason == "scheduled comfort"


def test_away_mode_still_overrides_wake_sensor_preheat():
    weekplan = weekday_plan(comfort_start="06:30", comfort_temp=21.0)
    alarms = [GarminAlarm(enabled=True, time_of_day=time(6, 30), weekdays={0, 1, 2, 3, 4})]
    now = datetime(2026, 9, 14, 6, 0)
    decision = compute_decision(
        now,
        weekplan,
        alarms,
        **{
            **BASE_KWARGS,
            "away_active": True,
            "wake_sensor_temp": 17.0,
            "wake_target_temp": 24.0,
            "wake_boost_temp": 26.0,
        },
    )
    assert decision.reason == "away"
    assert decision.target_temp == BASE_KWARGS["away_temp"]


# ---------- heating season gate + mild-day setback ----------


def test_in_heating_season_handles_wraparound_october_to_april():
    # October through April, wrapping across the year boundary.
    assert in_heating_season(datetime(2026, 1, 15), 10, 4) is True
    assert in_heating_season(datetime(2026, 10, 1), 10, 4) is True
    assert in_heating_season(datetime(2026, 4, 30), 10, 4) is True
    assert in_heating_season(datetime(2026, 7, 15), 10, 4) is False
    assert in_heating_season(datetime(2026, 9, 30), 10, 4) is False


def test_in_heating_season_non_wrapping_range():
    assert in_heating_season(datetime(2026, 3, 1), 2, 5) is True
    assert in_heating_season(datetime(2026, 6, 1), 2, 5) is False


def test_off_season_cold_summer_night_does_not_trigger_heating():
    weekplan = weekday_plan()
    # A chilly August night below every sane instantaneous threshold - must
    # NOT heat, because the calendar gate (not a temperature reading) decides.
    now = datetime(2026, 8, 10, 3, 0)
    decision = compute_decision(
        now,
        weekplan,
        [],
        **{
            **BASE_KWARGS,
            "current_indoor_temp": 19.0,
            "season_start_month": 10,
            "season_end_month": 4,
            "frost_protect_temp": 7.0,
        },
    )
    assert decision.hvac_mode == "off"
    assert decision.reason == "mimo topnou sezónu"


def test_off_season_frost_protection_still_engages():
    weekplan = weekday_plan()
    now = datetime(2026, 8, 10, 3, 0)
    decision = compute_decision(
        now,
        weekplan,
        [],
        **{
            **BASE_KWARGS,
            "current_indoor_temp": 6.0,  # below the frost floor even in August
            "season_start_month": 10,
            "season_end_month": 4,
            "frost_protect_temp": 7.0,
        },
    )
    assert decision.hvac_mode == "heat"
    assert decision.target_temp == 7.0
    assert "frost protection" in decision.reason


def test_in_season_normal_schedule_applies_when_season_configured():
    weekplan = weekday_plan(comfort_start="06:30", comfort_temp=21.0)
    now = datetime(2026, 1, 14, 8, 0)  # January, well inside 10..4
    decision = compute_decision(
        now,
        weekplan,
        [],
        **{
            **BASE_KWARGS,
            "current_indoor_temp": 19.0,
            "season_start_month": 10,
            "season_end_month": 4,
            "frost_protect_temp": 7.0,
        },
    )
    assert decision.hvac_mode == "heat"
    assert decision.target_temp == 21.0
    assert decision.reason == "scheduled comfort"


def test_mild_day_reduces_target_instead_of_skipping():
    weekplan = weekday_plan(comfort_start="06:30", comfort_temp=21.0)
    now = datetime(2026, 3, 14, 8, 0)  # inside season, but a mild March day
    decision = compute_decision(
        now,
        weekplan,
        [],
        **{
            **BASE_KWARGS,
            "current_indoor_temp": 19.0,
            "outdoor_forecast_temp": 18.0,
            "season_start_month": 10,
            "season_end_month": 4,
            "mild_outdoor_threshold": 16.0,
            "mild_setback": 3.0,
        },
    )
    assert decision.hvac_mode == "heat"
    assert decision.target_temp == 18.0  # 21 - 3
    assert "mírný den" in decision.reason


def test_mild_day_and_eco_do_not_stack():
    weekplan = weekday_plan(comfort_start="06:30", comfort_temp=21.0)
    now = datetime(2026, 3, 14, 8, 0)
    decision = compute_decision(
        now,
        weekplan,
        [],
        **{
            **BASE_KWARGS,
            "eco_active": True,
            "eco_setback": 2.0,
            "current_indoor_temp": 19.0,
            "outdoor_forecast_temp": 18.0,
            "season_start_month": 10,
            "season_end_month": 4,
            "mild_outdoor_threshold": 16.0,
            "mild_setback": 3.0,
        },
    )
    # mild (3) beats eco (2) - only the larger setback applies, not both.
    assert decision.target_temp == 18.0


def test_cold_day_in_season_does_not_get_mild_setback():
    weekplan = weekday_plan(comfort_start="06:30", comfort_temp=21.0)
    now = datetime(2026, 1, 14, 8, 0)
    decision = compute_decision(
        now,
        weekplan,
        [],
        **{
            **BASE_KWARGS,
            "current_indoor_temp": 19.0,
            "outdoor_forecast_temp": 2.0,
            "season_start_month": 10,
            "season_end_month": 4,
            "mild_outdoor_threshold": 16.0,
            "mild_setback": 3.0,
        },
    )
    assert decision.target_temp == 21.0
    assert "mírný den" not in decision.reason


def test_season_gate_skipped_when_not_configured():
    # Existing behaviour (no season kwargs passed) must be untouched.
    weekplan = weekday_plan(comfort_start="06:30", comfort_temp=21.0)
    now = datetime(2026, 8, 10, 3, 0)
    decision = compute_decision(now, weekplan, [], **BASE_KWARGS)
    assert decision.hvac_mode == "heat"
