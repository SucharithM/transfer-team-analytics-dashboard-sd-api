import math

import pandas as pd

from workflow_dashboard.analytics import (
    ACTION_BUCKET_LABELS,
    build_analytics,
)
from workflow_dashboard.config import DashboardConfig
from workflow_dashboard.dashboard_html import (
    _age_idle_action_matrix_chart,
    render_dashboard,
)
from workflow_dashboard.normalization import normalize_records

GENERATED_AT = pd.Timestamp("2026-07-27T16:00:00Z")


def _case(
    record_id: str,
    *,
    age_days: float | None,
    idle_days: float | None,
    step_name: str = "Transcript Evaluator",
    status: str = "InProgress",
    terminal: bool = False,
    item_label: str | None = None,
    owner: str = "Outside, Person",
) -> dict[str, object]:
    submitted_at = (
        pd.NaT if age_days is None else GENERATED_AT - pd.Timedelta(days=age_days)
    )
    last_activity_at = (
        pd.NaT if idle_days is None else GENERATED_AT - pd.Timedelta(days=idle_days)
    )
    return {
        "record_id": record_id,
        "item_label": item_label or record_id,
        "workflow_name": "Workflow A",
        "step_name": step_name,
        "status": status,
        "owner": owner,
        "submitted_at": submitted_at,
        "last_activity_at": last_activity_at,
        "is_terminal": terminal,
        "age_days": age_days,
        "idle_days": idle_days,
    }


def _analytics(
    cases: list[dict[str, object]],
    config: DashboardConfig | None = None,
):
    return build_analytics(
        pd.DataFrame(cases),
        config=config or DashboardConfig(),
        generated_at=GENERATED_AT,
    )


def test_action_buckets_use_exact_configured_boundaries() -> None:
    cases = [
        _case("seven-active", age_days=7, idle_days=2.999),
        _case("seven-stale", age_days=7, idle_days=3),
        _case("over-seven-active", age_days=7.001, idle_days=2),
        _case("fourteen-active", age_days=14, idle_days=2),
        _case("fourteen-stale", age_days=14, idle_days=3),
    ]

    table = _analytics(cases).chart_tables["age_idle_action_matrix"]
    buckets = table.set_index("record_id")["action_bucket"].to_dict()

    assert buckets == {
        "seven-active": "young_active",
        "seven-stale": "young_stale",
        "over-seven-active": "backlog_active",
        "fourteen-active": "backlog_active",
        "fourteen-stale": "backlog_stale",
    }
    assert table.attrs["backlog_age_days"] == 7
    assert table.attrs["old_age_days"] == 14
    assert table.attrs["stale_idle_days"] == 3


def test_action_buckets_reproduce_july_27_noon_acceptance_split() -> None:
    cases: list[dict[str, object]] = []
    cases.extend(
        _case(f"young-active-{index}", age_days=2, idle_days=1) for index in range(27)
    )
    cases.extend(
        _case(f"young-stale-{index}", age_days=5, idle_days=4) for index in range(7)
    )
    cases.extend(
        _case(f"backlog-active-{index}", age_days=10, idle_days=2) for index in range(5)
    )
    cases.extend(
        _case(f"backlog-stale-{index}", age_days=15, idle_days=4) for index in range(11)
    )

    table = _analytics(cases).chart_tables["age_idle_action_matrix"]

    assert table["action_bucket"].value_counts().to_dict() == {
        "young_active": 27,
        "backlog_stale": 11,
        "young_stale": 7,
        "backlog_active": 5,
    }
    assert len(table) == table.attrs["total_open_count"] == 50


def test_action_matrix_uses_end_step_not_status_for_open_population() -> None:
    records = [
        {
            "packageID": "end-in-progress",
            "packageName": "End package",
            "workflowName": "Workflow A",
            "stepName": "End",
            "status": "InProgress",
            "submissionDate": "2026-07-25T12:00:00Z",
            "lastActivityDate": "2026-07-27T12:00:00Z",
        },
        {
            "packageID": "review-completed",
            "packageName": "Review package",
            "workflowName": "Workflow A",
            "stepName": "Review",
            "status": "Completed",
            "submissionDate": "2026-07-25T12:00:00Z",
            "lastActivityDate": "2026-07-27T12:00:00Z",
        },
    ]
    normalized = normalize_records(
        records,
        DashboardConfig(),
        generated_at=GENERATED_AT,
    )

    analytics = _analytics(normalized.to_dict("records"))
    table = analytics.chart_tables["age_idle_action_matrix"]

    assert normalized.set_index("record_id")["is_terminal"].to_dict() == {
        "end-in-progress": True,
        "review-completed": False,
    }
    assert table["record_id"].tolist() == ["review-completed"]


def test_invalid_or_incomplete_timing_is_excluded_and_disclosed() -> None:
    cases = [
        _case("valid", age_days=5, idle_days=1),
        _case("missing-age", age_days=None, idle_days=1),
        _case("missing-idle", age_days=5, idle_days=None),
        _case("future-submission", age_days=-1, idle_days=0),
        _case("future-activity", age_days=5, idle_days=-1),
        _case("activity-before-submission", age_days=2, idle_days=3),
    ]

    table = _analytics(cases).chart_tables["age_idle_action_matrix"]
    chart = _age_idle_action_matrix_chart(table)

    assert table["record_id"].tolist() == ["valid"]
    assert table.attrs["total_open_count"] == 6
    assert chart.layout.meta["valid_count"] == 1
    assert chart.layout.meta["total_open_count"] == 6


def test_chart_uses_square_root_positions_and_privacy_limited_hover() -> None:
    cases = [
        _case(
            "package-14",
            age_days=14,
            idle_days=3,
            step_name="Faculty Evaluator - Initial Review",
            item_label="Student Secret Name",
            owner="Secret Submitter",
        ),
        _case("package-120", age_days=120, idle_days=100),
    ]
    table = _analytics(cases).chart_tables["age_idle_action_matrix"]
    chart = _age_idle_action_matrix_chart(table)
    trace = next(
        trace
        for trace in chart.data
        if trace.name == "Faculty Evaluator - Initial Review"
    )

    assert list(table.columns) == [
        "record_id",
        "step_name",
        "age_days",
        "idle_days",
        "last_activity_at",
        "action_bucket",
        "action_order",
    ]
    assert trace.x[0] == math.sqrt(14)
    assert trace.y[0] == math.sqrt(3)
    assert chart.layout.meta["axis_transform"] == "square_root"
    assert "14" in chart.layout.xaxis.ticktext
    assert "3" in chart.layout.yaxis.ticktext
    assert "%{customdata[0]}" not in trace.hovertemplate
    assert "Package ID" not in trace.hovertemplate
    assert "Last activity: %{customdata[4]}" in trace.hovertemplate
    assert "Student Secret Name" not in str(chart.to_plotly_json())
    assert "Secret Submitter" not in str(chart.to_plotly_json())
    assert trace.customdata[0][0] == "package-14"
    assert trace.customdata[0][4] == "2026-07-24 12:00 PM EDT"
    assert set(ACTION_BUCKET_LABELS).issuperset(
        row[5] for trace in chart.data for row in trace.customdata
    )


def test_dashboard_drilldown_is_hidden_and_contains_only_safe_fields(
    tmp_path,
) -> None:
    case = _case(
        "safe-package-id",
        age_days=2,
        idle_days=1,
        item_label="Student Secret Name",
        owner="Secret Submitter",
    )
    analytics = _analytics([case])
    output_path = tmp_path / "dashboard.html"

    render_dashboard(
        df=pd.DataFrame([case]),
        analytics=analytics,
        history=pd.DataFrame(),
        owner_history=pd.DataFrame(),
        output_path=output_path,
    )
    html_text = output_path.read_text(encoding="utf-8")

    assert 'id="age-idle-action-drilldown"' in html_text
    assert 'id="age-idle-action-controls"' in html_text
    assert 'aria-labelledby="age-idle-action-drilldown-title" hidden' in html_text
    assert 'data-action-bucket="young_active"' in html_text
    assert 'plot.on("plotly_click"' in html_text
    assert 'clear.addEventListener("click"' in html_text
    assert "window.requestAnimationFrame" in html_text
    assert "element.scrollIntoView({" in html_text
    assert 'window.matchMedia("(prefers-reduced-motion: reduce)")' in html_text
    assert "scrollToDrilldown = false" in html_text
    assert "if (scrollToDrilldown) scrollToElement(drilldown)" in html_text
    assert "scrollToElement(controls" in html_text
    assert 'button.getAttribute("aria-pressed") === "true"' in html_text
    assert "activeButton.focus({ preventScroll: true })" in html_text
    assert "scroll-margin-top: 24px" in html_text
    assert "right.idle_days - left.idle_days" in html_text
    assert "safe-package-id" in html_text
    assert "Student Secret Name" not in html_text
    assert "Secret Submitter" not in html_text
    assert "<th>Package ID</th>" in html_text
    assert "<th>Workflow step</th>" in html_text
    assert "<th>Case Age (Days)</th>" in html_text
    assert "<th>Days Since Last Activity</th>" in html_text
    assert "<th>Last activity</th>" in html_text
    assert "2026-07-26 12:00 PM EDT" in html_text
