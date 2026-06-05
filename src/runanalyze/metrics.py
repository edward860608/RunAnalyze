from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


def parse_pace_to_minutes(pace: object) -> float | None:
    if pd.isna(pace):
        return None

    text = str(pace).strip()
    if not text or ":" not in text:
        return None

    minutes, seconds = text.split(":", maxsplit=1)
    try:
        return int(minutes) + int(seconds) / 60
    except ValueError:
        return None


def add_run_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["run_date"] = df["start_datetime_local"].dt.date
    df["week_start"] = df["start_datetime_local"].dt.to_period("W-SUN").dt.start_time
    df["month_start"] = df["start_datetime_local"].dt.to_period("M").dt.start_time
    df["pace_min_per_km"] = df["avg_pace_str"].map(parse_pace_to_minutes)
    return df


def latest_run(df: pd.DataFrame) -> pd.Series:
    return df.sort_values("start_datetime_local", ascending=False).iloc[0]


def weekly_mileage(df: pd.DataFrame, today: date | None = None) -> float:
    today = today or date.today()
    start = today - timedelta(days=today.weekday())
    return df[df["run_date"] >= start]["distance_km"].sum()


def monthly_mileage(df: pd.DataFrame, today: date | None = None) -> float:
    today = today or date.today()
    start = today.replace(day=1)
    return df[df["run_date"] >= start]["distance_km"].sum()


def current_streak(df: pd.DataFrame, today: date | None = None) -> int:
    today = today or date.today()
    run_dates = set(df["run_date"].dropna())
    cursor = today

    if cursor not in run_dates:
        cursor = today - timedelta(days=1)

    streak = 0
    while cursor in run_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def format_pace(minutes: float | None) -> str:
    if minutes is None or pd.isna(minutes):
        return "-"
    whole_minutes = int(minutes)
    seconds = round((minutes - whole_minutes) * 60)
    return f"{whole_minutes}:{seconds:02d}/km"


def format_distance(km: float | None) -> str:
    if km is None or pd.isna(km):
        return "-"
    return f"{km:.1f} km"
