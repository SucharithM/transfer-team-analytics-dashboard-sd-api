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
    assert figure.layout.showlegend is False
    assert figure.layout.meta["category_values"] == ["6", "2", "2"]
    assert figure.layout.uniformtext.minsize == 11
    assert figure.layout.uniformtext.mode == "hide"


def test_donut_chart_keeps_plot_height_independent_of_category_count() -> None:
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
    assert figure.layout.height == 380
    assert figure.layout.margin.b == 10


def test_donut_chart_keeps_existing_empty_state() -> None:
    figure = _donut_chart(
        pd.DataFrame(columns=["category", "count"]),
        "category",
        "count",
        "Open cases",
    )

    assert len(figure.data) == 0
    assert figure.layout.annotations[0].text == "No data available"
    assert figure.layout.height == 240


def test_category_list_preserves_tiny_zero_and_unavailable_values():
    from workflow_dashboard.dashboard_html import _chart_category_list
    table = pd.DataFrame({"label": ["Large", "Tiny <category>", "Zero"], "value": [999, 1, 0]})
    fig = _donut_chart(table, "label", "value", "Counts")
    markup = _chart_category_list(fig, "owner_workload")
    assert "999 · 99.9%" in markup
    assert "1 · 0.1%" in markup
    assert "0 · 0.0%" in markup
    assert "Tiny &lt;category&gt;" in markup
    assert markup.count('aria-pressed="true"') == 3
    table.loc[1, "value"] = float("nan")
    fig = _donut_chart(table, "label", "value", "Age", one_decimal=True, show_percent=False, value_suffix="d")
    markup = _chart_category_list(fig, "aging_by_step")
    assert "<strong>—</strong>" in markup
    assert "<strong>0.0d</strong>" in markup
    assert "%" not in markup
