import pandas as pd
import pytest

from workflow_dashboard.analytics import build_analytics
from workflow_dashboard.config import DashboardConfig
from workflow_dashboard.dashboard_html import _table_html
from workflow_dashboard.normalization import normalize_records

GENERATED_AT = pd.Timestamp("2026-07-22T16:00:00Z")
OWNER = "Staff Member A"


def _record(
    record_id: str,
    *,
    submitted_at: pd.Timestamp,
    last_activity_at: pd.Timestamp,
    step_name: str = "Review",
    status: str | None = "In Progress",
    owner: str | None = OWNER,
) -> dict:
    return {
        "packageID": record_id,
        "packageName": record_id,
        "workflowName": "Workflow A",
        "stepName": step_name,
        "status": status,
        "submittedBy": owner,
        "submissionDate": submitted_at.isoformat(),
        "lastActivityDate": last_activity_at.isoformat(),
    }


def _normalize(records: list[dict]) -> pd.DataFrame:
    return normalize_records(
        records,
        DashboardConfig(),
        generated_at=GENERATED_AT,
    )


def test_normalization_preserves_negative_age_and_idle_durations() -> None:
    normalized = _normalize(
        [
            _record(
                "future",
                submitted_at=GENERATED_AT + pd.Timedelta(days=1),
                last_activity_at=GENERATED_AT + pd.Timedelta(hours=12),
            )
        ]
    )

    assert normalized.iloc[0]["age_days"] == pytest.approx(-1.0)
    assert normalized.iloc[0]["idle_days"] == pytest.approx(-0.5)


def test_future_open_durations_are_flagged_and_excluded_only_where_invalid() -> None:
    normalized = _normalize(
        [
            _record(
                "valid",
                submitted_at=GENERATED_AT - pd.Timedelta(days=4),
                last_activity_at=GENERATED_AT - pd.Timedelta(days=2),
            ),
            _record(
                "future",
                submitted_at=GENERATED_AT + pd.Timedelta(days=1),
                last_activity_at=GENERATED_AT + pd.Timedelta(days=2),
            ),
        ]
    )
    analytics = build_analytics(
        normalized,
        config=DashboardConfig(
            minimum_wait_completeness=0.5,
            minimum_idle_completeness=0,
        ),
        generated_at=GENERATED_AT,
    )

    assert analytics.snapshot_metrics["total_records"] == 2
    assert analytics.snapshot_metrics["in_the_works_count"] == 2
    assert analytics.chart_tables["in_the_works_by_step"]["count"].sum() == 2
    assert analytics.chart_tables["status_mix"]["count"].sum() == 2
    assert analytics.chart_tables["submitted_by_workload"]["count"].sum() == 2

    assert analytics.snapshot_metrics["median_age_days"] == pytest.approx(4.0)
    assert analytics.snapshot_metrics["oldest_age_days"] == pytest.approx(4.0)
    assert analytics.snapshot_metrics["median_idle_days"] == pytest.approx(2.0)
    assert analytics.snapshot_metrics["idle_valid_count"] == 1
    assert analytics.snapshot_metrics["idle_total_count"] == 2
    aging = analytics.chart_tables["aging_by_step"]
    assert aging.iloc[0]["age_days"] == pytest.approx(4.0)

    future = analytics.exceptions.loc[
        analytics.exceptions["record_id"] == "future"
    ].iloc[0]
    assert future["exception_reasons"] == (
        "Case submission after report generation; "
        "Last activity after report generation"
    )
    assert future["age_days"] == pytest.approx(-1.0)
    assert future["idle_days"] == pytest.approx(-2.0)

    dated_activity = analytics.chart_tables["submitted_by_date_activity"]
    assert dated_activity["count"].sum() == 1
    assert dated_activity["submitted_date"].max() <= GENERATED_AT.date()
    assert "Case Submitted" in _table_html(analytics.exceptions)


def test_last_activity_before_submission_is_excluded_from_idle_metrics() -> None:
    normalized = _normalize(
        [
            _record(
                "valid",
                submitted_at=GENERATED_AT - pd.Timedelta(days=2),
                last_activity_at=GENERATED_AT - pd.Timedelta(days=1),
            ),
            _record(
                "impossible",
                submitted_at=GENERATED_AT - pd.Timedelta(days=2),
                last_activity_at=GENERATED_AT - pd.Timedelta(days=100),
            ),
        ]
    )

    permissive = build_analytics(
        normalized,
        config=DashboardConfig(minimum_idle_completeness=0.5),
        generated_at=GENERATED_AT,
    )
    permissive_idle = next(
        kpi for kpi in permissive.kpis if kpi.key == "typical_idle_time"
    )
    assert permissive_idle.value == "1.0d"
    assert permissive_idle.warning_caption is None
    assert permissive.snapshot_metrics["median_idle_days"] == pytest.approx(1.0)
    assert permissive.snapshot_metrics["idle_valid_count"] == 1
    assert permissive.snapshot_metrics["idle_total_count"] == 2

    analytics = build_analytics(
        normalized,
        config=DashboardConfig(),
        generated_at=GENERATED_AT,
    )
    idle_kpi = next(kpi for kpi in analytics.kpis if kpi.key == "typical_idle_time")
    assert idle_kpi.value == "—"
    assert idle_kpi.warning_caption == "1/2 valid · below 95%"
    assert analytics.snapshot_metrics["median_idle_days"] is None
    assert analytics.snapshot_metrics["idle_valid_count"] == 1
    assert analytics.snapshot_metrics["idle_total_count"] == 2

    impossible = analytics.exceptions.loc[
        analytics.exceptions["record_id"] == "impossible"
    ].iloc[0]
    assert impossible["exception_reasons"] == ("Last activity before case submission")


def test_negative_completion_is_flagged_but_valid_closure_volume_is_retained() -> None:
    normalized = _normalize(
        [
            _record(
                "valid-terminal",
                submitted_at=GENERATED_AT - pd.Timedelta(days=10),
                last_activity_at=GENERATED_AT - pd.Timedelta(days=2),
                step_name="End",
                status=None,
                owner=None,
            ),
            _record(
                "invalid-terminal",
                submitted_at=GENERATED_AT - pd.Timedelta(days=1),
                last_activity_at=GENERATED_AT - pd.Timedelta(days=2),
                step_name="End",
                status="Completed",
            ),
        ]
    )
    analytics = build_analytics(
        normalized,
        config=DashboardConfig(),
        generated_at=GENERATED_AT,
    )

    monthly = analytics.chart_tables["closed_by_month"]
    assert monthly["closed_count"].sum() == 2
    assert pd.isna(monthly.iloc[0]["median_completion_days"])
    assert monthly.iloc[0]["completion_valid_count"] == 1
    assert monthly.iloc[0]["completion_total_count"] == 2
    assert set(analytics.exceptions["record_id"]) == {"invalid-terminal"}
    assert analytics.exceptions.iloc[0]["exception_reasons"] == (
        "Last activity before case submission"
    )


def test_future_terminal_activity_is_not_counted_as_closed_today() -> None:
    normalized = _normalize(
        [
            _record(
                "future-terminal",
                submitted_at=GENERATED_AT - pd.Timedelta(days=2),
                last_activity_at=GENERATED_AT + pd.Timedelta(hours=1),
                step_name="End",
                status="Completed",
            )
        ]
    )
    analytics = build_analytics(
        normalized,
        config=DashboardConfig(),
        generated_at=GENERATED_AT,
    )

    assert analytics.snapshot_metrics["terminal_count"] == 1
    assert analytics.snapshot_metrics["reached_end_today_count"] == 0
    assert analytics.chart_tables["closed_by_month"].empty
    assert analytics.exceptions.iloc[0]["exception_reasons"] == (
        "Last activity after report generation"
    )
