import pandas as pd

from workflow_dashboard.analytics import build_analytics
from workflow_dashboard.config import DashboardConfig


GENERATED_AT = pd.Timestamp("2026-07-21T16:00:00Z")


def sample_cases() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "record_id": "old-team",
                "item_label": "Old team case",
                "step_name": "Review",
                "status": "In Progress",
                "owner": "  staff   member b ",
                "submitted_at": GENERATED_AT - pd.Timedelta(days=7, minutes=1),
                "last_activity_at": GENERATED_AT - pd.Timedelta(days=1),
                "is_terminal": False,
                # The display age is rounded, so backlog must use the exact timestamp.
                "age_days": 7.0,
                "idle_days": 1.0,
            },
            {
                "record_id": "exactly-seven",
                "item_label": "Exactly seven days",
                "step_name": "Review",
                "status": "In Progress",
                "owner": "Staff Member A",
                "submitted_at": GENERATED_AT - pd.Timedelta(days=7),
                "last_activity_at": GENERATED_AT - pd.Timedelta(days=1),
                "is_terminal": False,
                "age_days": 7.0,
                "idle_days": 1.0,
            },
            {
                "record_id": "young",
                "item_label": "Young case",
                "step_name": "Review",
                "status": "Needs Review",
                "owner": "Staff Member C",
                "submitted_at": GENERATED_AT - pd.Timedelta(days=2),
                "last_activity_at": GENERATED_AT - pd.Timedelta(hours=4),
                "is_terminal": False,
                "age_days": 2.0,
                "idle_days": 0.2,
            },
            {
                "record_id": "missing-date",
                "item_label": "Missing submission date",
                "step_name": "Review",
                "status": "Needs Review",
                "owner": "Staff Member D",
                "submitted_at": pd.NaT,
                "last_activity_at": GENERATED_AT - pd.Timedelta(hours=4),
                "is_terminal": False,
                "age_days": pd.NA,
                "idle_days": 0.2,
            },
            {
                "record_id": "closed",
                "item_label": "Closed case",
                "step_name": "End",
                "status": "Completed",
                "owner": "Staff Member E",
                "submitted_at": GENERATED_AT - pd.Timedelta(days=20),
                "last_activity_at": GENERATED_AT,
                "is_terminal": True,
                "age_days": 20.0,
                "idle_days": 0.0,
            },
            {
                "record_id": "old-outsider",
                "item_label": "Old non-roster case",
                "step_name": "Faculty Review",
                "status": "In Progress",
                "owner": "Outside, Person",
                "submitted_at": GENERATED_AT - pd.Timedelta(days=8),
                "last_activity_at": GENERATED_AT - pd.Timedelta(days=1),
                "is_terminal": False,
                "age_days": 8.0,
                "idle_days": 1.0,
            },
        ]
    )


def build_sample_analytics():
    return build_analytics(
        sample_cases(),
        config=DashboardConfig(),
        generated_at=GENERATED_AT,
    )


def high_cardinality_cases(statuses: list[object] | None = None) -> pd.DataFrame:
    statuses = statuses or [f"Status {index:02}" for index in range(15)]
    return pd.DataFrame(
        [
            {
                "record_id": f"case-{index:02}",
                "item_label": f"Case {index:02}",
                "step_name": f"Step {index:02}",
                "status": status,
                "owner": "Outside, Person",
                "submitted_at": GENERATED_AT - pd.Timedelta(days=index + 1),
                "last_activity_at": GENERATED_AT - pd.Timedelta(hours=1),
                "is_terminal": False,
                "age_days": float(index + 1),
                "idle_days": 1.0,
            }
            for index, status in enumerate(statuses)
        ]
    )


def build_high_cardinality_analytics(statuses: list[object] | None = None):
    return build_analytics(
        high_cardinality_cases(statuses),
        config=DashboardConfig(),
        generated_at=GENERATED_AT,
    )


def test_in_the_works_and_backlog_are_distinct_cohorts() -> None:
    analytics = build_sample_analytics()

    assert set(analytics.in_the_works["record_id"]) == {
        "old-team",
        "exactly-seven",
        "young",
        "missing-date",
        "old-outsider",
    }
    assert set(analytics.backlog["record_id"]) == {"old-team", "old-outsider"}
    assert analytics.kpis[1].key == "in_the_works"
    assert analytics.kpis[1].label == "Open Cases"
    assert analytics.kpis[1].value == "5"
    assert analytics.snapshot_metrics["in_the_works_count"] == 5
    assert analytics.snapshot_metrics["backlog_count"] == 2
    assert analytics.chart_tables["in_the_works_by_step"]["count"].sum() == 5


def test_step_charts_include_every_category() -> None:
    analytics = build_high_cardinality_analytics()
    step_counts = analytics.chart_tables["in_the_works_by_step"]
    aging = analytics.chart_tables["aging_by_step"].set_index("step_name")

    assert len(step_counts) == 15
    assert step_counts["count"].sum() == analytics.snapshot_metrics[
        "in_the_works_count"
    ]
    assert set(step_counts["step_name"]) == {
        f"Step {index:02}" for index in range(15)
    }
    assert len(aging) == 15
    assert aging.loc["Step 00", "age_days"] == 1.0
    assert aging.loc["Step 14", "age_days"] == 15.0


def test_status_chart_aggregates_categories_beyond_top_eleven() -> None:
    statuses = [None, "Other"] + [f"Status {index:02}" for index in range(13)]
    analytics = build_high_cardinality_analytics(statuses)
    status_mix = analytics.chart_tables["status_mix"].set_index("status")["count"]

    assert len(status_mix) == 12
    assert status_mix.sum() == analytics.snapshot_metrics["total_records"]
    assert status_mix["No status"] == 1
    assert status_mix["Other"] == 1
    assert status_mix["Other (4 statuses)"] == 4
    assert "Status 08" in status_mix.index
    assert "Status 09" not in status_mix.index


def test_status_chart_combines_open_statuses_with_completed_end_step_cases() -> None:
    analytics = build_sample_analytics()
    status_mix = analytics.chart_tables["status_mix"].set_index("status")["count"]

    assert status_mix.to_dict() == {
        "Completed": 1,
        "Needs Review": 2,
        "In Progress": 3,
    }
    assert status_mix.sum() == analytics.snapshot_metrics["total_records"]


def test_status_chart_keeps_completed_when_categories_are_aggregated() -> None:
    cases = high_cardinality_cases(
        [f"Status {index:02}" for index in range(14)]
    )
    cases.loc[cases.index[-1], "is_terminal"] = True
    analytics = build_analytics(
        cases,
        config=DashboardConfig(),
        generated_at=GENERATED_AT,
    )
    status_mix = analytics.chart_tables["status_mix"].set_index("status")["count"]

    assert len(status_mix) == 12
    assert status_mix["Completed"] == 1
    assert status_mix["Other (3 statuses)"] == 3
    assert status_mix.sum() == analytics.snapshot_metrics["total_records"]


def test_status_chart_does_not_add_other_at_or_below_limit() -> None:
    analytics = build_high_cardinality_analytics(
        [f"Status {index:02}" for index in range(12)]
    )
    statuses = analytics.chart_tables["status_mix"]["status"]

    assert len(statuses) == 12
    assert not statuses.str.startswith("Other (").any()


def test_missing_chart_categories_use_explicit_labels() -> None:
    cases = sample_cases()
    cases.loc[cases["record_id"] == "old-team", ["step_name", "status"]] = None
    analytics = build_analytics(
        cases,
        config=DashboardConfig(),
        generated_at=GENERATED_AT,
    )

    assert "No step" in set(
        analytics.chart_tables["in_the_works_by_step"]["step_name"]
    )
    assert "No step" in set(analytics.chart_tables["aging_by_step"]["step_name"])
    assert "No status" in set(analytics.chart_tables["status_mix"]["status"])


def test_cases_closed_today_remains_separate_from_completed_day_chart() -> None:
    analytics = build_sample_analytics()
    closed_today = next(
        kpi for kpi in analytics.kpis if kpi.key == "cases_closed_today"
    )
    total_closed = next(
        kpi for kpi in analytics.kpis if kpi.key == "total_cases_closed"
    )

    assert closed_today.value == "1"
    assert total_closed.value == "1"
    assert [kpi.key for kpi in analytics.kpis][2:4] == [
        "cases_closed_today",
        "total_cases_closed",
    ]
    assert analytics.snapshot_metrics["reached_end_today_count"] == 1
    assert analytics.chart_tables["daily_closures"].empty


def test_missing_submission_date_is_a_notable_observation() -> None:
    analytics = build_sample_analytics()
    missing = analytics.exceptions.loc[
        analytics.exceptions["record_id"] == "missing-date"
    ].iloc[0]

    assert "Missing case submission date" in missing["exception_reasons"]
    assert "missing-date" not in set(analytics.backlog["record_id"])


def test_team_outputs_use_explicit_zero_filled_roster() -> None:
    analytics = build_sample_analytics()
    current_counts = analytics.chart_tables["owner_workload"].set_index("owner")[
        "count"
    ]
    submission_counts = analytics.chart_tables["submitted_by_workload"].set_index(
        "owner"
    )["count"]

    assert set(current_counts.index) == set(DashboardConfig().team_members) | {"Others"}
    assert current_counts["Others"] == 1
    assert current_counts.sum() == len(analytics.in_the_works)
    assert submission_counts.sum() == len(sample_cases())
    assert current_counts["Staff Member B"] == 1
    assert current_counts["Staff Member E"] == 0
    assert "Outside, Person" not in current_counts.index
    assert submission_counts["Staff Member E"] == 1
    assert "Outside, Person" not in submission_counts.index

    activity = analytics.chart_tables["submitted_by_date_activity"]
    assert set(activity["owner"]) == set(DashboardConfig().team_members) | {"Others"}
