from __future__ import annotations

from pathlib import Path

import pandas as pd

try:
    import streamlit as st
except ModuleNotFoundError:
    st = None

from src.runanalyze.config import get_settings


ROOT_DIR = Path(__file__).resolve().parents[2]
SAMPLE_DIR = ROOT_DIR / "sample_data"


RUN_COLUMNS = [
    "run_id",
    "name",
    "type",
    "sport_type",
    "start_datetime_local",
    "end_datetime_local",
    "distance_km",
    "moving_time_min_str",
    "avg_pace_str",
    "avg_heart_rate_bpm",
    "max_heart_rate_bpm",
    "avg_cadence_spm",
    "shoes",
]

SPLIT_COLUMNS = [
    "run_id",
    "name",
    "type",
    "sport_type",
    "start_datetime_local",
    "end_datetime_local",
    "moving_time_min_str",
    "distance_km",
    "distance",
    "km",
    "pace_str",
    "avg_heart_rate_bpm",
    "avg_cadence_spm",
    "shoes",
]


def load_run_data() -> tuple[pd.DataFrame, pd.DataFrame, str]:
    settings = get_settings()
    if settings.data_source == "google_sheets" and settings.service_account_info:
        try:
            runs_df, splits_df = _load_from_google_sheets()
            return _normalize_runs(runs_df), _normalize_splits(splits_df), "Google Sheets"
        except Exception as exc:
            if st is not None:
                st.warning(f"Google Sheets load failed, using sample data instead: {exc}")

    runs_df = pd.read_csv(SAMPLE_DIR / "runs_df.csv")
    splits_df = pd.read_csv(SAMPLE_DIR / "splits_df.csv")
    return _normalize_runs(runs_df), _normalize_splits(splits_df), "Sample data"


if st is not None:
    load_run_data = st.cache_data(ttl=900)(load_run_data)


def _load_from_google_sheets() -> tuple[pd.DataFrame, pd.DataFrame]:
    import gspread
    from google.oauth2.service_account import Credentials

    settings = get_settings()
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    credentials = Credentials.from_service_account_info(
        settings.service_account_info,
        scopes=scopes,
    )
    client = gspread.authorize(credentials)
    sheet = (
        client.open_by_key(settings.spreadsheet_id)
        if settings.spreadsheet_id
        else client.open(settings.sheet_name)
    )

    runs = sheet.worksheet(settings.runs_worksheet).get_all_records()
    splits = sheet.worksheet(settings.splits_worksheet).get_all_records()
    return pd.DataFrame(runs), pd.DataFrame(splits)


def _normalize_runs(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = _rename_aliases(df)
    for column in RUN_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA

    df["start_datetime_local"] = pd.to_datetime(df["start_datetime_local"], errors="coerce")
    df["end_datetime_local"] = pd.to_datetime(df["end_datetime_local"], errors="coerce")
    df["distance_km"] = pd.to_numeric(df["distance_km"], errors="coerce").fillna(0)
    df["avg_heart_rate_bpm"] = pd.to_numeric(df["avg_heart_rate_bpm"], errors="coerce")
    df["max_heart_rate_bpm"] = pd.to_numeric(df["max_heart_rate_bpm"], errors="coerce")
    df["avg_cadence_spm"] = pd.to_numeric(df["avg_cadence_spm"], errors="coerce")
    return df.dropna(subset=["start_datetime_local"]).sort_values(
        "start_datetime_local",
        ascending=False,
    )


def _normalize_splits(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = _rename_aliases(df)
    for column in SPLIT_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA

    df["start_datetime_local"] = pd.to_datetime(df["start_datetime_local"], errors="coerce")
    df["distance_km"] = pd.to_numeric(df["distance_km"], errors="coerce").fillna(0)
    df["km"] = pd.to_numeric(df["km"], errors="coerce")
    df["distance"] = pd.to_numeric(df["distance"], errors="coerce")
    df["avg_heart_rate_bpm"] = pd.to_numeric(df["avg_heart_rate_bpm"], errors="coerce")
    df["avg_cadence_spm"] = pd.to_numeric(df["avg_cadence_spm"], errors="coerce")
    return df.dropna(subset=["start_datetime_local"]).sort_values(
        ["start_datetime_local", "km"],
        ascending=[False, True],
    )


def _rename_aliases(df: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "moving_time_str": "moving_time_min_str",
        "avg_heart_rate": "avg_heart_rate_bpm",
        "heart_rate": "avg_heart_rate_bpm",
        "avg_cadence": "avg_cadence_spm",
        "cadence": "avg_cadence_spm",
    }
    return df.rename(columns={old: new for old, new in aliases.items() if old in df.columns})
