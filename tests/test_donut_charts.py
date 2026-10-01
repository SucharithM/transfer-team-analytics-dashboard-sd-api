import pandas as pd
import pytest

from workflow_dashboard.dashboard_html import _category_color, _donut_chart


def test_donut_chart_orders_and_displays_complete_category_counts() -> None:
    table = pd.DataFrame(
        {
            "category": ["Beta", "Gamma", "Alpha"],
            "count": [2, 6, 2],
        }
    )

    figure = _donut_chart(
        table,
        "category",
        "count",
        "Open cases",
    )

    trace = figure.data[0]
    assert trace.type == "pie"
    assert trace.hole == pytest.approx(0.58)
    assert trace.sort is False
    assert list(trace.labels) == ["Gamma", "Alpha", "Beta"]
    assert list(trace.values) == [6, 2, 2]
    assert list(trace.customdata) == ["Gamma", "Alpha", "Beta"]
    assert list(trace.marker.colors) == [
        _category_color(label, "generic")
        for label in ["Gamma", "Alpha", "Beta"]
    ]
    assert trace.marker.line.color == "#ffffff"
    assert trace.marker.line.width == 2
    assert trace.texttemplate == "%{value:,}<br>%{percent:.1%}"
    assert "Cases: %{value:,}" in trace.hovertemplate
    assert "Share: %{percent:.1%}" in trace.hovertemplate
    assert figure.layout.annotations[0].text == "<b>10</b>"
    assert figure.layout.height == 380
    assert figure.layout.legend.orientation == "h"
    assert figure.layout.uniformtext.minsize == 11
    assert figure.layout.uniformtext.mode == "hide"


def test_donut_chart_wraps_labels_and_reserves_high_cardinality_height() -> None:
    table = pd.DataFrame(
        {
            "category": [
                "A workflow category with a long name",
                "Category B",
                "Category C",
                "Category D",
                "Category E",
            ],
            "count": [5, 4, 3, 2, 1],
        }
    )

    figure = _donut_chart(table, "category", "count", "Open cases")

    assert list(figure.data[0].values) == [5, 4, 3, 2, 1]
    assert "<br>" in figure.data[0].labels[0]
    assert len(figure.data[0].labels) == len(table)
    assert figure.layout.height == 428
    assert figure.layout.margin.b == 140


def test_donut_chart_keeps_existing_empty_state() -> None:
    figure = _donut_chart(
        pd.DataFrame(columns=["category", "count"]),
        "category",
        "count",
        "Open cases",
    )

    assert len(figure.data) == 0
    assert figure.layout.annotations[0].text == "No data available"
    assert figure.layout.height == 320
