# RunAnalyze

RunAnalyze turns running data into training insights. It combines a Strava ETL
pipeline, Google Sheets storage, an AI daily running report, and a Streamlit
dashboard for personal running analytics.

## What Is Included

- Streamlit dashboard MVP
- Strava to Google Sheets append-only sync
- Daily AI running report sent by email
- Google Sheets-ready dashboard loader
- Sample data fallback for local development
- Overview, run history, trends, goals, and report archive tabs
- Project context and deployment-ready settings

## Project Structure

```text
.
├── app.py
├── src/runanalyze/
│   ├── config.py
│   ├── data_loader.py
│   ├── metrics.py
│   └── ui.py
├── scripts/
│   ├── automation/
│   │   └── run_daily.sh
│   ├── etl/
│   │   └── sync_strava_to_sheets.py
│   └── reports/
│       └── daily_ai_report.py
├── sample_data/
│   ├── runs_df.csv
│   └── splits_df.csv
├── notebooks/
│   └── running_log_database.ipynb
├── docs/
│   └── project-context.md
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml.example
├── requirements.txt
└── .env.example
```

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

By default, the app uses `sample_data`. This lets the dashboard run before
Google credentials are configured.

## Google Sheets Setup

The app expects two worksheets:

- `runs`
- `run_splits`

For local development, copy `.streamlit/secrets.toml.example` to
`.streamlit/secrets.toml` and fill in the values.

For Streamlit Community Cloud, add the same keys under app secrets.

Required secret values:

```toml
RUNANALYZE_DATA_SOURCE = "google_sheets"
SPREADSHEET_ID = "your_google_sheet_id"
GOOGLE_SHEET_NAME = "RunAnalyze"
GOOGLE_RUNS_WORKSHEET = "runs"
GOOGLE_SPLITS_WORKSHEET = "run_splits"
GOOGLE_SERVICE_ACCOUNT_JSON = """{ ... }"""
```

Share the target Google Sheet with the service account email.

## Daily Automation

Create `.env` from `.env.example`, then run:

```bash
scripts/automation/run_daily.sh
```

The automation script runs:

1. `scripts/etl/sync_strava_to_sheets.py`
2. `scripts/reports/daily_ai_report.py`

For crontab, point to the absolute path of `scripts/automation/run_daily.sh`.
Logs are written to `logs/`, which is intentionally ignored by git.

## Secrets And Data Policy

Do not commit:

- `.env`
- service account JSON files
- Strava tokens
- SMTP app passwords
- OpenAI API keys
- real running CSV exports
- logs

The repository includes anonymized `sample_data` so the dashboard can run before
production credentials are configured.

## Deployment

1. Push this repository to GitHub.
2. Create a Streamlit Community Cloud app from the GitHub repo.
3. Set `app.py` as the entrypoint.
4. Add the Google Sheets secrets in Streamlit Cloud.

## Roadmap

- Add GitHub Actions for scheduled sync.
- Add richer training analytics such as weekly load, fatigue, fitness, and form.
- Add race goal prediction and AI coaching summaries.
