import pandas as pd

from workflow_dashboard.analytics import (
    AGING_BAND_LABELS,
    build_analytics,
)
from workflow_dashboard.config import DashboardConfig
from workflow_dashboard.dashboard_content import WORKFLOW_STEP_ORDER
from workflow_dashboard.dashboard_html import (
    AGING_RISK_COLORS,
    _workflow_aging_matrix_chart,
)


GENERATED_AT = pd.Timestamp("2026-07-27T16:00:00Z")
POST_FACULTY = "Transcript Evaluator - Post-Faculty Review"
PENDING_SYLLABI = "Transcript Evaluator - Pending Student Syllabi"


def _case(
    record_id: str,
    *,
    step_name: object = "Transcript Evaluator",
    age_days: float | None = 1.0,
    terminal: bool = False,
) -> dict[str, object]:
    submitted_at = (
        pd.NaT
        if age_days is None
        else GENERATED_AT - pd.Timedelta(days=age_days)
    )
    return {
        "record_id": record_id,
        "item_label": record_id,
        "step_name": step_name,
        "status": "InProgress",
        "owner": "Staff Member A",
        "submitted_at": submitted_at,
        "last_activity_at": GENERATED_AT - pd.Timedelta(hours=1),
        "is_terminal": terminal,
        "age_days": age_days,
        "idle_days": 1.0,
    }


def _analytics(cases: list[dict[str, object]]):
    return build_analytics(
        pd.DataFrame(cases),
        config=DashboardConfig(),
        generated_at=GENERATED_AT,
    )


def _step_rows(table: pd.DataFrame, step_name: str) -> pd.DataFrame:
    return (
        table.loc[table["step_name"].eq(step_name)]
        .sort_values("band_order")
        .reset_index(drop=True)
    )


def test_aging_bands_are_lower_inclusive_at_every_boundary() -> None:
    ages = [0, 2.999, 3, 6.999, 7, 13.999, 14, 29.999, 30, 59.999, 60]
    cases = [
        _case(f"age-{index}", age_days=age)
        for index, age in enumerate(ages)
    ]
    cases.append(_case("terminal", age_days=90, terminal=True))

    analytics = _analytics(cases)
    rows = _step_rows(
        analytics.chart_tables["workflow_aging_matrix"],
        "Transcript Evaluator",
    )

    assert list(rows["aging_band"]) == list(AGING_BAND_LABELS)
    assert list(rows["count"]) == [2, 2, 2, 2, 2, 1]
    assert rows["count"].sum() == analytics.snapshot_metrics["age_valid_count"]
    assert rows["step_total"].unique().tolist() == [len(ages)]
    assert rows["excluded_age_count"].unique().tolist() == [0]


def test_missing_and_negative_ages_are_disclosed_without_reducing_step_total() -> None:
    cases = [
        _case("valid", age_days=4),
        _case("missing", age_days=None),
        _case("future", age_days=-1),
    ]

    analytics = _analytics(cases)
    rows = _step_rows(
        analytics.chart_tables["workflow_aging_matrix"],
        "Transcript Evaluator",
    )

    assert rows["count"].sum() == 1
    assert rows.loc[rows["aging_band"].eq("3–7d"), "count"].item() == 1
    assert rows["step_total"].unique().tolist() == [3]
    assert rows["excluded_age_count"].unique().tolist() == [2]
    assert analytics.snapshot_metrics["age_valid_count"] == 1
    assert analytics.snapshot_metrics["age_total_count"] == 3


def test_matrix_keeps_canonical_rows_then_unknown_steps_and_no_step() -> None:
    cases = [
        _case(
            "post-faculty",
            step_name="Transcript Evaluator – Post-Faculty Review",
        ),
        _case("zeta", step_name="zeta Queue"),
        _case("alpha", step_name="Alpha Queue"),
        _case("missing", step_name=None),
    ]

    table = _analytics(cases).chart_tables["workflow_aging_matrix"]
    ordered_rows = (
        table[
            [
                "step_name",
                "step_order",
                "step_total",
                "excluded_age_count",
            ]
        ]
        .drop_duplicates("step_order")
        .sort_values("step_order")
        .reset_index(drop=True)
    )

    expected_canonical = list(WORKFLOW_STEP_ORDER)
    expected_canonical[2] = "Transcript Evaluator – Post-Faculty Review"
    assert list(ordered_rows["step_name"]) == [
        *expected_canonical,
        "Alpha Queue",
        "zeta Queue",
        "No step",
    ]
    assert list(ordered_rows.loc[:5, "step_total"]) == [0, 0, 1, 0, 0, 0]
    assert len(table) == len(ordered_rows) * len(AGING_BAND_LABELS)


def test_matrix_distinguishes_large_young_and_small_aged_queues() -> None:
    post_ages = [1] * 12 + [5] * 20 + [10] * 4 + [20]
    syllabi_ages = [5] + [20] * 6 + [40] + [65] * 2
    cases = [
        _case(f"post-{index}", step_name=POST_FACULTY, age_days=age)
        for index, age in enumerate(post_ages)
    ]
    cases.extend(
        _case(
            f"syllabi-{index}",
            step_name=PENDING_SYLLABI,
            age_days=age,
        )
        for index, age in enumerate(syllabi_ages)
    )

    table = _analytics(cases).chart_tables["workflow_aging_matrix"]
    post = _step_rows(table, POST_FACULTY)
    syllabi = _step_rows(table, PENDING_SYLLABI)

    assert list(post["count"]) == [12, 20, 4, 1, 0, 0]
    assert post["step_total"].unique().tolist() == [37]
    assert list(syllabi["count"]) == [0, 1, 0, 6, 1, 2]
    assert syllabi["step_total"].unique().tolist() == [10]

    chart = _workflow_aging_matrix_chart(table)
    assert len(chart.data) == 1
    trace = chart.data[0]
    assert list(trace.x) == list(AGING_BAND_LABELS)
    assert {stop[1] for stop in trace.colorscale}.issuperset(
        AGING_RISK_COLORS
    )
    assert trace.meta["global_max_count"] == 20
    assert trace.type == "heatmap"
    assert trace.texttemplate == "%{text}"
    assert "Open cases: %{customdata[3]:,}" in trace.hovertemplate
    assert "Case age unavailable: %{customdata[2]:,}" in trace.hovertemplate

    post_index = list(trace.y).index(POST_FACULTY)
    syllabi_index = list(trace.y).index(PENDING_SYLLABI)
    assert list(trace.text[post_index]) == ["12", "20", "4", "1", "", ""]
    assert list(trace.text[syllabi_index]) == ["", "1", "", "6", "1", "2"]
    assert [cell[3] for cell in trace.customdata[post_index]] == [
        12,
        20,
        4,
        1,
        0,
        0,
    ]
    assert [cell[3] for cell in trace.customdata[syllabi_index]] == [
        0,
        1,
        0,
        6,
        1,
        2,
    ]
    assert chart.layout.height == 420
    assert chart.layout.yaxis.autorange == "reversed"
    assert [annotation.text for annotation in chart.layout.annotations].count(
        "<b>37</b>"
    ) == 1
    assert [annotation.text for annotation in chart.layout.annotations].count(
        "<b>10</b>"
    ) == 1


def test_matrix_height_expands_for_unrecognized_workflow_steps() -> None:
    cases = [
        _case(f"unknown-{index}", step_name=f"Unknown Step {index:02}")
        for index in range(5)
    ]
    table = _analytics(cases).chart_tables["workflow_aging_matrix"]

    chart = _workflow_aging_matrix_chart(table)

    assert chart.layout.height == 150 + 45 * (len(WORKFLOW_STEP_ORDER) + 5)
