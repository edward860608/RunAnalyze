# RunAnalyze Project Context

RunAnalyze is a personal running analytics platform built around the Strava API.
The goal is to automate running data collection, storage, analysis, reporting,
and visualization to support training decisions and long-term performance
tracking.

## Current Architecture

```text
Strava API
  -> Python ETL
  -> Google Sheets
  -> Daily Email Report
```

Current hosting uses an old MacBook as a lightweight home server. A crontab
executes daily Python scripts.

## Data Model

`runs` stores activity-level records:

- `run_id`
- `name`
- `type`
- `sport_type`
- `start_datetime_local`
- `end_datetime_local`
- `distance_km`
- `moving_time_min_str`
- `avg_pace_str`
- `avg_heart_rate_bpm`
- `max_heart_rate_bpm`
- `avg_cadence_spm`
- `shoes`

`run_splits` stores kilometer-level split records:

- `run_id`
- `name`
- `type`
- `sport_type`
- `start_datetime_local`
- `end_datetime_local`
- `moving_time_min_str`
- `distance_km`
- `distance`
- `km`
- `pace_str`
- `avg_heart_rate_bpm`
- `avg_cadence_spm`
- `shoes`

## ETL Principle

The ETL should remain append-only:

1. Read existing `run_id` values from storage.
2. Pull latest Strava activities.
3. Compare incoming IDs with existing IDs.
4. Append only new activities.
5. Never overwrite historical records.

## Dashboard MVP

Phase 1 uses Streamlit and targets GitHub plus Streamlit Community Cloud.

The MVP includes:

- Overview
- Run History
- Trends
- Goal Tracking
- Daily Report Archive

## Product Vision

RunAnalyze should evolve into a personal running intelligence platform:

```text
Strava API
  -> ETL Layer
  -> Google Sheets / Database
  -> Analytics Layer
  -> Dashboard
  -> Web App
```

Longer-term features may include training load, race prediction, and AI coach
recommendations.

Core idea: running + analytics + automation.
