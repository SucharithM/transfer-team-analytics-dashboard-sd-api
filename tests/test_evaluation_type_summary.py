import pandas as pd
import pytest

from workflow_dashboard.analytics import (
    _evaluation_type,
    _evaluation_type_summary,
)
from workflow_dashboard.dashboard_html import _evaluation_type_summary_html


def _packages() -> pd.DataFrame:
    rows = [
        {
            "record_id": "nr-open-old",
            "item_label": "No-Rule Transcript Evaluation | Person One | College A",
            "is_terminal": False,
            "submitted_at": "2026-07-01T00:00:00Z",
            "last_activity_at": "2026-07-02T00:00:00Z",
            "age_days": 29.0,
        },
        {
            "record_id": "nr-open-new",
            "item_label": "No-Rule Transcript Evaluation | Person Two | College B",
            "is_terminal": False,
            "submitted_at": "2026-07-29T00:00:00Z",
            "last_activity_at": "2026-07-29T12:00:00Z",
            "age_days": 1.0,
        },
        {
            "record_id": "nr-end-2d",
            "item_label": "No-Rule Transcript Evaluation | Person Three | College C",
            "is_terminal": True,
            "submitted_at": "2026-07-01T00:00:00Z",
            "last_activity_at": "2026-07-03T00:00:00Z",
            "age_days": 2.0,
        },
        {
            "record_id": "nr-end-4d",
            "item_label": "No-Rule Transcript Evaluation | Person Four | College D",
            "is_terminal": True,
            "submitted_at": "2026-07-01T00:00:00Z",
            "last_activity_at": "2026-07-05T00:00:00Z",
            "age_days": 4.0,
        },
        {
            "record_id": "intl-valid",
            "item_label": " International Transcript Evaluation | Person Five | College E ",
            "is_terminal": True,
            "submitted_at": "2026-07-01T00:00:00Z",
            "last_activity_at": "2026-07-06T00:00:00Z",
            "age_days": 5.0,
        },
        {
            "record_id": "intl-invalid",
            "item_label": "International Transcript Evaluation | Person Six | College F",
            "is_terminal": True,
            "submitted_at": "2026-07-02T00:00:00Z",
            "last_activity_at": "2026-07-01T00:00:00Z",
            "age_days": -1.0,
        },
        {
            "record_id": "military-open",
            "item_label": "Military Transcript Evaluation | Person Seven | College G",
            "is_terminal": False,
            "submitted_at": "2026-07-29T00:00:00Z",
            "last_activity_at": "2026-07-29T12:00:00Z",
            "age_days": 1.0,
        },
        {
            "record_id": "malformed",
            "item_label": "A label without delimiters or private fields",
            "is_terminal": False,
            "submitted_at": "2026-07-29T00:00:00Z",
            "last_activity_at": "2026-07-29T12:00:00Z",
            "age_days": -1.0,
        },
    ]
    return pd.DataFrame(rows)


def _summary(
    packages: pd.DataFrame,
    *,
    minimum_wait_completeness: float = 0.95,
    minimum_completion_completeness: float = 0.95,
) -> pd.DataFrame:
    open_packages = packages[~packages["is_terminal"]]
    completed = packages[packages["is_terminal"]]
    backlog = open_packages[open_packages["record_id"].eq("nr-open-old")]
    return _evaluation_type_summary(
        packages,
        in_the_works=open_packages,
        backlog=backlog,
        fully_processed=completed,
        minimum_wait_completeness=minimum_wait_completeness,
        minimum_completion_completeness=minimum_completion_completeness,
    )


def test_evaluation_type_parser_uses_only_the_first_of_three_clean_parts() -> None:
    assert (
        _evaluation_type(
            " Continuing Student Transcript Evaluation | Private Person | Private College "
        )
        == "Continuing Student"
    )
    assert _evaluation_type("No-Rule | Private Person | Private College") == "No-Rule"
    assert _evaluation_type("Missing separators") == "Unclassified"
    assert _evaluation_type("Type | | College") == "Unclassified"
    assert _evaluation_type(None) == "Unclassified"


def test_evaluation_type_summary_calculates_inventory_backlog_and_medians() -> None:
    result = _summary(_packages()).set_index("evaluation_type")

    assert list(result.index) == [
        "No-Rule",
        "International",
        "Military",
        "Unclassified",
    ]
    no_rule = result.loc["No-Rule"]
    assert no_rule["total_count"] == 4
    assert no_rule["in_progress_count"] == 2
    assert no_rule["completed_count"] == 2
    assert no_rule["completion_rate"] == pytest.approx(0.5)
    assert no_rule["backlog_count"] == 1
    assert "backlog_rate" not in result.columns
    assert no_rule["open_age_valid_count"] == 2
    assert no_rule["median_open_age_days"] == pytest.approx(15.0)
    assert no_rule["completion_valid_count"] == 2
    assert no_rule["median_completion_days"] == pytest.approx(3.0)

    international = result.loc["International"]
    assert international["in_progress_count"] == 0
    assert international["completed_count"] == 2
    assert international["completion_rate"] == pytest.approx(1.0)
    assert pd.isna(international["median_open_age_days"])
    assert international["completion_valid_count"] == 1
    assert pd.isna(international["median_completion_days"])

    assert result.loc["Military", "median_open_age_days"] == pytest.approx(1.0)
    assert pd.isna(result.loc["Military", "median_completion_days"])
    assert result.loc["Unclassified", "open_age_valid_count"] == 0
    assert pd.isna(result.loc["Unclassified", "median_open_age_days"])


def test_empty_evaluation_type_summary_omits_backlog_rate() -> None:
    empty = pd.DataFrame()
    result = _evaluation_type_summary(
        empty,
        in_the_works=empty,
        backlog=empty,
        fully_processed=empty,
        minimum_wait_completeness=0.95,
        minimum_completion_completeness=0.95,
    )

    assert "backlog_count" in result.columns
    assert "backlog_rate" not in result.columns


def test_evaluation_type_summary_thresholds_are_independent() -> None:
    result = _summary(
        _packages(),
        minimum_wait_completeness=1.0,
        minimum_completion_completeness=0.5,
    ).set_index("evaluation_type")

    assert result.loc["International", "median_completion_days"] == pytest.approx(5.0)
    assert result.loc["No-Rule", "median_open_age_days"] == pytest.approx(15.0)
    assert pd.isna(result.loc["Unclassified", "median_open_age_days"])


def test_low_volume_type_keeps_completion_sample_visible() -> None:
    durations = [78.4, 78.5, 78.6, 78.8, 78.9, 79.0]
    continuing = pd.DataFrame(
        [
            {
                "record_id": f"continuing-{index}",
                "item_label": (
                    "Continuing Student Transcript Evaluation "
                    f"| Private Person {index} | Private College"
                ),
                "is_terminal": True,
                "submitted_at": "2026-01-01T00:00:00Z",
                "last_activity_at": (
                    pd.Timestamp("2026-01-01T00:00:00Z")
                    + pd.Timedelta(days=duration)
                ),
                "age_days": duration,
            }
            for index, duration in enumerate(durations)
        ]
    )
    result = _evaluation_type_summary(
        continuing,
        in_the_works=continuing.iloc[0:0],
        backlog=continuing.iloc[0:0],
        fully_processed=continuing,
        minimum_wait_completeness=0.95,
        minimum_completion_completeness=0.95,
    ).iloc[0]

    assert result["evaluation_type"] == "Continuing Student"
    assert result["total_count"] == 6
    assert result["in_progress_count"] == 0
    assert result["completed_count"] == 6
    assert result["completion_valid_count"] == 6
    assert result["median_completion_days"] == pytest.approx(78.7)


def test_evaluation_type_summary_html_is_simplified_and_excludes_pii() -> None:
    html_text = _evaluation_type_summary_html(_summary(_packages()))

    assert "<th scope=\"row\" class=\"evaluation-type-name\">No-Rule</th>" in html_text
    assert html_text.count("50.0%") == 1
    assert "secondary-value" not in html_text
    assert "metric-sample" not in html_text
    assert "15.0d" in html_text
    assert "2/2 valid" not in html_text
    assert "1/2 valid" not in html_text
    assert "Person" not in html_text
    assert "College" not in html_text
