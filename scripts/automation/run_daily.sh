#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
VENV_PY="$PROJECT_DIR/.venv/bin/python"
ENV_FILE="$PROJECT_DIR/.env"

mkdir -p "$LOG_DIR"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') START =====" >> "$LOG_DIR/cron.log"

# venv python 必須存在
if [ ! -x "$VENV_PY" ]; then
  echo "[ERROR] venv python not found or not executable: $VENV_PY" >> "$LOG_DIR/cron.log"
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') END (FAILED) =====" >> "$LOG_DIR/cron.log"
  exit 1
fi

# 載入環境變數（有空白記得加引號）
if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

"$VENV_PY" "$PROJECT_DIR/scripts/etl/sync_strava_to_sheets.py" >> "$LOG_DIR/running_log.log" 2>&1
"$VENV_PY" "$PROJECT_DIR/scripts/reports/daily_ai_report.py" >> "$LOG_DIR/daily_ai_report.log" 2>&1

echo "===== $(date '+%Y-%m-%d %H:%M:%S') END =====" >> "$LOG_DIR/cron.log"
