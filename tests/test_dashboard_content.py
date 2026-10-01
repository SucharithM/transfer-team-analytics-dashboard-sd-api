import pytest

from workflow_dashboard.analytics import build_analytics
from workflow_dashboard.config import DashboardConfig
from workflow_dashboard.dashboard_content import (
    CHART_CONTENT,
    EVALUATION_TYPE_TABLE,
    KPI_CONTENT,
    SECTION_CONTENT,
    WORKFLOW_LEGEND,
    WORKBOOK,
)
from workflow_dashboard.dashboard_html import _kpi_html

from .test_analytics_cohorts import GENERATED_AT, sample_cases

EXPECTED_KPI_KEYS = {
    "total_records",
    "in_the_works",
    "cases_closed_today",
    "total_cases_closed",
    "typical_wait_time",
    "typical_idle_time",
    "notable_observations",
}

EXPECTED_CHART_KEYS = {
    "in_the_works_by_step",
    "status_mix",
    "aging_by_step",
    "workflow_aging_matrix",
    "age_idle_action_matrix",
    "owner_workload",
    "submitted_by_workload",
    "submitted_by_date_activity",
    "closed_by_month",
    "backlog_trend",
    "daily_closures",
    "age_trend",
    "recent_closures",
}


def test_content_catalog_covers_all_dashboard_components() -> None:
    assert set(KPI_CONTENT) == EXPECTED_KPI_KEYS
    assert set(CHART_CONTENT) == EXPECTED_CHART_KEYS
    assert all(
        item.label.strip()
        and item.format_help(
            valid_count=1,
            total_count=1,
            minimum_completeness="95%",
        ).strip()
        for item in KPI_CONTENT.values()
    )
    assert all(
        item.title.strip() and item.help_text.strip() for item in CHART_CONTENT.values()
    )
    assert set(SECTION_CONTENT) == {
        "overview",
        "operations",
        "evaluation_types",
        "staff",
        "trends",
        "exceptions",
    }
    assert set(WORKBOOK.sheet_names) == {
        "summary",
        "normalized_records",
        "in_the_works",
        "backlog",
        "submitted_by_activity",
        "daily_closures",
        "closed_by_month",
        "exceptions",
        "history_trends",
        "owner_history",
        "completion_history",
    }


def test_current_open_chart_titles_and_age_help_match_dashboard_presentation() -> None:
    assert CHART_CONTENT["in_the_works_by_step"].title == "Open Cases by Workflow Step"
    assert CHART_CONTENT["status_mix"].title == "Cases by Status"
    assert "reached End appear as Completed" in CHART_CONTENT["status_mix"].help_text
    assert SECTION_CONTENT["evaluation_types"].eyebrow == "Case Overview"
    assert (
        SECTION_CONTENT["evaluation_types"].title
        == "Evaluation Cases by Evaluation Type"
    )
    assert EVALUATION_TYPE_TABLE.title == "Evaluation Progress"
    assert "Completed cases have reached End" in (EVALUATION_TYPE_TABLE.help_text)
    assert EVALUATION_TYPE_TABLE.header_labels["total_count"] == "Total Cases"
    assert set(EVALUATION_TYPE_TABLE.header_labels) == {
        "evaluation_type",
        "total_count",
        "in_progress_count",
        "completed_count",
        "completion_rate",
        "backlog_summary",
        "median_open_age_summary",
        "median_completion_summary",
    }
    assert CHART_CONTENT["owner_workload"].title == "Open Cases by Submitter"
    assert "valid/total" not in CHART_CONTENT["aging_by_step"].help_text
    assert "completeness" not in CHART_CONTENT["aging_by_step"].help_text
    assert (
        "Cases without usable dates" in CHART_CONTENT["workflow_aging_matrix"].help_text
    )
    assert (
        CHART_CONTENT["age_idle_action_matrix"].title
        == "Open Cases: Time and Activity - Risk Overview"
    )
    assert "since submission" in (CHART_CONTENT["age_idle_action_matrix"].help_text)
    assert "Select a group or dot" in (
        CHART_CONTENT["age_idle_action_matrix"].help_text
    )
    assert CHART_CONTENT["recent_closures"].title == "Cases Completed — Last 7 Days"
    assert "last report saved" in CHART_CONTENT["backlog_trend"].help_text
    assert "last report saved" in CHART_CONTENT["age_trend"].help_text


def test_process_guide_uses_case_flow_order() -> None:
    assert [item.title for item in WORKFLOW_LEGEND.items] == [
        "Transcript Evaluator",
        "Faculty Evaluator – Initial Review",
        "Transcript Evaluator – Post-Faculty Review",
        "Transcript Evaluator – Pending Student Syllabi",
        "Faculty Evaluator – Second Review",
        "Transcript Evaluator – Final Review",
    ]


def test_dynamic_kpi_help_uses_named_content_values() -> None:
    help_text = KPI_CONTENT["typical_wait_time"].format_help(
        valid_count=1,
        total_count=10,
        minimum_completeness="95%",
    )

    assert "Based on 1 of 10 cases" in help_text
    assert "at least 95% have usable dates" in help_text
    assert "Median means the middle value" in help_text
    assert "including time without activity" in help_text


def test_content_mappings_are_read_only() -> None:
    with pytest.raises(TypeError):
        KPI_CONTENT["new_kpi"] = KPI_CONTENT["total_records"]  # type: ignore[index]


def test_kpi_actions_use_stable_keys_and_labels_remain_display_copy() -> None:
    analytics = build_analytics(
        sample_cases(),
        config=DashboardConfig(),
        generated_at=GENERATED_AT,
    )

    observations = next(
        kpi for kpi in analytics.kpis if kpi.key == "notable_observations"
    )
    kpi_markup = _kpi_html(analytics)

    assert observations.label == "Notable Observations"
    assert kpi_markup.count('href="#problem-rows-table"') == 1


def test_executive_help_avoids_technical_and_timezone_jargon():
    help_texts = [item.help_text for item in CHART_CONTENT.values()] + [
        EVALUATION_TYPE_TABLE.help_text
    ]
    for text in help_texts:
        for phrase in (
            "Eastern",
            "calendar day",
            "square-root",
            "configured",
            "suppressed",
            "interval",
            "completeness",
        ):
            assert phrase not in text
