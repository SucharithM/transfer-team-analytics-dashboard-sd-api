import pandas as pd

from workflow_dashboard.analytics import _closed_by_month
from workflow_dashboard.dashboard_html import _closed_by_month_trend


GENERATED_AT = pd.Timestamp("2026-04-15T16:00:00Z")


def _closures(last_activity_at: list[str]) -> pd.DataFrame:
    closed_at = pd.to_datetime(last_activity_at, utc=True)
    return pd.DataFrame(
        {
            "last_activity_at": closed_at,
            "submitted_at": closed_at - pd.Timedelta(days=10),
        }
    )


def test_monthly_closures_fill_internal_gaps_without_trailing_report_month() -> None:
    result = _closed_by_month(
        _closures(["2026-01-10T15:00:00Z", "2026-03-20T15:00:00Z"]),
        GENERATED_AT,
    )

    assert result["closed_month"].tolist() == ["2026-01", "2026-02", "2026-03"]
    assert result["closed_count"].tolist() == [1, 0, 1]
    assert result["completion_valid_count"].tolist() == [1, 0, 1]
    assert result["completion_total_count"].tolist() == [1, 0, 1]
    assert pd.isna(result.loc[1, "median_completion_days"])
    assert result["closed_month_label"].tolist() == [
        "Jan 2026",
        "Feb 2026",
        "Mar 2026",
    ]


def test_monthly_closures_label_active_reporting_month_as_mtd() -> None:
    result = _closed_by_month(
        _closures(["2026-03-20T15:00:00Z", "2026-04-10T15:00:00Z"]),
        GENERATED_AT,
    )

    assert result["closed_count"].tolist() == [1, 1]
    assert result.iloc[-1]["closed_month_label"] == "Apr 2026 (MTD)"


def test_monthly_closures_use_eastern_months_and_exclude_future_activity() -> None:
    result = _closed_by_month(
        _closures(
            [
                "2026-03-01T04:30:00Z",  # February 28 in America/New_York
                "2026-04-15T15:59:00Z",
                "2026-04-15T16:01:00Z",  # After report generation
            ]
        ),
        GENERATED_AT,
    )

    assert result["closed_month"].tolist() == ["2026-02", "2026-03", "2026-04"]
    assert result["closed_count"].tolist() == [1, 0, 1]
    assert result.iloc[-1]["closed_month_label"] == "Apr 2026 (MTD)"


def test_monthly_chart_uses_date_axis_and_has_no_duplicate_trendline() -> None:
    table = pd.DataFrame(
        {
            "closed_month": ["2026-01", "2026-02", "2026-03"],
            "closed_month_label": ["Jan 2026", "Feb 2026", "Mar 2026"],
            "closed_count": [1, 0, 1],
            "median_completion_days": [10.0, pd.NA, 12.0],
            "completion_valid_count": [1, 0, 1],
            "completion_total_count": [1, 0, 1],
        }
    )

    chart = _closed_by_month_trend(table)

    assert len(chart.data) == 1
    assert chart.data[0].type == "bar"
    assert chart.data[0].name == "Completed Cases"
    assert list(chart.data[0].y) == [1, 0, 1]
    assert list(chart.data[0].x) == list(pd.date_range("2026-01-01", periods=3, freq="MS"))
    assert chart.layout.xaxis.type == "date"
    assert list(chart.layout.xaxis.ticktext) == ["Jan 2026", "Feb 2026", "Mar 2026"]
    assert chart.data[0].customdata[0][1] == "1/1 valid"
