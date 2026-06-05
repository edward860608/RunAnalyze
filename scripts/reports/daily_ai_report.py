import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv

import gspread
from google.oauth2.service_account import Credentials

import smtplib
from email.message import EmailMessage


# =========================
# Config
# =========================
load_dotenv()
TZ = ZoneInfo("Asia/Taipei")

# Sheets
RUNS_SHEET_NAME = os.getenv("RUNS_SHEET_NAME", "runs")
SPLITS_SHEET_NAME = os.getenv("SPLITS_SHEET_NAME", "run_splits")

GOOGLE_SERVICE_ACCOUNT_JSON = (os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or "").strip()
SPREADSHEET_ID = (os.getenv("SPREADSHEET_ID") or "").strip().replace(" ", "")

# OpenAI (AI coach)
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")  # you can change later
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.4"))

# Email (SMTP)
SMTP_HOST = (os.getenv("SMTP_HOST") or "smtp.gmail.com").strip()
SMTP_PORT = int((os.getenv("SMTP_PORT") or "587").strip())
SMTP_USER = (os.getenv("SMTP_USER") or "").strip()
SMTP_APP_PASSWORD = (os.getenv("SMTP_APP_PASSWORD") or "").strip()

REPORT_TO_EMAIL = (os.getenv("REPORT_TO_EMAIL") or "").strip()
REPORT_FROM_EMAIL = (os.getenv("REPORT_FROM_EMAIL") or SMTP_USER).strip()
REPORT_SUBJECT_PREFIX = (os.getenv("REPORT_SUBJECT_PREFIX") or "[Running Daily]").strip()

# Report selection
RECENT_N_RUNS = int(os.getenv("REPORT_RECENT_N_RUNS", "6"))      # latest + previous 5
LOOKBACK_DAYS = int(os.getenv("REPORT_LOOKBACK_DAYS", "60"))     # pull this many days from sheet to find latest runs
MAX_SPLITS_PER_RUN = int(os.getenv("REPORT_MAX_SPLITS_PER_RUN", "40"))  # cap prompt size


# =========================
# Utilities
# =========================
def _resolve_path(p: str) -> str:
    if not p:
        return ""
    if os.path.isabs(p):
        return p
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, p)


def _parse_dt_local_naive(s: str):
    """
    runs sheet stores start_datetime_local as 'YYYY-MM-DD HH:MM:SS' local time (naive).
    We'll parse and attach Asia/Taipei tz for comparisons only.
    """
    dt = pd.to_datetime(s, errors="coerce")
    if pd.isna(dt):
        return None
    py = dt.to_pydatetime()
    return py.replace(tzinfo=TZ)


def _safe_str(x) -> str:
    if x is None:
        return ""
    return str(x).strip()


def _safe_float(x):
    try:
        if x is None or str(x).strip() == "":
            return None
        return float(x)
    except Exception:
        return None


def _pace_str_to_seconds(p: str):
    """
    'MM:SS' -> int seconds
    """
    p = _safe_str(p)
    if ":" not in p:
        return None
    try:
        mm, ss = p.split(":")
        return int(mm) * 60 + int(ss)
    except Exception:
        return None


def _seconds_to_pace_str(sec: float):
    if sec is None:
        return ""
    try:
        sec = int(round(float(sec)))
    except Exception:
        return ""
    mm = sec // 60
    ss = sec % 60
    return f"{mm:02d}:{ss:02d}"


def _hhmmss_to_seconds(hhmmss: str):
    """
    'HH:MM:SS' -> seconds
    """
    s = _safe_str(hhmmss)
    parts = s.split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, sec = parts
        return int(h) * 3600 + int(m) * 60 + int(sec)
    except Exception:
        return None


def _seconds_to_hhmmss(sec: float):
    if sec is None:
        return ""
    try:
        sec = int(round(float(sec)))
    except Exception:
        return ""
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


# =========================
# Google Sheets
# =========================
def _get_spreadsheet():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("Missing .env: GOOGLE_SERVICE_ACCOUNT_JSON")
    if not SPREADSHEET_ID:
        raise RuntimeError("Missing .env: SPREADSHEET_ID")

    json_path = _resolve_path(GOOGLE_SERVICE_ACCOUNT_JSON)
    if not os.path.exists(json_path):
        raise RuntimeError(f"Service account json not found: {json_path}")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(json_path, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID)


def _sheet_to_df(ws) -> pd.DataFrame:
    values = ws.get_all_values()
    if not values or len(values) < 2:
        return pd.DataFrame()
    header = values[0]
    rows = values[1:]
    return pd.DataFrame(rows, columns=header)


# =========================
# Email (SMTP)
# =========================
def _send_email(subject: str, body: str):
    # Validate required env vars
    missing = []
    if not SMTP_USER:
        missing.append("SMTP_USER")
    if not SMTP_APP_PASSWORD:
        missing.append("SMTP_APP_PASSWORD")
    if not REPORT_TO_EMAIL:
        missing.append("REPORT_TO_EMAIL")
    if not REPORT_FROM_EMAIL:
        missing.append("REPORT_FROM_EMAIL")

    if missing:
        raise RuntimeError("Missing .env email vars: " + ", ".join(missing))

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = REPORT_FROM_EMAIL
    msg["To"] = REPORT_TO_EMAIL
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_APP_PASSWORD)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise RuntimeError(
            "SMTPAuthenticationError: Gmail rejected credentials. "
            "Use a Gmail App Password (16 chars) with 2-Step Verification enabled, "
            "and ensure SMTP_USER matches the Gmail account that created the App Password."
        ) from e

# =========================
# AI Coach (OpenAI)
# =========================
def _call_openai(system_prompt: str, user_prompt: str) -> str:
    """
    Uses OpenAI Python SDK v1.x style: from openai import OpenAI
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("Missing .env: OPENAI_API_KEY")

    try:
        from openai import OpenAI
    except Exception as e:
        raise RuntimeError(
            "OpenAI SDK not installed or import failed. Install with: pip install openai"
        ) from e

    client = OpenAI(api_key=OPENAI_API_KEY)

    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=OPENAI_TEMPERATURE,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    text = resp.choices[0].message.content
    return text.strip() if text else ""


# =========================
# Data selection
# =========================
def _select_recent_runs_and_splits(runs_df: pd.DataFrame, splits_df: pd.DataFrame):
    """
    Returns:
      - recent_runs_df (latest N)
      - recent_splits_df (splits for those runs, capped)
      - did_run_report_day (bool)
      - latest_run_row (Series)
    """
    if runs_df.empty:
        return pd.DataFrame(), pd.DataFrame(), False, None

    df = runs_df.copy()

    if "start_datetime_local" not in df.columns:
        raise RuntimeError("runs sheet missing column: start_datetime_local")

    df["_dt"] = df["start_datetime_local"].apply(_parse_dt_local_naive)
    df = df.dropna(subset=["_dt"]).sort_values("_dt").reset_index(drop=True)

    # optional lookback window to reduce noise
    cutoff = datetime.now(TZ) - timedelta(days=LOOKBACK_DAYS)
    df = df[df["_dt"] >= cutoff].reset_index(drop=True)

    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), False, None

    # ===== 報表日期：昨天 =====
    report_date = (datetime.now(TZ) - timedelta(days=1)).date()

    recent = df.tail(RECENT_N_RUNS).copy()
    latest = recent.tail(1).iloc[0]

    # ===== 判斷昨天是否有跑步 =====
    did_run_report_day = any(
        row_dt.date() == report_date
        for row_dt in df["_dt"]
    )

    # filter splits for these run_ids
    run_ids = set(recent["run_id"].astype(str).tolist())

    sp = splits_df.copy()

    if sp.empty or "run_id" not in sp.columns:
        sp = pd.DataFrame()
    else:
        sp = sp[sp["run_id"].astype(str).isin(run_ids)].copy()

    # Sort splits within each run_id by km
    if not sp.empty:
        sp["km_num"] = pd.to_numeric(sp.get("km", ""), errors="coerce")
        sp["_dt"] = sp.get("start_datetime_local", "").apply(_parse_dt_local_naive)

        sp = (
            sp.sort_values(["_dt", "run_id", "km_num"])
            .drop(columns=["_dt", "km_num"], errors="ignore")
            .reset_index(drop=True)
        )

        # Cap splits per run to keep prompt small
        capped_rows = []

        for rid in run_ids:
            sub = sp[sp["run_id"].astype(str) == str(rid)].head(MAX_SPLITS_PER_RUN)
            capped_rows.append(sub)

        sp = pd.concat(capped_rows, ignore_index=True) if capped_rows else pd.DataFrame()

    # drop helper column in recent
    recent = recent.drop(columns=["_dt"], errors="ignore")

    return recent, sp, did_run_report_day, latest


def _build_payload(recent_runs_df: pd.DataFrame, recent_splits_df: pd.DataFrame, did_run_today: bool):
    """
    Create a compact JSON payload for the model.
    """
    def row_to_dict(r):
        return {
            "run_id": _safe_str(r.get("run_id")),
            "name": _safe_str(r.get("name")),
            "sport_type": _safe_str(r.get("sport_type")),
            "start_datetime_local": _safe_str(r.get("start_datetime_local")),
            "end_datetime_local": _safe_str(r.get("end_datetime_local")),
            "distance_km": _safe_str(r.get("distance_km")),
            "moving_time_min_str": _safe_str(r.get("moving_time_min_str")),
            "avg_pace_str": _safe_str(r.get("avg_pace_str")),
            "avg_heart_rate_bpm":_safe_str(r.get("avg_heart_rate_bpm")),
            "avg_cadence_spm":_safe_str(r.get("avg_cadence_spm"))
        }

    runs = [row_to_dict(r) for _, r in recent_runs_df.iterrows()]

    splits = []
    if not recent_splits_df.empty:
        for _, s in recent_splits_df.iterrows():
            splits.append({
                "run_id": _safe_str(s.get("run_id")),
                "km": _safe_str(s.get("km")),
                "pace_str": _safe_str(s.get("pace_str")),
                "distance": _safe_str(s.get("distance")),
                "avg_heart_rate_bpm":_safe_str(s.get("avg_heart_rate_bpm")),
                "avg_cadence_spm":_safe_str(s.get("avg_cadence_spm"))
            })

    payload = {
        "meta": {
            "generated_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
            "timezone": "Asia/Taipei",
            "did_run_today": did_run_today,
            "recent_runs_count": len(runs),
            "recent_splits_count": len(splits),
        },
        "recent_runs_latest_to_oldest": list(reversed(runs)),  # make it easy: latest first
        "recent_splits_for_these_runs": splits,
        "goal": {
            "race": "half_marathon",
            "priority": "finish",
            "notes": "Provide short-term (1-2 weeks) and mid-term (3-6 weeks) training guidance.",
        },
        "constraints": {
            "tone": "rational coach, honest, supportive",
            "length": "medium",
            "language": "zh-Hant",
        }
    }
    return payload


# =========================
# Prompt (A / B / A)
# =========================
SYSTEM_PROMPT = """你是一位專業跑步教練與運動科學顧問，擅長以數據做理性分析，但表達方式仍溫和、支持與務實。
你會避免套公式式的僵硬建議，而是根據資料脈絡（距離、配速、分段、近期趨勢、可能疲勞）做判斷。

重要規則：
- 不要捏造不存在的數據（例如心率、坡度、體重等）。
- 若資料不足，要明確說明「缺什麼」以及「用現有資訊能推到哪裡」。
- 若今天沒有跑步，也要用最近幾次的表現給出有建設性的建議與鼓勵。
- 請用繁體中文輸出。
"""

USER_PROMPT_TEMPLATE = """請根據我提供的跑步資料(runs+run_splits)，生成一份「跑步日報」寄信用內容。你的角色是理性分析型教練（語氣支持、務實，中等篇幅）。

分析範圍固定包含：
1) 最新一次跑步活動表現，搭配前面幾次跑步表現：一開始先以跑步分圈數據判斷是哪種類型的跑步目標（如LSD、Tempo、間歇跑、長跑、easy等），評論是否進步/退步或狀態波動，並綜合訓練時間、速度、距離、分段配速（若有）給建議與評價。
2) 針對最新一次跑步活動：將分段數據（km pace heartrate cadence）進行列表並簡單分析，判斷數據是否穩定、前後段落差，並給出可能原因與建議。
3) 半馬目標（以完賽為主，目標sub2；目前PB：2:12:12 ）：提供合理推估與訓練建議，包含短期（1–2 週）與中期（3–6 週）的調整方向，並給出可行策略（如跑走策略、補給安排等）。
4) 我的身材條件：身高182cm；體重約85kg上下

輸出格式建議（可微調但請保持清晰）：
- 今日摘要（1–3 行）
- 1) 最新一次 + 近期趨勢：趨勢判讀與重點觀察（條列 + 簡短解釋），也需要講解分段配速狀況（若有）。
- 2) 最新一次的 split 列表 + 穩定度/前後段差異分析 + 原因與建議
- 3) 半馬：完賽推估（給合理挑戰目標與區間）+ 短期建議 + 中期建議 + 策略建議
- 明日/下次跑步建議：給一個具體可執行安排（easy/休息/短間歇/長跑/LSD/TEMPO擇一並說原因），可提供鞋款輪替建議（碳板or高緩衝or普通）
- 最後用 1–2 句鼓勵收尾（不要雞湯過頭）

以下是資料（JSON）：
```json
{payload_json}
"""

# =========================
# Main
# =========================

def main():
    # 1) Read sheets
    ss = _get_spreadsheet()
    ws_runs = ss.worksheet(RUNS_SHEET_NAME)
    ws_splits = ss.worksheet(SPLITS_SHEET_NAME)

    runs_df = _sheet_to_df(ws_runs)
    splits_df = _sheet_to_df(ws_splits)

    # 2) Select recent runs/splits
    recent_runs, recent_splits, did_run_report_day, latest = _select_recent_runs_and_splits(runs_df, splits_df)

    # 3) Build email subject
    today_str = (datetime.now(TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    subject = f"{REPORT_SUBJECT_PREFIX} {today_str}"

    # 4) If no data at all, send a simple note (still via email)
    if recent_runs.empty:
        body = (
            f"跑步日報（{today_str}）\n\n"
            "我有去 Google Sheet 抓資料，但在設定的回溯範圍內找不到 runs 記錄。\n"
            "你可以先確認：\n"
            "- update_strava_logs.py 是否已成功更新到 GSheet\n"
            "- Sheet 名稱是否為 runs / run_splits（或 .env 有正確指定）\n\n"
            "等資料回來我就可以開始做 AI 教練分析囉。"
        )
        _send_email(subject, body)
        report_day = (datetime.now(TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"{report_day} | sent (no data) -> {REPORT_TO_EMAIL}")
        return

    # 5) Create payload & prompt
    payload = _build_payload(recent_runs, recent_splits, did_run_report_day)
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
    user_prompt = USER_PROMPT_TEMPLATE.format(payload_json=payload_json)

    # 6) Call OpenAI to generate coach report
    coach_text = _call_openai(SYSTEM_PROMPT, user_prompt)

    # 7) Send via SMTP
    _send_email(subject, coach_text)

    # 8) Print log
    now_str = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    print(
        f"{now_str} | sent daily AI report -> {REPORT_TO_EMAIL} | "
        f"did_run_today={payload['meta']['did_run_today']} | "
        f"runs_in_prompt={payload['meta']['recent_runs_count']} | splits_in_prompt={payload['meta']['recent_splits_count']}"
    )

if __name__ == "__main__":
    
    main()  
