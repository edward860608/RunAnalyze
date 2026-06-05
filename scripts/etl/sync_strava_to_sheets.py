#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Strava -> Google Sheets (append / insert-only) daily sync

This script **does NOT overwrite** existing Google Sheets data.
It reads what's currently in your sheets and only inserts NEW activities.

Key behavior
- Uses Strava refresh token to obtain an access token
- Reads existing `runs` and `run_splits` tabs to build sets of existing run_ids
- Detects new runs by run_id; only new runs are inserted
- Inserts new rows at the top (row 2), so the newest activities stay on top
- Builds run_splits from `/activities/{id}/laps`
  - distance = actual lap distance (km)
  - km = lap index (1,2,3,...) (not necessarily kilometer number)
- Cadence normalized to SPM (3-digit) by doubling if Strava returns single-leg cadence (<120)

Notes
- This is **append/insert-only**. If you edit an activity on Strava, this script will NOT update
  existing rows in your sheet; it will only add new ones.
"""

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import pandas as pd
from dotenv import load_dotenv

import gspread
from google.oauth2.service_account import Credentials

# =========================
# Load .env
# =========================
load_dotenv()

TZ = ZoneInfo("Asia/Taipei")
STRAVA_API_BASE = "https://www.strava.com/api/v3"

LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "30"))  # a bit larger is safer for late sync

# Throttle for laps requests
SLEEP_EVERY_N = int(os.getenv("SLEEP_EVERY_N", "10"))
SLEEP_SECONDS = float(os.getenv("SLEEP_SECONDS", "1.0"))

# Sheets/tabs
RUNS_TAB = os.getenv("RUNS_SHEET_NAME", "runs")
SPLITS_TAB = os.getenv("SPLITS_SHEET_NAME", "run_splits")

# Output columns
RUNS_COLS = [
    "run_id", "name", "type", "sport_type",
    "start_datetime_local", "end_datetime_local",
    "distance_km", "moving_time_min_str", "avg_pace_str",
    "avg_heart_rate_bpm", "max_heart_rate_bpm", "avg_cadence_spm",
    "shoes",
]

SPLITS_COLS = [
    "run_id", "name", "type", "sport_type",
    "start_datetime_local", "end_datetime_local",
    "moving_time_min_str", "distance_km",
    "distance", "km", "pace_str",
    "avg_heart_rate_bpm", "avg_cadence_spm",
    "shoes",
]

# =========================
# Env helpers
# =========================

def getenv_stripped(key: str, default: str = "") -> str:
    v = os.getenv(key)
    if v is None:
        return default
    return str(v).strip()


def get_spreadsheet_id() -> str:
    sid = getenv_stripped("SPREADSHEET_ID")
    if not sid:
        sid = getenv_stripped("GSHEET_SPREADSHEET_ID")
    return sid.replace(" ", "")


def get_service_account_json_path() -> str:
    p = getenv_stripped("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not p:
        p = getenv_stripped("GSHEET_SERVICE_ACCOUNT_JSON")
    if not p:
        return ""
    if not os.path.isabs(p):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        p = os.path.join(script_dir, p)
    return p


# =========================
# Strava OAuth (Refresh token)
# =========================

def refresh_strava_access_token() -> dict:
    client_id = getenv_stripped("STRAVA_CLIENT_ID")
    client_secret = getenv_stripped("STRAVA_CLIENT_SECRET")
    refresh_token = getenv_stripped("STRAVA_REFRESH_TOKEN")

    if not (client_id and client_secret and refresh_token):
        raise RuntimeError(
            "Missing .env vars: STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN"
        )

    url = "https://www.strava.com/oauth/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    r = requests.post(url, data=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def strava_get(access_token: str, endpoint: str, params=None):
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(STRAVA_API_BASE + endpoint, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


# =========================
# Gear (Shoes) helpers
# =========================

GEAR_CACHE: dict[str, str] = {}


def fetch_gear_name(access_token: str, gear_id: str) -> str:
    gear_id = (gear_id or "").strip()
    if not gear_id:
        return ""
    if gear_id in GEAR_CACHE:
        return GEAR_CACHE[gear_id]
    data = strava_get(access_token, f"/gear/{gear_id}")
    name = (data.get("name") or "").strip()
    GEAR_CACHE[gear_id] = name
    return name


# =========================
# Metric + formatting helpers
# =========================

def cadence_to_spm(cad):
    if cad is None or cad == "":
        return ""
    try:
        cad = float(cad)
    except Exception:
        return ""
    cad = cad * 2 if cad < 120 else cad
    if abs(cad - round(cad)) < 1e-6:
        return str(int(round(cad)))
    return str(round(cad, 1))


def sec_to_hhmmss(sec) -> str:
    if sec is None or sec == "":
        return ""
    sec = int(round(float(sec)))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def sec_to_mmss(sec) -> str:
    if sec is None or sec == "":
        return ""
    sec = float(sec)
    m = int(sec // 60)
    s = int(round(sec % 60))
    return f"{m:02d}:{s:02d}"


def start_dt_local_naive(activity: dict):
    s = activity.get("start_date_local")
    if not s:
        return None
    dt = pd.to_datetime(s, errors="coerce")
    if pd.isna(dt):
        return None
    return dt.to_pydatetime()  # naive local


def end_dt_local_naive(activity: dict):
    sdt = start_dt_local_naive(activity)
    if sdt is None:
        return None
    elapsed = activity.get("elapsed_time") or 0
    try:
        elapsed = int(elapsed)
    except Exception:
        elapsed = 0
    return sdt + pd.to_timedelta(elapsed, unit="s")


def format_dt_local_naive(dt):
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# =========================
# Build rows from Strava summary + laps
# =========================

def runs_row_from_summary(activity_summary: dict, access_token: str) -> dict | None:
    if activity_summary.get("type") != "Run":
        return None

    dist_km = (activity_summary.get("distance") or 0) / 1000.0
    moving_sec = activity_summary.get("moving_time") or 0
    if dist_km <= 0:
        return None

    sdt = start_dt_local_naive(activity_summary)
    edt = end_dt_local_naive(activity_summary)
    avg_pace_sec = (moving_sec / dist_km) if dist_km > 0 else None

    gear_id = activity_summary.get("gear_id")
    shoes = fetch_gear_name(access_token, gear_id) if gear_id else ""

    avg_hr = activity_summary.get("average_heartrate")
    max_hr = activity_summary.get("max_heartrate")

    return {
        "run_id": str(activity_summary.get("id") or ""),
        "name": (activity_summary.get("name") or ""),
        "type": (activity_summary.get("type") or ""),
        "sport_type": (activity_summary.get("sport_type") or ""),
        "start_datetime_local": format_dt_local_naive(sdt),
        "end_datetime_local": format_dt_local_naive(edt),
        "distance_km": f"{dist_km:.2f}",
        "moving_time_min_str": sec_to_hhmmss(moving_sec),
        "avg_pace_str": sec_to_mmss(avg_pace_sec),
        "avg_heart_rate_bpm": "" if avg_hr is None else str(avg_hr),
        "max_heart_rate_bpm": "" if max_hr is None else str(max_hr),
        "avg_cadence_spm": cadence_to_spm(activity_summary.get("average_cadence")),
        "shoes": shoes,
    }


def fetch_activity_laps(access_token: str, run_id: int):
    return strava_get(access_token, f"/activities/{run_id}/laps")


def splits_rows_from_laps(activity_summary: dict, laps: list[dict], access_token: str) -> list[dict]:
    run_row = runs_row_from_summary(activity_summary, access_token)
    if run_row is None or not laps:
        return []

    rows: list[dict] = []
    lap_idx = 0
    for lap in laps:
        lap_dist_m = lap.get("distance") or 0
        lap_moving = lap.get("moving_time") or lap.get("elapsed_time") or 0
        if lap_dist_m <= 0:
            continue

        lap_idx += 1
        lap_dist_km = lap_dist_m / 1000.0
        pace_sec = (lap_moving / lap_dist_km) if lap_dist_km > 0 else None

        rows.append({
            "run_id": run_row["run_id"],
            "name": run_row["name"],
            "type": run_row["type"],
            "sport_type": run_row["sport_type"],
            "start_datetime_local": run_row["start_datetime_local"],
            "end_datetime_local": run_row["end_datetime_local"],
            "moving_time_min_str": run_row["moving_time_min_str"],
            "distance_km": run_row["distance_km"],
            "distance": f"{lap_dist_km:.3f}",
            "km": str(lap_idx),
            "pace_str": sec_to_mmss(pace_sec),
            "avg_heart_rate_bpm": "" if lap.get("average_heartrate") is None else str(lap.get("average_heartrate")),
            "avg_cadence_spm": cadence_to_spm(lap.get("average_cadence")),
            "shoes": run_row["shoes"],
        })

    return rows


# =========================
# Strava fetch (activities after)
# =========================

def local_string_to_epoch_seconds(local_str: str) -> int:
    dt = pd.to_datetime(local_str, errors="coerce")
    if pd.isna(dt):
        return 0
    dt = dt.to_pydatetime().replace(tzinfo=TZ)
    return int(dt.timestamp())


def list_activities_after(access_token: str, after_epoch: int) -> list[dict]:
    results = []
    page = 1
    per_page = 200
    while True:
        params = {"after": after_epoch, "page": page, "per_page": per_page}
        batch = strava_get(access_token, "/athlete/activities", params=params)
        if not batch:
            break
        results.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
        time.sleep(0.2)
    return results


# =========================
# Google Sheets helpers (append/insert)
# =========================

def get_gspread_spreadsheet():
    json_path = get_service_account_json_path()
    spreadsheet_id = get_spreadsheet_id()

    if not json_path:
        raise RuntimeError("Missing .env: GOOGLE_SERVICE_ACCOUNT_JSON")
    if not spreadsheet_id:
        raise RuntimeError("Missing .env: SPREADSHEET_ID")
    if not os.path.exists(json_path):
        raise RuntimeError(f"Service account json not found: {json_path}")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(json_path, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc.open_by_key(spreadsheet_id)


def ensure_worksheet(ss, title: str, rows=2000, cols=30):
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        return ss.add_worksheet(title=title, rows=str(rows), cols=str(cols))


def ensure_header(ws, cols: list[str]):
    values = ws.get_all_values()
    if not values:
        ws.update([cols], value_input_option="USER_ENTERED")
        return cols

    header = values[0]
    if header != cols:
        # If header differs, keep existing but try to align by updating header row
        ws.update([cols], value_input_option="USER_ENTERED")
        header = cols
    return header


def sheet_existing_run_ids_and_latest_dt(ws, run_id_col: str = "run_id", dt_col: str = "start_datetime_local"):
    values = ws.get_all_values()
    if not values or len(values) < 2:
        return set(), None

    header = values[0]
    idx_run = header.index(run_id_col) if run_id_col in header else None
    idx_dt = header.index(dt_col) if dt_col in header else None

    run_ids = set()
    latest_dt = None

    for row in values[1:]:
        if idx_run is not None and idx_run < len(row):
            rid = str(row[idx_run]).strip()
            if rid:
                run_ids.add(rid)
        if idx_dt is not None and idx_dt < len(row):
            s = str(row[idx_dt]).strip()
            if s:
                dt = pd.to_datetime(s, errors="coerce")
                if not pd.isna(dt):
                    if latest_dt is None or dt > latest_dt:
                        latest_dt = dt

    return run_ids, (latest_dt.strftime("%Y-%m-%d %H:%M:%S") if latest_dt is not None else None)


def insert_rows_top(ws, cols: list[str], row_dicts: list[dict]):
    if not row_dicts:
        return
    # keep column order
    rows = [["" if d.get(c) is None else str(d.get(c)) for c in cols] for d in row_dicts]
    # insert right below header
    ws.insert_rows(rows, row=2, value_input_option="USER_ENTERED")


# =========================
# Main
# =========================

def main():
    # 0) connect sheets early (so we use existing as source of truth)
    ss = get_gspread_spreadsheet()
    ws_runs = ensure_worksheet(ss, RUNS_TAB, rows=2000, cols=max(20, len(RUNS_COLS) + 2))
    ws_splits = ensure_worksheet(ss, SPLITS_TAB, rows=5000, cols=max(30, len(SPLITS_COLS) + 2))

    ensure_header(ws_runs, RUNS_COLS)
    ensure_header(ws_splits, SPLITS_COLS)

    existing_run_ids, latest_dt_str = sheet_existing_run_ids_and_latest_dt(ws_runs)

    # 1) token
    token_info = refresh_strava_access_token()
    access_token = token_info["access_token"]

    # 2) compute after_epoch based on existing sheet (latest start_datetime)
    now_epoch = int(datetime.now(TZ).timestamp())
    lookback_epoch = now_epoch - LOOKBACK_DAYS * 86400

    if latest_dt_str:
        latest_epoch = local_string_to_epoch_seconds(latest_dt_str) - 60
        after_epoch = min(latest_epoch, lookback_epoch)  # go earlier to catch late sync
    else:
        after_epoch = lookback_epoch

    # 3) fetch candidate activities
    activities = list_activities_after(access_token, after_epoch)

    new_runs: list[dict] = []
    new_splits: list[dict] = []
    laps_calls = 0

    for a in activities:
        rid = a.get("id")
        if rid is None:
            continue

        run_row = runs_row_from_summary(a, access_token)
        if run_row is None:
            continue

        rid_str = run_row["run_id"]
        if rid_str in existing_run_ids:
            continue  # already in sheet

        # New run
        new_runs.append(run_row)
        existing_run_ids.add(rid_str)  # prevent duplicates within same run

        # Splits (laps)
        laps = fetch_activity_laps(access_token, int(rid))
        laps_calls += 1
        split_rows = splits_rows_from_laps(a, laps, access_token)
        # within each run, keep km asc (already)
        new_splits.extend(split_rows)

        if laps_calls % max(1, SLEEP_EVERY_N) == 0:
            time.sleep(SLEEP_SECONDS)

    # 4) sort so newest stays on top
    def _dt_key(d):
        return pd.to_datetime(d.get("start_datetime_local", ""), errors="coerce")

    new_runs_sorted = sorted(new_runs, key=_dt_key, reverse=True)

    # For splits, sort by run start desc, then run_id, then km numeric asc
    # Build run_id -> start dt mapping from new_runs
    run_start_map = {d["run_id"]: _dt_key(d) for d in new_runs}

    def _split_sort_key(d):
        dt = run_start_map.get(d.get("run_id"), pd.Timestamp.min)
        km = pd.to_numeric(d.get("km"), errors="coerce")
        if pd.isna(km):
            km = 1e18
        return (-dt.value if not pd.isna(dt) else 0, str(d.get("run_id")), km)

    new_splits_sorted = sorted(new_splits, key=_split_sort_key)

    # 5) insert into sheets (top)
    insert_rows_top(ws_runs, RUNS_COLS, new_runs_sorted)
    insert_rows_top(ws_splits, SPLITS_COLS, new_splits_sorted)

    now_str = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    print(
        f"{now_str} | inserted runs: {len(new_runs_sorted)}, inserted splits: {len(new_splits_sorted)}, "
        f"laps_calls: {laps_calls}, after_epoch: {after_epoch}"
    )


if __name__ == "__main__":
    main()
