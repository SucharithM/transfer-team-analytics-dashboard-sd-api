import pandas as pd

from workflow_dashboard.dashboard_html import (
    _bar_chart,
    _category_color,
    _donut_chart,
    _submitted_by_date_heatmap,
)


def test_staff_member_e_uses_pinned_light_pink_in_staff_category_charts() -> None:
    roster = (
        "Staff Member A",
        "Staff Member B",
        "Staff Member C",
        "Staff Member D",
        "Staff Member E",
    )
    table = pd.DataFrame(
        {
            "owner": ["Staff Member E", "Staff Member A"],
            "count": [12, 5],
        }
    )

    assert _category_color(
        "Staff Member E",
        "staff",
        category_order=roster,
    ) == "#F48FB1"
    assert _category_color(
        " Staff  Member E ",
        "staff",
        category_order=tuple(reversed(roster)),
    ) == "#F48FB1"
    assert _category_color(
        "Staff Member A",
        "staff",
        category_order=roster,
    ) == "#2563eb"

    donut = _donut_chart(
        table,
        "owner",
        "count",
        "Open cases",
        color_dimension="staff",
        category_order=roster,
    )
    bar = _bar_chart(
        table,
        "owner",
        "count",
        "Submission volume",
        "Records",
        color_dimension="staff",
        category_order=roster,
    )
    donut_colors = dict(
        zip(donut.data[0].customdata, donut.data[0].marker.colors)
    )
    bar_colors = dict(zip(bar.data[0].y, bar.data[0].marker.color))
    assert donut_colors["Staff Member E"] == "#F48FB1"
    assert bar_colors["Staff Member E"] == "#F48FB1"


def test_staff_heatmap_keeps_shared_blue_intensity_scale() -> None:
    table = pd.DataFrame(
        {
            "owner": ["Staff Member E", "Staff Member A"],
            "submitted_date": ["2026-07-29", "2026-07-29"],
            "count": [12, 5],
        }
    )

    heatmap = _submitted_by_date_heatmap(table)
    colorscale = [color for _, color in heatmap.data[0].colorscale]
    assert "#F48FB1" not in colorscale
    assert colorscale == ["#e8f0ff", "#2563eb"]


def test_status_chart_is_a_largest_first_direct_labeled_bar() -> None:
    figure = _bar_chart(
        pd.DataFrame(
            {
                "status": ["Completed", "Needs Review", "In Progress"],
                "count": [30, 8, 12],
            }
        ),
        "status",
        "count",
        "Cases by Status",
        "Records",
        color_dimension="status",
        largest_first=True,
    )

    trace = figure.data[0]
    assert trace.type == "bar"
    assert trace.orientation == "h"
    assert list(trace.y) == ["Completed", "In Progress", "Needs Review"]
    assert list(trace.text) == [30, 12, 8]
    assert trace.textposition == "outside"
    assert list(trace.marker.color) == [
        _category_color("Completed", "status"),
        _category_color("In Progress", "status"),
        _category_color("Needs Review", "status"),
    ]
    assert figure.layout.yaxis.autorange == "reversed"
