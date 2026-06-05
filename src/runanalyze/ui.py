from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.runanalyze.metrics import format_distance, format_pace


def render_overview(runs_df: pd.DataFrame, summary: dict) -> None:
    latest = summary["latest_run"]
    metric_cols = st.columns(5)
    metric_cols[0].metric("Latest run", latest["start_datetime_local"].strftime("%Y-%m-%d"))
    metric_cols[1].metric("This week", format_distance(summary["weekly_mileage"]))
    metric_cols[2].metric("This month", format_distance(summary["monthly_mileage"]))
    metric_cols[3].metric("Avg pace", format_pace(summary["avg_pace"]))
    metric_cols[4].metric("Current streak", f"{summary['current_streak']} days")

    st.subheader("Recent Runs")
    recent = runs_df.head(8).copy()
    st.dataframe(
        recent[
            [
                "start_datetime_local",
                "name",
                "distance_km",
                "moving_time_min_str",
                "avg_pace_str",
                "avg_heart_rate_bpm",
            ]
        ],
        hide_index=True,
        use_container_width=True,
    )

    weekly = (
        runs_df.groupby("week_start", as_index=False)["distance_km"]
        .sum()
        .sort_values("week_start")
    )
    fig = px.bar(
        weekly,
        x="week_start",
        y="distance_km",
        labels={"week_start": "Week", "distance_km": "Distance (km)"},
    )
    st.plotly_chart(fig, use_container_width=True)


def render_history(runs_df: pd.DataFrame, splits_df: pd.DataFrame) -> None:
    st.subheader("Run History")
    st.dataframe(
        runs_df[
            [
                "start_datetime_local",
                "name",
                "distance_km",
                "moving_time_min_str",
                "avg_pace_str",
                "avg_heart_rate_bpm",
                "max_heart_rate_bpm",
                "avg_cadence_spm",
                "shoes",
            ]
        ],
        hide_index=True,
        use_container_width=True,
    )

    run_options = runs_df["run_id"].astype(str).tolist()
    selected_run = st.selectbox("Splits", run_options)
    selected_splits = splits_df[splits_df["run_id"].astype(str) == selected_run]
    if selected_splits.empty:
        st.info("No split data available for this run.")
        return

    st.dataframe(
        selected_splits[["km", "distance", "pace_str", "avg_heart_rate_bpm", "avg_cadence_spm", "shoes"]],
        hide_index=True,
        use_container_width=True,
    )


def render_trends(runs_df: pd.DataFrame) -> None:
    st.subheader("Trends")

    weekly = (
        runs_df.groupby("week_start", as_index=False)
        .agg(distance_km=("distance_km", "sum"), avg_pace=("pace_min_per_km", "mean"))
        .sort_values("week_start")
    )
    monthly = (
        runs_df.groupby("month_start", as_index=False)["distance_km"]
        .sum()
        .sort_values("month_start")
    )

    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(
            px.line(
                weekly,
                x="week_start",
                y="distance_km",
                markers=True,
                labels={"week_start": "Week", "distance_km": "Weekly distance (km)"},
            ),
            use_container_width=True,
        )
    with col_b:
        st.plotly_chart(
            px.line(
                monthly,
                x="month_start",
                y="distance_km",
                markers=True,
                labels={"month_start": "Month", "distance_km": "Monthly distance (km)"},
            ),
            use_container_width=True,
        )

    st.plotly_chart(
        px.scatter(
            runs_df.sort_values("start_datetime_local"),
            x="start_datetime_local",
            y="pace_min_per_km",
            size="distance_km",
            hover_name="name",
            labels={
                "start_datetime_local": "Date",
                "pace_min_per_km": "Pace (min/km)",
                "distance_km": "Distance (km)",
            },
        ),
        use_container_width=True,
    )


def render_goal_tracking(runs_df: pd.DataFrame, summary: dict) -> None:
    st.subheader("Goal Tracking")
    monthly_goal = summary["monthly_goal"]
    progress = min(summary["monthly_mileage"] / monthly_goal, 1)
    remaining = max(monthly_goal - summary["monthly_mileage"], 0)

    st.progress(progress)
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Monthly goal", format_distance(monthly_goal))
    col_b.metric("Completed", format_distance(summary["monthly_mileage"]))
    col_c.metric("Remaining", format_distance(remaining))

    best_5k = runs_df[runs_df["distance_km"] >= 5].sort_values("pace_min_per_km").head(1)
    best_10k = runs_df[runs_df["distance_km"] >= 10].sort_values("pace_min_per_km").head(1)
    benchmarks = pd.DataFrame(
        [
            {
                "Goal": "Sub-30 5K",
                "Status": _goal_status(best_5k, target_pace=6),
                "Reference run": _reference_run(best_5k),
            },
            {
                "Goal": "Sub-60 10K",
                "Status": _goal_status(best_10k, target_pace=6),
                "Reference run": _reference_run(best_10k),
            },
        ]
    )
    st.dataframe(benchmarks, hide_index=True, use_container_width=True)


def render_report_archive(runs_df: pd.DataFrame) -> None:
    st.subheader("Daily Report Archive")
    report_rows = runs_df.copy()
    report_rows["Report date"] = report_rows["start_datetime_local"].dt.date
    report_rows["Summary"] = report_rows.apply(
        lambda row: (
            f"{row['name']}: {row['distance_km']:.1f} km, "
            f"{row['moving_time_min_str']}, {row['avg_pace_str']}"
        ),
        axis=1,
    )
    query = st.text_input("Search reports")
    if query:
        report_rows = report_rows[
            report_rows["Summary"].str.contains(query, case=False, na=False)
        ]

    st.dataframe(
        report_rows[["Report date", "Summary", "avg_heart_rate_bpm"]],
        hide_index=True,
        use_container_width=True,
    )


def _goal_status(df: pd.DataFrame, target_pace: float) -> str:
    if df.empty:
        return "No qualifying run yet"
    pace = df.iloc[0]["pace_min_per_km"]
    if pd.isna(pace):
        return "Needs pace data"
    return "On track" if pace <= target_pace else f"{format_pace(pace)} best pace"


def _reference_run(df: pd.DataFrame) -> str:
    if df.empty:
        return "-"
    run = df.iloc[0]
    return f"{run['start_datetime_local'].date()} - {run['name']}"
