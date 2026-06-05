from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv() -> bool:
        return False

try:
    import streamlit as st
except ModuleNotFoundError:
    st = None


load_dotenv()


@dataclass(frozen=True)
class Settings:
    data_source: str
    spreadsheet_id: str
    sheet_name: str
    runs_worksheet: str
    splits_worksheet: str
    service_account_info: dict[str, Any] | None


def _secret_or_env(name: str, default: str = "") -> str:
    if st is None:
        return os.getenv(name, default)

    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.getenv(name, default))


def _service_account_info() -> dict[str, Any] | None:
    raw_value = _secret_or_env("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw_value:
        return None

    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return None


def get_settings() -> Settings:
    return Settings(
        data_source=_secret_or_env("RUNANALYZE_DATA_SOURCE", "sample").lower(),
        spreadsheet_id=_secret_or_env("SPREADSHEET_ID") or _secret_or_env("GSHEET_SPREADSHEET_ID"),
        sheet_name=_secret_or_env("GOOGLE_SHEET_NAME", "RunAnalyze"),
        runs_worksheet=_secret_or_env("GOOGLE_RUNS_WORKSHEET", "runs"),
        splits_worksheet=_secret_or_env("GOOGLE_SPLITS_WORKSHEET", "run_splits"),
        service_account_info=_service_account_info(),
    )
