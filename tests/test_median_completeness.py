import pandas as pd
import pytest

from workflow_dashboard.analytics import build_analytics
from workflow_dashboard.config import DashboardConfig, load_config
from workflow_dashboard.dashboard_html import (
    _aging_by_step_chart,
    _closed_by_month_trend,
)
from workflow_dashboard.history import (
    build_metric_definition,
    load_history,
    store_snapshot,
)


GENERATED_AT = pd.Timestamp("2026-07-22T16:00:00Z")


def _open_case(
    index: int,
    *,
    valid_age: bool,
    step_name: str = "Review",
) -> dict:
    return {
        "record_id": f"open-{index}",
        "item_label": f"Open {index}",
        "workflow_name": "Workflow A",
        "step_name": step_name,
        "status": "In Progress",
        "owner": "Staff Member A",
        "submitted_at": (
            GENERATED_AT - pd.Timedelta(days=1)
            if valid_age
            else pd.NaT
        ),
        "last_activity_at": GENERATED_AT - pd.Timedelta(hours=1),
        "is_terminal": False,
        "age_days": 1.0 if valid_age else pd.NA,
        "idle_days": 1 / 24,
    }


def _terminal_case(index: int, *, valid_completion: bool) -> dict:
    closed_at = GENERATED_AT - pd.Timedelta(days=2)
    return {
        "record_id": f"closed-{index}",
        "item_label": f"Closed {index}",
        "workflow_name": "Workflow A",
        "step_name": "End",
        "status": "Completed",
        "owner": "Staff Member A",
        "submitted_at": (
            closed_at - pd.Timedelta(days=10)
            if valid_completion
            else pd.NaT
        ),
        "last_activity_at": closed_at,
        "is_terminal": True,
        "age_days": 12.0 if valid_completion else pd.NA,
        "idle_days": 2.0,
    }


def _kpi(analytics, key: str):
    return next(kpi for kpi in analytics.kpis if kpi.key == key)


def test_wait_median_suppresses_one_of_ten_without_cluttering_value() -> None:
    cases = pd.DataFrame(
        [_open_case(index, valid_age=index == 0) for index in range(10)]
    )

    analytics = build_analytics(
        cases,
        config=DashboardConfig(),
        generated_at=GENERATED_AT,
    )

    wait = _kpi(analytics, "typical_wait_time")
    assert wait.value == "—"
    assert wait.warning_caption == "1/10 valid · below 95%"
    assert "Based on 1 of 10 cases" in wait.help_text
    assert analytics.snapshot_metrics["median_age_days"] is None
    assert analytics.snapshot_metrics["age_valid_count"] == 1
    assert analytics.snapshot_metrics["age_total_count"] == 10


def test_wait_median_at_threshold_keeps_clean_kpi_value() -> None:
    cases = pd.DataFrame(
        [_open_case(index, valid_age=index < 19) for index in range(20)]
    )

    analytics = build_analytics(
        cases,
        config=DashboardConfig(),
        generated_at=GENERATED_AT,
    )

    wait = _kpi(analytics, "typical_wait_time")
    assert wait.value == "1.0d"
    assert wait.warning_caption is None
    assert analytics.snapshot_metrics["median_age_days"] == pytest.approx(1.0)
    assert analytics.snapshot_metrics["age_valid_count"] == 19
    assert analytics.snapshot_metrics["age_total_count"] == 20


def test_age_by_step_keeps_undercovered_group_without_showing_sample_sizes() -> None:
    cases = pd.DataFrame(
        [
            _open_case(1, valid_age=True, step_name="Review"),
            _open_case(2, valid_age=False, step_name="Review"),
            _open_case(3, valid_age=True, step_name="Faculty Review"),
        ]
    )
    analytics = build_analytics(
        cases,
        config=DashboardConfig(),
        generated_at=GENERATED_AT,
    )
    aging = analytics.chart_tables["aging_by_step"].set_index("step_name")

    assert aging.loc["Review", "age_valid_count"] == 1
    assert aging.loc["Review", "age_total_count"] == 2
    assert pd.isna(aging.loc["Review", "age_days"])
    assert aging.loc["Faculty Review", "age_valid_count"] == 1
    assert aging.loc["Faculty Review", "age_total_count"] == 1
    assert aging.loc["Faculty Review", "age_days"] == pytest.approx(1.0)

    chart = _aging_by_step_chart(
        analytics.chart_tables["aging_by_step"],
        overall_age_days=1.0,
    )
    trace = chart.data[0]
    assert trace.type == "pie"
    assert list(trace.labels) == ["Faculty Review", "Review"]
    assert list(trace.values) == [1.0, 0.0]
    assert trace.texttemplate == "%{value:.1f}d"
    assert "Median Open Age: %{value:.1f}d" in trace.hovertemplate
    assert "percent" not in trace.texttemplate
    assert "Share" not in trace.hovertemplate
    assert "valid" not in trace.hovertemplate
    assert chart.layout.annotations[0].text == "<b>1.0d</b>"


def test_monthly_completion_keeps_volume_and_suppresses_one_of_one_hundred() -> None:
    cases = pd.DataFrame(
        [
            _terminal_case(index, valid_completion=index == 0)
            for index in range(100)
        ]
    )
    analytics = build_analytics(
        cases,
        config=DashboardConfig(),
        generated_at=GENERATED_AT,
    )
    monthly = analytics.chart_tables["closed_by_month"]

    assert monthly.iloc[0]["closed_count"] == 100
    assert monthly.iloc[0]["completion_valid_count"] == 1
    assert monthly.iloc[0]["completion_total_count"] == 100
    assert pd.isna(monthly.iloc[0]["median_completion_days"])

    chart = _closed_by_month_trend(monthly)
    assert chart.data[0].y[0] == 100
    assert chart.data[0].customdata[0][0] == "—"
    assert chart.data[0].customdata[0][1] == "1/100 valid"


def test_wait_and_monthly_coverage_round_trip_through_history(tmp_path) -> None:
    cases = pd.DataFrame(
        [
            _open_case(1, valid_age=True),
            _open_case(2, valid_age=False),
            _terminal_case(3, valid_completion=True),
            _terminal_case(4, valid_completion=False),
        ]
    )
    config = DashboardConfig(fixture_path=tmp_path / "fixture.json")
    analytics = build_analytics(
        cases,
        config=config,
        generated_at=GENERATED_AT,
    )
    definition = build_metric_definition(config, cases, source="fixture")
    db_path = tmp_path / "history.sqlite"

    run_id = store_snapshot(
        db_path, analytics, definition, source="fixture"
    )
    snapshots, _, monthly = load_history(
        db_path,
        source="fixture",
        definition_hash=definition.definition_hash,
    )

    snapshot = snapshots.loc[snapshots["run_id"] == run_id].iloc[0]
    assert snapshot["age_valid_count"] == 1
    assert snapshot["age_total_count"] == 2
    assert pd.isna(snapshot["median_age_days"])
    completion = monthly.loc[monthly["run_id"] == run_id].iloc[0]
    assert completion["closed_count"] == 2
    assert completion["completion_valid_count"] == 1
    assert completion["completion_total_count"] == 2
    assert pd.isna(completion["median_completion_days"])


@pytest.mark.parametrize(
    "name",
    [
        "WORKFLOW_MIN_WAIT_COMPLETENESS",
        "WORKFLOW_MIN_COMPLETION_COMPLETENESS",
    ],
)
def test_new_completeness_environment_values_are_validated(
    monkeypatch, tmp_path, name
) -> None:
    monkeypatch.setenv(name, "not-a-number")
    with pytest.raises(ValueError, match=name):
        load_config(env_file=tmp_path / "missing.env")

    monkeypatch.setenv(name, "1.1")
    with pytest.raises(ValueError, match="decimal from 0 through 1"):
        load_config(env_file=tmp_path / "missing.env")
