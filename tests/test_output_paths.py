import pandas as pd

from workflow_dashboard.generation import _run_output_paths


def test_dashboard_outputs_share_title_based_filename(tmp_path) -> None:
    generated_at = pd.Timestamp("2026-07-21T16:30:45.123456Z")

    csv_path, html_path, xlsx_path = _run_output_paths(
        tmp_path,
        generated_at,
        "Transfer Credit Executive Overview",
    )

    assert csv_path.name == "normalized_records_2026-07-21_12-30-45-123456_EDT.csv"
    expected_stem = (
        "transfer_credit_executive_overview_2026-07-21_12-30-45-123456_EDT"
    )
    assert html_path.name == f"{expected_stem}.html"
    assert xlsx_path.name == f"{expected_stem}.xlsx"
    assert html_path.parent == xlsx_path.parent == csv_path.parent


def test_dashboard_filename_has_safe_fallback(tmp_path) -> None:
    _, html_path, xlsx_path = _run_output_paths(
        tmp_path,
        pd.Timestamp("2026-07-21T16:30:45Z"),
        "---",
    )

    assert html_path.name.startswith("workflow_dashboard_")
    assert xlsx_path.name.startswith("workflow_dashboard_")
