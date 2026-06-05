from __future__ import annotations

import streamlit as st

from src.runanalyze.data_loader import load_run_data
from src.runanalyze.metrics import (
    add_run_features,
    current_streak,
    format_distance,
    format_pace,
    latest_run,
    monthly_mileage,
    weekly_mileage,
)
from src.runanalyze.ui import (
    render_goal_tracking,
    render_history,
    render_overview,
    render_report_archive,
    render_trends,
)


st.set_page_config(
    page_title="RunAnalyze",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    st.title("RunAnalyze")
    st.caption("Turn running data into training insights.")

    runs_df, splits_df, source_label = load_run_data()
    runs_df = add_run_features(runs_df)

    with st.sidebar:
        st.header("Controls")
        st.caption(f"Data source: {source_label}")

        if runs_df.empty:
            st.warning("No run data available yet.")
            return

        date_min = runs_df["start_datetime_local"].dt.date.min()
        date_max = runs_df["start_datetime_local"].dt.date.max()
        selected_range = st.date_input(
            "Date range",
            value=(date_min, date_max),
            min_value=date_min,
            max_value=date_max,
        )

        monthly_goal = st.number_input(
            "Monthly mileage goal (km)",
            min_value=1,
            max_value=1000,
            value=120,
            step=5,
        )

    if isinstance(selected_range, tuple) and len(selected_range) == 2:
        start_date, end_date = selected_range
        filtered_runs = runs_df[
            (runs_df["start_datetime_local"].dt.date >= start_date)
            & (runs_df["start_datetime_local"].dt.date <= end_date)
        ].copy()
    else:
        filtered_runs = runs_df.copy()

    if filtered_runs.empty:
        st.info("No runs match this date range.")
        return

    latest = latest_run(runs_df)
    summary = {
        "latest_run": latest,
        "weekly_mileage": weekly_mileage(runs_df),
        "monthly_mileage": monthly_mileage(runs_df),
        "current_streak": current_streak(runs_df),
        "avg_pace": filtered_runs["pace_min_per_km"].mean(),
        "total_distance": filtered_runs["distance_km"].sum(),
        "run_count": len(filtered_runs),
        "monthly_goal": monthly_goal,
    }

    tabs = st.tabs(["Overview", "Run History", "Trends", "Goal Tracking", "Daily Reports"])
    with tabs[0]:
        render_overview(filtered_runs, summary)
    with tabs[1]:
        render_history(filtered_runs, splits_df)
    with tabs[2]:
        render_trends(filtered_runs)
    with tabs[3]:
        render_goal_tracking(runs_df, summary)
    with tabs[4]:
        render_report_archive(runs_df)

    st.sidebar.divider()
    st.sidebar.metric("Selected distance", format_distance(summary["total_distance"]))
    st.sidebar.metric("Selected avg pace", format_pace(summary["avg_pace"]))


if __name__ == "__main__":
    main()
