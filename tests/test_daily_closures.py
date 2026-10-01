import pandas as pd
import pytest

from workflow_dashboard.analytics import _daily_closures
from workflow_dashboard.dashboard_html import (
    _daily_closures_chart,
    _recent_closures_chart,
)


def test_daily_closures_uses_eastern_dates_and_fills_completed_days() -> None:
    terminal_cases = pd.DataFrame(
        {
            "last_activity_at": pd.to_datetime(
                [
                    "2026-07-16T01:00:00Z",  # July 15 in America/New_York
                    "2026-07-16T02:00:00Z",  # July 15 in America/New_York
                    "2026-07-18T01:00:00Z",  # July 17 in America/New_York
                ],
                utc=True,
            )
        }
    )

    result = _daily_closures(
        terminal_cases,
        generated_at=pd.Timestamp("2026-07-18T16:00:00Z"),
    )

    assert result["closed_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-07-15",
        "2026-07-16",
        "2026-07-17",
    ]
    assert result["closed_count"].tolist() == [2, 0, 1]
    assert result["rolling_7_day_avg"].isna().all()


def test_daily_closures_requires_seven_completed_calendar_days() -> None:
    terminal_cases = pd.DataFrame(
        {
            "last_activity_at": pd.to_datetime(
                [f"2026-07-{day:02d}T16:00:00Z" for day in range(1, 8)],
                utc=True,
            )
        }
    )

    result = _daily_closures(
        terminal_cases,
        generated_at=pd.Timestamp("2026-07-08T16:00:00Z"),
    )

    assert result["rolling_7_day_avg"].iloc[:6].isna().all()
    assert result["rolling_7_day_avg"].iloc[6] == pytest.approx(1.0)


def test_daily_closures_excludes_current_day_from_counts_and_average() -> None:
    completed_closures = [
        f"2026-07-{day:02d}T16:{minute:02d}:00Z"
        for day in range(1, 8)
        for minute in range(10)
    ]
    terminal_cases = pd.DataFrame(
        {
            "last_activity_at": pd.to_datetime(
                completed_closures + ["2026-07-08T15:00:00Z"],
                utc=True,
            )
        }
    )

    result = _daily_closures(
        terminal_cases,
        generated_at=pd.Timestamp("2026-07-08T16:00:00Z"),
    )

    assert result["closed_date"].max() == pd.Timestamp("2026-07-07")
    assert result["closed_count"].tolist() == [10] * 7
    assert result["rolling_7_day_avg"].iloc[-1] == pytest.approx(10.0)


def test_daily_closures_uses_eastern_midnight_for_current_day_boundary() -> None:
    terminal_cases = pd.DataFrame(
        {
            "last_activity_at": pd.to_datetime(
                [
                    "2026-07-18T03:59:00Z",  # July 17 at 11:59 PM EDT
                    "2026-07-18T04:01:00Z",  # July 18 at 12:01 AM EDT
                ],
                utc=True,
            )
        }
    )

    result = _daily_closures(
        terminal_cases,
        generated_at=pd.Timestamp("2026-07-18T16:00:00Z"),
    )

    assert result["closed_date"].tolist() == [pd.Timestamp("2026-07-17")]
    assert result["closed_count"].tolist() == [1]
    assert result["rolling_7_day_avg"].isna().all()


def test_daily_closures_returns_empty_when_only_current_day_has_closures() -> None:
    terminal_cases = pd.DataFrame(
        {
            "last_activity_at": pd.to_datetime(
                ["2026-07-18T15:00:00Z"], utc=True
            )
        }
    )

    result = _daily_closures(
        terminal_cases,
        generated_at=pd.Timestamp("2026-07-18T16:00:00Z"),
    )

    assert result.empty
    assert list(result.columns) == [
        "closed_date",
        "closed_count",
        "rolling_7_day_avg",
    ]


def test_daily_closures_chart_only_plots_full_window_averages() -> None:
    dates = pd.date_range("2026-07-01", periods=8, freq="D")
    table = pd.DataFrame(
        {
            "closed_date": dates,
            "closed_count": [1] * 8,
            "rolling_7_day_avg": [float("nan")] * 6 + [1.0, 1.0],
        }
    )

    chart = _daily_closures_chart(table)

    assert list(chart.data[0].x) == list(dates)
    assert list(chart.data[1].x) == list(dates[6:])
    assert list(chart.data[1].y) == [1.0, 1.0]
    assert list(chart.data[1].customdata) == ["1.0", "1.0"]


def test_recent_closures_chart_shows_seven_completed_days_and_fills_zeros() -> None:
    table = pd.DataFrame(
        {
            "closed_date": pd.to_datetime(
                ["2026-07-10", "2026-07-12", "2026-07-17", "2026-07-18"]
            ),
            "closed_count": [99, 2, 4, 8],
        }
    )

    chart = _recent_closures_chart(
        table,
        generated_at=pd.Timestamp("2026-07-18T16:00:00Z"),
    )

    assert list(chart.data[0].x) == list(
        pd.date_range("2026-07-11", "2026-07-17", freq="D")
    )
    assert list(chart.data[0].y) == [0, 2, 0, 0, 0, 0, 4]
    assert chart.data[0].mode == "lines+markers"
    assert chart.layout.xaxis.title.text == "Date"
    assert chart.layout.yaxis.title.text == "Completed Cases"
    assert chart.layout.yaxis.dtick == 1


def test_recent_closures_chart_does_not_force_every_high_count_tick() -> None:
    table = pd.DataFrame(
        {
            "closed_date": pd.date_range("2026-07-20", periods=7, freq="D"),
            "closed_count": [12, 62, 0, 35, 20, 0, 0],
        }
    )

    chart = _recent_closures_chart(
        table,
        generated_at=pd.Timestamp("2026-07-27T16:00:00Z"),
    )

    assert chart.layout.yaxis.dtick is None
    assert chart.layout.yaxis.nticks == 8
