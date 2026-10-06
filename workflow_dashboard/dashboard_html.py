"""Standalone HTML dashboard rendering with embedded Plotly."""

from __future__ import annotations

import hashlib
import html
import json
import math
import textwrap
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.io import to_html

from . import dashboard_content as content
from .dashboard_print import PRINT_STYLES, export_script
from .analytics import (
    AGING_BAND_LABELS,
    AnalyticsBundle,
)
from .number_format import format_one_decimal
from .time_utils import dashboard_time_series, dashboard_timestamp

PRIMARY = "#2563eb"
PRIMARY_DARK = "#1d4ed8"
TEXT = "#172033"
MUTED = "#5f6f85"
BORDER = "#dce4ee"
BG = "#eef2f7"
SURFACE_MUTED = "#f8fafc"
COLORWAY = ["#2563eb", "#0f9f8f", "#7c3aed", "#e8792e", "#db3b5a", "#0891b2", "#64748b"]
CATEGORY_COLORWAY = (
    "#2563eb",
    "#0f9f8f",
    "#7c3aed",
    "#e8792e",
    "#db3b5a",
    "#0891b2",
    "#64748b",
    "#ca8a04",
    "#be185d",
    "#4f46e5",
)
STATUS_COLORS = {
    "completed": "#2f855a",
    "needs review": "#e8792e",
    "in progress": "#2563eb",
    "no status": "#64748b",
}
STAFF_COLORS = {
    "staff member e": "#F48FB1",
    content.OTHER_SUBMITTERS.casefold(): "#475569",
    content.MISSING_SUBMITTER.casefold(): "#737373",
}
AGING_RISK_COLORS = (
    "#2f855a",
    "#65a30d",
    "#c89b19",
    "#e8792e",
    "#dc5a45",
    "#b4233c",
)
ACTION_BUCKET_COLORS = {
    "young_active": "rgba(47, 133, 90, 0.07)",
    "young_stale": "rgba(200, 155, 25, 0.08)",
    "backlog_active": "rgba(232, 121, 46, 0.08)",
    "backlog_stale": "rgba(180, 35, 60, 0.08)",
}


def _category_key(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split()).casefold()


def _stable_fallback_color(value: object) -> str:
    digest = hashlib.sha256(_category_key(value).encode("utf-8")).digest()
    return CATEGORY_COLORWAY[int.from_bytes(digest[:4], "big") % len(CATEGORY_COLORWAY)]


def _category_color(
    value: object,
    dimension: str,
    *,
    category_order: tuple[str, ...] = (),
) -> str:
    """Resolve one stable color from semantic dimension and category label."""

    key = _category_key(value)
    if dimension == "status":
        if key.startswith("other (") and key.endswith(" statuses)"):
            return "#7c3aed"
        return STATUS_COLORS.get(key, _stable_fallback_color(value))
    if dimension == "workflow_step":
        step_colors = {
            _category_key(step): CATEGORY_COLORWAY[index % len(CATEGORY_COLORWAY)]
            for index, step in enumerate(content.WORKFLOW_STEP_ORDER)
        }
        return step_colors.get(key, _stable_fallback_color(value))
    if dimension == "staff":
        if key in STAFF_COLORS:
            return STAFF_COLORS[key]
        staff_colors = {
            _category_key(member): ("#F48FB1" if index == 4 else CATEGORY_COLORWAY[index % len(CATEGORY_COLORWAY)])
            for index, member in enumerate(category_order)
        }
        return staff_colors.get(key, _stable_fallback_color(value))
    return _stable_fallback_color(value)


def _category_colors(
    values: list[object],
    dimension: str,
    *,
    category_order: tuple[str, ...] = (),
) -> list[str]:
    return [
        _category_color(
            value,
            dimension,
            category_order=category_order,
        )
        for value in values
    ]


def _format_generated_at(generated_at: pd.Timestamp) -> str:
    local = dashboard_timestamp(generated_at)
    time_text = local.strftime("%I:%M %p").lstrip("0")
    return f"{local.strftime('%Y-%m-%d')} at {time_text} {local.strftime('%Z')}"


def _wrap_label(value: object, width: int = 26) -> str:
    text = (
        content.COMMON.missing_value
        if value is None or pd.isna(value) or str(value).strip() == ""
        else str(value)
    )
    return "<br>".join(textwrap.wrap(text, width=width)) or text


def _empty_figure(title: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        title=dict(text=""),
        annotations=[
            dict(
                text=content.COMMON.empty_figure,
                x=0.5,
                y=0.5,
                xref="paper",
                yref="paper",
                showarrow=False,
                font=dict(color=MUTED),
            )
        ],
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        height=320,
        margin=dict(l=32, r=20, t=20, b=34),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=SURFACE_MUTED,
    )
    return fig


def _base_layout(fig: go.Figure, title: str, *, height: int = 340) -> go.Figure:
    fig.update_layout(
        title=dict(text=""),
        font=dict(
            family="Segoe UI, Inter, system-ui, -apple-system, sans-serif",
            color=TEXT,
            size=13,
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=SURFACE_MUTED,
        margin=dict(l=150, r=42, t=20, b=58),
        height=height,
        hoverlabel=dict(
            bgcolor=TEXT, bordercolor=TEXT, font=dict(color="#ffffff", size=12)
        ),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.2,
            xanchor="left",
            x=0,
            font=dict(size=12, color=MUTED),
        ),
        colorway=COLORWAY,
    )
    fig.update_xaxes(
        gridcolor="#dbe4ee",
        linecolor="#dbe4ee",
        tickcolor="#dbe4ee",
        zeroline=False,
        title_font=dict(size=12),
        tickfont=dict(color=MUTED),
    )
    fig.update_yaxes(
        gridcolor="#dbe4ee",
        linecolor="#dbe4ee",
        tickcolor="#dbe4ee",
        zeroline=False,
        title_font=dict(size=12),
        tickfont=dict(color=MUTED),
    )
    return fig


def _bar_chart(
    table: pd.DataFrame,
    label_col: str,
    value_col: str,
    title: str,
    x_title: str,
    *,
    one_decimal: bool = False,
    dynamic_height: bool = False,
    color_dimension: str = "generic",
    category_order: tuple[str, ...] = (),
    largest_first: bool = False,
) -> go.Figure:
    if table.empty:
        return _empty_figure(title)
    ordered = table.copy()
    if largest_first:
        ordered["_sort_label"] = ordered[label_col].astype(str).str.casefold()
        ordered = (
            ordered.sort_values(
                [value_col, "_sort_label"],
                ascending=[False, True],
                kind="stable",
            )
            .drop(columns="_sort_label")
            .reset_index(drop=True)
        )
    display_values = (
        [format_one_decimal(value) for value in ordered[value_col]]
        if one_decimal
        else ordered[value_col]
    )
    hovertemplate = "%{y}<br>" + x_title + ": %{x}<extra></extra>"
    customdata = None
    if one_decimal:
        customdata = display_values
        hovertemplate = "%{y}<br>" + x_title + ": %{customdata}<extra></extra>"
    fig = go.Figure(
        go.Bar(
            x=ordered[value_col],
            y=[_wrap_label(value) for value in ordered[label_col]],
            orientation="h",
            marker=dict(
                color=_category_colors(
                    ordered[label_col].tolist(),
                    color_dimension,
                    category_order=category_order,
                )
            ),
            text=display_values,
            textposition="outside",
            cliponaxis=False,
            customdata=customdata,
            hovertemplate=hovertemplate,
        )
    )
    height = max(340, 100 + 28 * len(ordered)) if dynamic_height else 340
    _base_layout(fig, title, height=height)
    fig.update_xaxes(title=x_title, rangemode="tozero", automargin=True)
    fig.update_yaxes(
        title="",
        automargin=True,
        autorange="reversed" if largest_first else True,
    )
    fig.update_layout(showlegend=False)
    return fig


def _donut_chart(
    table: pd.DataFrame,
    label_col: str,
    value_col: str,
    title: str,
    *,
    value_label: str = content.CHART_LABELS.records,
    one_decimal: bool = False,
    value_suffix: str = "",
    show_percent: bool = True,
    center_text: str | None = None,
    color_dimension: str = "generic",
    category_order: tuple[str, ...] = (),
) -> go.Figure:
    if table.empty:
        return _empty_figure(title)

    ordered = table.copy()
    ordered["_donut_sort_label"] = ordered[label_col].astype(str).str.casefold()
    ordered = (
        ordered.sort_values(
            [value_col, "_donut_sort_label"],
            ascending=[False, True],
            kind="stable",
        )
        .drop(columns="_donut_sort_label")
        .reset_index(drop=True)
    )
    raw_labels = [str(value) for value in ordered[label_col]]
    wrapped_labels = [_wrap_label(value, 30) for value in ordered[label_col]]
    values = pd.to_numeric(ordered[value_col], errors="coerce").fillna(0)
    displayed_center = (
        center_text if center_text is not None else f"{int(values.sum()):,}"
    )
    value_template = (
        f"%{{value:.1f}}{value_suffix}"
        if one_decimal
        else f"%{{value:,}}{value_suffix}"
    )
    texttemplate = (
        value_template + "<br>%{percent:.1%}" if show_percent else value_template
    )
    hovertemplate = "%{customdata}<br>" + value_label + ": " + value_template
    if show_percent:
        hovertemplate += "<br>" + content.CHART_LABELS.share + ": %{percent:.1%}"
    hovertemplate += "<extra></extra>"
    extra_categories = max(0, len(ordered) - 3)
    height = 380 + 24 * extra_categories
    bottom_margin = 92 + 24 * extra_categories
    colors = _category_colors(
        raw_labels,
        color_dimension,
        category_order=category_order,
    )

    fig = go.Figure(
        go.Pie(
            labels=wrapped_labels,
            values=values,
            customdata=raw_labels,
            hole=0.58,
            sort=False,
            direction="clockwise",
            marker=dict(
                colors=colors,
                line=dict(color="#ffffff", width=2),
            ),
            textposition="inside",
            texttemplate=texttemplate,
            textfont=dict(color="#ffffff", size=12),
            insidetextorientation="horizontal",
            hovertemplate=hovertemplate,
        )
    )
    _base_layout(fig, title, height=height)
    fig.update_layout(
        margin=dict(l=24, r=24, t=20, b=bottom_margin),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.08,
            xanchor="center",
            x=0.5,
            font=dict(size=12, color=MUTED),
        ),
        uniformtext=dict(minsize=11, mode="hide"),
        annotations=[
            dict(
                text=f"<b>{displayed_center}</b>",
                x=0.5,
                y=0.5,
                xref="paper",
                yref="paper",
                showarrow=False,
                font=dict(color=TEXT, size=22),
            )
        ],
    )
    return fig


def _latest_daily_history(history: pd.DataFrame) -> pd.DataFrame:
    """Select the latest saved run from each Eastern calendar day."""

    if history.empty or "generated_at" not in history.columns:
        return history.iloc[0:0].copy()

    snapshots = history.copy()
    snapshots["_source_order"] = range(len(snapshots))
    snapshots["_local_run_time"] = dashboard_time_series(snapshots["generated_at"])
    snapshots = snapshots.dropna(subset=["_local_run_time"])
    if snapshots.empty:
        return snapshots.drop(columns=["_source_order", "_local_run_time"])

    snapshots["_snapshot_date"] = snapshots["_local_run_time"].dt.date
    snapshots["_run_id_sort"] = (
        snapshots["run_id"].fillna("").astype(str)
        if "run_id" in snapshots.columns
        else ""
    )
    latest = (
        snapshots.sort_values(
            [
                "_snapshot_date",
                "_local_run_time",
                "_run_id_sort",
                "_source_order",
            ],
            kind="stable",
        )
        .drop_duplicates(subset=["_snapshot_date"], keep="last")
        .sort_values("_snapshot_date", kind="stable")
    )
    return latest.drop(
        columns=[
            "_source_order",
            "_local_run_time",
            "_snapshot_date",
            "_run_id_sort",
        ]
    ).reset_index(drop=True)


def _line_chart(
    history: pd.DataFrame,
    metric: str,
    title: str,
    y_title: str,
    *,
    one_decimal: bool = False,
    coverage_columns: tuple[str, str] | None = None,
) -> go.Figure:
    if history.empty or metric not in history.columns:
        return _empty_figure(title)
    history = _latest_daily_history(history)
    history = history.dropna(subset=[metric])
    if history.empty:
        return _empty_figure(title)
    local_run_times = dashboard_time_series(history["generated_at"])
    run_time_labels = local_run_times.dt.strftime("%Y-%m-%d %I:%M %p %Z")
    customdata = run_time_labels
    hovertemplate = "%{customdata}<br>" + y_title + ": %{y}<extra></extra>"
    if one_decimal:
        display_values = [format_one_decimal(value) for value in history[metric]]
        customdata = list(zip(run_time_labels, display_values))
        hovertemplate = (
            "%{customdata[0]}<br>" + y_title + ": %{customdata[1]}<extra></extra>"
        )
        if coverage_columns is not None and set(coverage_columns).issubset(
            history.columns
        ):
            valid_col, total_col = coverage_columns
            coverage_labels = [
                content.COMMON.valid_count_template.format(
                    valid=int(valid),
                    total=int(total),
                )
                for valid, total in zip(history[valid_col], history[total_col])
            ]
            customdata = list(zip(run_time_labels, display_values, coverage_labels))
            hovertemplate = (
                "%{customdata[0]}<br>"
                + y_title
                + ": %{customdata[1]}<br>"
                + content.CHART_LABELS.coverage
                + ": %{customdata[2]}<extra></extra>"
            )
    fig = go.Figure(
        go.Scatter(
            x=local_run_times.dt.tz_localize(None).dt.normalize(),
            y=history[metric],
            mode="lines+markers",
            line=dict(color=PRIMARY, width=3),
            marker=dict(size=7),
            customdata=customdata,
            hovertemplate=hovertemplate,
        )
    )
    _base_layout(fig, title, height=310)
    fig.update_layout(margin=dict(l=72, r=36, t=20, b=58))
    fig.update_xaxes(title=content.CHART_LABELS.date)
    if len(history) == 1:
        day = local_run_times.dt.tz_localize(None).dt.normalize().iloc[0]
        fig.update_xaxes(
            range=[day - pd.Timedelta(days=1), day + pd.Timedelta(days=1)],
            tickvals=[day],
            tickformat="%b %d, %Y",
        )
    fig.update_yaxes(title=y_title, rangemode="tozero")
    return fig


def _aging_by_step_chart(
    table: pd.DataFrame,
    *,
    overall_age_days: float | None = None,
) -> go.Figure:
    title = content.CHART_CONTENT["aging_by_step"].title
    required_columns = {"step_name", "age_days"}
    if table.empty or not required_columns.issubset(table.columns):
        return _empty_figure(title)

    table = table.dropna(subset=["step_name"]).copy()
    if table.empty:
        return _empty_figure(title)

    return _donut_chart(
        table,
        "step_name",
        "age_days",
        title,
        value_label=content.CHART_LABELS.median_age,
        one_decimal=True,
        value_suffix="d",
        show_percent=False,
        center_text=format_one_decimal(
            overall_age_days,
            suffix="d",
            missing="—",
        ),
        color_dimension="workflow_step",
    )


def _daily_closures_chart(table: pd.DataFrame) -> go.Figure:
    title = content.CHART_CONTENT["daily_closures"].title
    required_columns = {"closed_date", "closed_count", "rolling_7_day_avg"}
    if table.empty or not required_columns.issubset(table.columns):
        return _empty_figure(title)
    table = table.dropna(subset=["closed_date", "closed_count"])
    if table.empty:
        return _empty_figure(title)

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=table["closed_date"],
            y=table["closed_count"],
            name=content.CHART_LABELS.daily_closures,
            marker=dict(color=PRIMARY),
            hovertemplate=(
                content.CHART_LABELS.close_date
                + ": %{x|%Y-%m-%d}<br>"
                + content.CHART_LABELS.cases_closed
                + ": %{y}<extra></extra>"
            ),
        )
    )
    rolling = table.dropna(subset=["rolling_7_day_avg"])
    fig.add_trace(
        go.Scatter(
            x=rolling["closed_date"],
            y=rolling["rolling_7_day_avg"],
            name=content.CHART_LABELS.seven_day_average,
            mode="lines+markers",
            line=dict(color=COLORWAY[1], width=3),
            marker=dict(size=6),
            customdata=[
                format_one_decimal(value) for value in rolling["rolling_7_day_avg"]
            ],
            hovertemplate=(
                content.CHART_LABELS.date
                + ": %{x|%Y-%m-%d}<br>"
                + content.CHART_LABELS.seven_day_average
                + ": %{customdata}<extra></extra>"
            ),
        )
    )
    _base_layout(fig, title, height=380)
    fig.update_layout(
        margin=dict(l=72, r=36, t=70, b=76),
        bargap=0.15,
        legend=dict(y=1.08, yanchor="bottom"),
    )
    fig.update_xaxes(title=content.CHART_LABELS.close_date)
    fig.update_yaxes(
        title=content.CHART_LABELS.cases_closed,
        rangemode="tozero",
    )
    return fig


def _recent_closures_chart(
    table: pd.DataFrame,
    generated_at: pd.Timestamp,
) -> go.Figure:
    """Plot closure counts for the seven most recent completed Eastern days."""

    chart_copy = content.CHART_CONTENT["recent_closures"]
    required_columns = {"closed_date", "closed_count"}
    if not required_columns.issubset(table.columns):
        return _empty_figure(chart_copy.title)

    generated_date = dashboard_timestamp(generated_at).tz_localize(None).normalize()
    completed_dates = pd.date_range(
        end=generated_date - pd.Timedelta(days=1),
        periods=7,
        freq="D",
    )
    recent = pd.DataFrame({"closed_date": completed_dates})

    observed = table[["closed_date", "closed_count"]].copy()
    observed["closed_date"] = pd.to_datetime(
        observed["closed_date"], errors="coerce"
    ).dt.normalize()
    observed["closed_count"] = pd.to_numeric(observed["closed_count"], errors="coerce")
    observed = (
        observed.dropna(subset=["closed_date", "closed_count"])
        .groupby("closed_date", as_index=False)["closed_count"]
        .sum()
    )
    recent = recent.merge(observed, on="closed_date", how="left")
    recent["closed_count"] = recent["closed_count"].fillna(0).astype(int)
    max_count = int(recent["closed_count"].max())

    fig = go.Figure(
        go.Scatter(
            x=recent["closed_date"],
            y=recent["closed_count"],
            name=content.CHART_LABELS.cases_closed,
            mode="lines+markers",
            line=dict(color=PRIMARY, width=3),
            marker=dict(size=7),
            hovertemplate=(
                content.CHART_LABELS.date
                + ": %{x|%Y-%m-%d}<br>"
                + content.CHART_LABELS.cases_closed
                + ": %{y}<extra></extra>"
            ),
        )
    )
    _base_layout(fig, chart_copy.title, height=330)
    fig.update_layout(
        margin=dict(l=72, r=36, t=20, b=58),
        showlegend=False,
    )
    fig.update_xaxes(title=content.CHART_LABELS.date)
    fig.update_yaxes(
        title=content.CHART_LABELS.cases_closed,
        rangemode="tozero",
        nticks=8,
        dtick=1 if max_count < 8 else None,
    )
    return fig


def _closed_by_month_trend(table: pd.DataFrame) -> go.Figure:
    title = content.CHART_CONTENT["closed_by_month"].title
    required_columns = {
        "closed_month",
        "closed_month_label",
        "closed_count",
        "median_completion_days",
        "completion_valid_count",
        "completion_total_count",
    }
    if table.empty or not required_columns.issubset(table.columns):
        return _empty_figure(title)

    table = table.dropna(
        subset=["closed_month", "closed_month_label", "closed_count"]
    ).copy()
    table["closed_month_start"] = pd.to_datetime(
        table["closed_month"], format="%Y-%m", errors="coerce"
    )
    table = table.dropna(subset=["closed_month_start"])
    if table.empty:
        return _empty_figure(title)

    median_days = [
        (format_one_decimal(value, suffix=" days") if pd.notna(value) else "—")
        for value in table["median_completion_days"]
    ]
    coverage_labels = [
        content.COMMON.valid_count_template.format(
            valid=int(valid),
            total=int(total),
        )
        for valid, total in zip(
            table["completion_valid_count"],
            table["completion_total_count"],
        )
    ]
    hovertemplate = (
        content.CHART_LABELS.close_month
        + ": %{x|%b %Y}<br>"
        + content.CHART_LABELS.closed_cases
        + ": %{y}<br>"
        + content.CHART_LABELS.median_completion
        + ": %{customdata[0]}<br>"
        + content.CHART_LABELS.completion_coverage
        + ": %{customdata[1]}<extra></extra>"
    )
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=table["closed_month_start"],
            y=table["closed_count"],
            name=content.CHART_LABELS.closed_cases,
            marker=dict(color=PRIMARY),
            text=table["closed_count"],
            textposition="outside",
            cliponaxis=False,
            customdata=list(zip(median_days, coverage_labels)),
            hovertemplate=hovertemplate,
        )
    )
    _base_layout(fig, title, height=330)
    fig.update_layout(
        margin=dict(l=72, r=36, t=20, b=76),
        showlegend=False,
    )
    fig.update_xaxes(
        title=content.CHART_LABELS.close_month,
        type="date",
        tickmode="array",
        tickvals=table["closed_month_start"],
        ticktext=table["closed_month_label"],
        automargin=True,
    )
    fig.update_yaxes(
        title=content.CHART_LABELS.closed_cases,
        rangemode="tozero",
    )
    return fig


def _submitted_by_date_heatmap(table: pd.DataFrame) -> go.Figure:
    title = content.CHART_CONTENT["submitted_by_date_activity"].title
    if table.empty:
        return _empty_figure(title)
    pivot = table.pivot_table(
        index="owner",
        columns="submitted_date",
        values="count",
        aggfunc="sum",
        fill_value=0,
    )
    if pivot.empty:
        return _empty_figure(title)
    pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).index]
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=[str(value) for value in pivot.columns],
            y=[_wrap_label(value, 22) for value in pivot.index],
            colorscale=[[0, "#e8f0ff"], [1, PRIMARY]],
            hovertemplate=(
                content.CHART_LABELS.date
                + ": %{x}<br>"
                + content.CHART_LABELS.staff
                + ": %{y}<br>"
                + content.CHART_LABELS.submissions
                + ": %{z}<extra></extra>"
            ),
            colorbar=dict(title=content.CHART_LABELS.submissions),
        )
    )
    _base_layout(fig, title, height=380)
    fig.update_xaxes(title=content.CHART_LABELS.submitted_date)
    fig.update_yaxes(title=content.CHART_LABELS.staff, automargin=True)
    return fig


def _workflow_aging_matrix_chart(table: pd.DataFrame) -> go.Figure:
    title = content.CHART_CONTENT["workflow_aging_matrix"].title
    required_columns = {
        "step_name",
        "step_order",
        "aging_band",
        "band_order",
        "count",
        "step_total",
        "excluded_age_count",
    }
    if table.empty or not required_columns.issubset(table.columns):
        return _empty_figure(title)

    ordered = table.sort_values(["step_order", "band_order"], kind="stable").copy()
    steps = (
        ordered[
            [
                "step_name",
                "step_order",
                "step_total",
                "excluded_age_count",
            ]
        ]
        .drop_duplicates(subset=["step_order"], keep="first")
        .sort_values("step_order", kind="stable")
        .reset_index(drop=True)
    )
    if steps.empty:
        return _empty_figure(title)

    step_orders = list(steps["step_order"])
    step_names = [str(value) for value in steps["step_name"]]
    global_max = max(
        1,
        int(pd.to_numeric(ordered["count"], errors="coerce").fillna(0).max()),
    )
    count_rows: list[list[int]] = []
    for step_order in step_orders:
        step_cells = (
            ordered.loc[ordered["step_order"].eq(step_order)]
            .set_index("aging_band")
            .reindex(AGING_BAND_LABELS)
        )
        count_rows.append(
            pd.to_numeric(step_cells["count"], errors="coerce")
            .fillna(0)
            .astype(int)
            .tolist()
        )

    band_span = global_max + 1
    composite_z = [
        [band_order * band_span + count for band_order, count in enumerate(counts)]
        for counts in count_rows
    ]
    zmax = (len(AGING_BAND_LABELS) - 1) * band_span + global_max
    colorscale: list[list[float | str]] = []
    for band_order, risk_color in enumerate(AGING_RISK_COLORS):
        band_start = band_order * band_span / zmax
        band_end = (band_order * band_span + global_max) / zmax
        colorscale.extend(
            [
                [band_start, SURFACE_MUTED],
                [band_end, risk_color],
            ]
        )

    customdata = [
        [
            [
                step_name,
                int(step_total),
                int(excluded_age_count),
                int(count),
            ]
            for count in counts
        ]
        for step_name, step_total, excluded_age_count, counts in zip(
            step_names,
            steps["step_total"],
            steps["excluded_age_count"],
            count_rows,
        )
    ]
    fig = go.Figure(
        go.Heatmap(
            z=composite_z,
            x=list(AGING_BAND_LABELS),
            y=step_names,
            text=[
                [f"{count:,}" if count else "" for count in counts]
                for counts in count_rows
            ],
            texttemplate="%{text}",
            textfont=dict(color=TEXT, size=13),
            customdata=customdata,
            colorscale=colorscale,
            zmin=0,
            zmax=zmax,
            showscale=False,
            showlegend=False,
            xgap=3,
            ygap=3,
            hoverongaps=False,
            hovertemplate=(
                content.CHART_LABELS.workflow_step
                + ": %{customdata[0]}<br>"
                + content.CHART_LABELS.aging_band
                + ": %{x}<br>"
                + content.CHART_LABELS.open_cases
                + ": %{customdata[3]:,}<br>"
                + content.CHART_LABELS.step_total
                + ": %{customdata[1]:,}<br>"
                + content.CHART_LABELS.age_unavailable
                + ": %{customdata[2]:,}<extra></extra>"
            ),
            meta={"global_max_count": global_max},
            name=title,
        )
    )

    height = max(400, 150 + 45 * len(steps))
    _base_layout(fig, title, height=height)
    fig.update_layout(
        margin=dict(l=250, r=92, t=54, b=34),
        showlegend=False,
    )
    fig.update_xaxes(
        title="",
        side="top",
        categoryorder="array",
        categoryarray=list(AGING_BAND_LABELS),
        tickfont=dict(color=TEXT, size=12),
        showgrid=False,
        automargin=True,
    )
    fig.update_yaxes(
        title="",
        categoryorder="array",
        categoryarray=step_names,
        tickmode="array",
        tickvals=step_names,
        ticktext=[_wrap_label(value, 30) for value in step_names],
        autorange="reversed",
        showgrid=False,
        automargin=True,
    )
    fig.add_annotation(
        x=1.015,
        y=1.08,
        xref="paper",
        yref="paper",
        text=f"<b>{content.CHART_LABELS.step_total}</b>",
        showarrow=False,
        xanchor="left",
        font=dict(color=MUTED, size=12),
    )
    for step_name, step_total in zip(step_names, steps["step_total"]):
        fig.add_annotation(
            x=1.015,
            y=step_name,
            xref="paper",
            yref="y",
            text=f"<b>{int(step_total):,}</b>",
            showarrow=False,
            xanchor="left",
            font=dict(color=TEXT, size=13),
        )
    return fig


def _sqrt_axis_ticks(
    maximum_days: float,
    *required_days: float,
) -> tuple[list[float], list[str]]:
    """Return square-root positions labeled in untransformed days."""

    candidates = {
        0.0,
        1.0,
        3.0,
        7.0,
        14.0,
        30.0,
        60.0,
        90.0,
        120.0,
        180.0,
        365.0,
        *[float(value) for value in required_days],
    }
    upper = max(1.0, float(maximum_days))
    larger_candidates = sorted(value for value in candidates if value >= upper)
    ceiling = (
        larger_candidates[0] if larger_candidates else math.ceil(upper / 365) * 365
    )
    days = sorted(
        value for value in candidates | {float(ceiling)} if 0 <= value <= ceiling
    )
    positions = [math.sqrt(value) for value in days]
    labels = [
        f"{value:g}" if not float(value).is_integer() else f"{int(value):,}"
        for value in days
    ]
    return positions, labels


def _age_idle_action_matrix_chart(table: pd.DataFrame) -> go.Figure:
    """Plot eligible open packages on transformed age and idle-time axes."""

    title = content.CHART_CONTENT["age_idle_action_matrix"].title
    required_columns = {
        "record_id",
        "step_name",
        "age_days",
        "idle_days",
        "last_activity_at",
        "action_bucket",
        "action_order",
    }
    if table.empty or not required_columns.issubset(table.columns):
        return _empty_figure(title)

    backlog_days = float(table.attrs.get("backlog_age_days", 7.0))
    bucket_labels = content.action_bucket_labels(backlog_days)
    old_days = float(table.attrs.get("old_age_days", 14.0))
    stale_days = float(table.attrs.get("stale_idle_days", 3.0))
    total_open = int(table.attrs.get("total_open_count", len(table)))
    valid_count = int(len(table))

    age_days = pd.to_numeric(table["age_days"], errors="coerce")
    idle_days = pd.to_numeric(table["idle_days"], errors="coerce")
    maximum_age = max(float(age_days.max()), old_days)
    maximum_idle = max(float(idle_days.max()), stale_days)
    x_tickvals, x_ticktext = _sqrt_axis_ticks(maximum_age, backlog_days, old_days)
    y_tickvals, y_ticktext = _sqrt_axis_ticks(maximum_idle, stale_days)
    x_max = max(x_tickvals) * 1.02
    y_max = max(y_tickvals) * 1.02
    backlog_x = math.sqrt(backlog_days)
    old_x = math.sqrt(old_days)
    stale_y = math.sqrt(stale_days)

    fig = go.Figure()
    for trace_index, step_name in enumerate(
        table["step_name"].drop_duplicates().tolist()
    ):
        step_rows = table.loc[table["step_name"].eq(step_name)].copy()
        last_activity_labels = (
            dashboard_time_series(step_rows["last_activity_at"])
            .dt.strftime("%Y-%m-%d %I:%M %p %Z")
            .fillna("")
            .tolist()
        )
        customdata = [
            [
                str(row["record_id"]),
                str(row["step_name"]),
                format_one_decimal(row["age_days"]),
                format_one_decimal(row["idle_days"]),
                last_activity_label,
                str(row["action_bucket"]),
                bucket_labels[str(row["action_bucket"])],
            ]
            for (_, row), last_activity_label in zip(
                step_rows.iterrows(), last_activity_labels
            )
        ]
        fig.add_trace(
            go.Scatter(
                x=[math.sqrt(float(value)) for value in step_rows["age_days"]],
                y=[math.sqrt(float(value)) for value in step_rows["idle_days"]],
                mode="markers",
                name=str(step_name),
                legendgroup=str(step_name),
                marker=dict(
                    color=COLORWAY[trace_index % len(COLORWAY)],
                    size=11,
                    opacity=0.82,
                    line=dict(color="#ffffff", width=1),
                ),
                customdata=customdata,
                hovertemplate=(
                    content.CHART_LABELS.workflow_step
                    + ": %{customdata[1]}<br>"
                    + content.CHART_LABELS.age_since_step_submission
                    + ": %{customdata[2]}<br>"
                    + content.CHART_LABELS.idle_time
                    + ": %{customdata[3]}<br>"
                    + content.CHART_LABELS.last_activity
                    + ": %{customdata[4]}<br>"
                    + content.CHART_LABELS.action_group
                    + ": %{customdata[6]}<extra></extra>"
                ),
            )
        )

    quadrant_shapes = (
        ("young_active", 0, backlog_x, 0, stale_y),
        ("young_stale", 0, backlog_x, stale_y, y_max),
        ("backlog_active", backlog_x, x_max, 0, stale_y),
        ("backlog_stale", backlog_x, x_max, stale_y, y_max),
    )
    for bucket, x0, x1, y0, y1 in quadrant_shapes:
        fig.add_shape(
            type="rect",
            x0=x0,
            x1=x1,
            y0=y0,
            y1=y1,
            fillcolor=ACTION_BUCKET_COLORS[bucket],
            line=dict(width=0),
            layer="below",
        )

    threshold_lines = (
        dict(type="line", x0=backlog_x, x1=backlog_x, y0=0, y1=y_max),
        dict(type="line", x0=old_x, x1=old_x, y0=0, y1=y_max),
        dict(type="line", x0=0, x1=x_max, y0=stale_y, y1=stale_y),
    )
    for index, line in enumerate(threshold_lines):
        fig.add_shape(
            **line,
            line=dict(
                color=PRIMARY_DARK if index != 1 else "#a95516",
                width=2 if index != 1 else 1.5,
                dash="solid" if index != 1 else "dash",
            ),
            layer="above",
        )

    counts = table["action_bucket"].value_counts().to_dict()
    annotation_positions = {
        "young_active": (backlog_x / 2, stale_y / 2),
        "young_stale": (backlog_x / 2, stale_y + (y_max - stale_y) / 2),
        "backlog_active": (backlog_x + (x_max - backlog_x) / 2, stale_y / 2),
        "backlog_stale": (
            backlog_x + (x_max - backlog_x) / 2,
            stale_y + (y_max - stale_y) / 2,
        ),
    }
    for bucket in bucket_labels:
        x_position, y_position = annotation_positions[bucket]
        fig.add_annotation(
            x=x_position,
            y=y_position,
            text=f"<b>{bucket_labels[bucket]}</b><br>{int(counts.get(bucket, 0)):,}",
            showarrow=False,
            font=dict(color=MUTED, size=12),
            opacity=0.9,
        )
    fig.add_annotation(
        x=backlog_x,
        y=1.07,
        xref="x",
        yref="paper",
        text=f"<b>{backlog_days:g}d backlog</b>",
        showarrow=False,
        xanchor="right",
        font=dict(color=PRIMARY_DARK, size=11),
    )
    fig.add_annotation(
        x=old_x,
        y=1.07,
        xref="x",
        yref="paper",
        text=f"<b>{old_days:g}d aged</b>",
        showarrow=False,
        xanchor="left",
        font=dict(color="#a95516", size=11),
    )
    fig.add_annotation(
        x=0.985,
        y=stale_y,
        xref="paper",
        yref="y",
        text=f"<b>{stale_days:g} days without activity</b>",
        showarrow=False,
        xanchor="right",
        yanchor="bottom",
        font=dict(color=PRIMARY_DARK, size=11),
    )

    _base_layout(fig, title, height=620)
    fig.update_layout(
        margin=dict(l=82, r=36, t=72, b=128),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.2,
            xanchor="left",
            x=0,
            font=dict(size=12, color=MUTED),
        ),
        hovermode="closest",
        meta={
            "valid_count": valid_count,
            "total_open_count": total_open,
            "backlog_age_days": backlog_days,
            "old_age_days": old_days,
            "stale_idle_days": stale_days,
            "axis_transform": "square_root",
        },
    )
    fig.update_xaxes(
        title=f"{content.CHART_LABELS.age_since_step_submission}",
        tickmode="array",
        tickvals=x_tickvals,
        ticktext=x_ticktext,
        range=[0, x_max],
        fixedrange=False,
        automargin=True,
    )
    fig.update_yaxes(
        title=f"{content.CHART_LABELS.idle_time}",
        tickmode="array",
        tickvals=y_tickvals,
        ticktext=y_ticktext,
        range=[0, y_max],
        fixedrange=False,
        automargin=True,
    )
    return fig


def _plot_divs(
    analytics: AnalyticsBundle,
    history: pd.DataFrame,
) -> dict[str, str]:
    chart_content = {
        key: value.formatted(analytics.presentation)
        for key, value in content.CHART_CONTENT.items()
    }
    figures = {
        "in_the_works_by_step": _donut_chart(
            analytics.chart_tables["in_the_works_by_step"],
            "step_name",
            "count",
            chart_content["in_the_works_by_step"].title,
            color_dimension="workflow_step",
        ),
        "status_mix": _bar_chart(
            analytics.chart_tables["status_mix"],
            "status",
            "count",
            chart_content["status_mix"].title,
            content.CHART_LABELS.records,
            dynamic_height=True,
            color_dimension="status",
            largest_first=True,
        ),
        "aging_by_step": _aging_by_step_chart(
            analytics.chart_tables["aging_by_step"],
            overall_age_days=analytics.snapshot_metrics["median_age_days"],
        ),
        "workflow_aging_matrix": _workflow_aging_matrix_chart(
            analytics.chart_tables["workflow_aging_matrix"]
        ),
        "age_idle_action_matrix": _age_idle_action_matrix_chart(
            analytics.chart_tables["age_idle_action_matrix"]
        ),
        "owner_workload": _donut_chart(
            analytics.chart_tables["owner_workload"],
            "owner",
            "count",
            chart_content["owner_workload"].title,
            value_label=content.CHART_LABELS.open_cases,
            color_dimension="staff",
            category_order=analytics.team_members,
        ),
        "submitted_by_workload": _bar_chart(
            analytics.chart_tables["submitted_by_workload"],
            "owner",
            "count",
            chart_content["submitted_by_workload"].title,
            content.CHART_LABELS.records,
            color_dimension="staff",
            category_order=analytics.team_members,
        ),
        "submitted_by_date_activity": _submitted_by_date_heatmap(
            analytics.chart_tables["submitted_by_date_activity"]
        ),
        "backlog_trend": _line_chart(
            history,
            "backlog_count",
            chart_content["backlog_trend"].title,
            content.CHART_LABELS.backlog,
        ),
        "daily_closures": _daily_closures_chart(
            analytics.chart_tables["daily_closures"]
        ),
        "closed_by_month": _closed_by_month_trend(
            analytics.chart_tables["closed_by_month"]
        ),
        "age_trend": _line_chart(
            history,
            "median_age_days",
            chart_content["age_trend"].title,
            content.CHART_LABELS.age_since_step_submission,
            one_decimal=True,
            coverage_columns=("age_valid_count", "age_total_count"),
        ),
        "recent_closures": _recent_closures_chart(
            analytics.chart_tables["daily_closures"],
            analytics.generated_at,
        ),
    }
    divs: dict[str, str] = {}
    include_plotlyjs: bool | str = True
    for key, fig in figures.items():
        divs[key] = to_html(
            fig,
            include_plotlyjs=include_plotlyjs,
            full_html=False,
            div_id=f"plot-{key.replace('_', '-')}",
            post_script=(
                "document.getElementById('{plot_id}').dataset.pdfReady = 'true';"
                "document.dispatchEvent(new Event('dashboard-chart-ready'));"
            ),
            config={
                "responsive": True,
                "displaylogo": False,
                "displayModeBar": "hover",
                "modeBarButtonsToRemove": ["lasso2d", "select2d"],
            },
        )
        include_plotlyjs = False
    return divs


def _help_control(label: str, help_text: str, *, help_id: str) -> str:
    about_label = content.COMMON.about_label_template.format(label=label)
    return f"""
      <span class="help-control">
        <button type="button" class="info-button" aria-label="{html.escape(about_label)}" aria-describedby="{html.escape(help_id)}">i</button>
        <span class="info-tooltip" id="{html.escape(help_id)}" role="tooltip">{html.escape(help_text)}</span>
      </span>
    """


def _kpi_html(analytics: AnalyticsBundle) -> str:
    cards = []
    for index, kpi in enumerate(analytics.kpis, start=1):
        view_list = ""
        if kpi.key == "notable_observations":
            view_list = (
                '<a class="kpi-link" href="#problem-rows-table">'
                f"{html.escape(content.COMMON.view_list)}</a>"
            )
        warning_caption = (
            f'<span class="kpi-warning">{html.escape(kpi.warning_caption)}</span>'
            if kpi.warning_caption
            else ""
        )
        cards.append(f"""
        <div class="kpi">
          <div class="kpi-heading">
            <span class="kpi-label">{html.escape(kpi.label)}</span>
            {_help_control(kpi.label, kpi.help_text, help_id=f"kpi-help-{index}")}
          </div>
          <strong>{html.escape(kpi.value)}</strong>
          {warning_caption}
          {view_list}
        </div>
        """)
    return "\n".join(cards)


def _process_guide_html() -> str:
    legend = content.WORKFLOW_LEGEND
    items = "\n".join(f"""
        <div class="legend-item">
          <span class="legend-number">{index}.</span>
          <div>
            <h3>{html.escape(item.title)}</h3>
            <p>{html.escape(item.description)}</p>
          </div>
        </div>
        """ for index, item in enumerate(legend.items, start=1))
    return f"""
    <section class="dashboard-section workflow-legend" aria-labelledby="workflow-legend-title">
      <div class="legend-card">
        <span class="eyebrow">{html.escape(legend.eyebrow)}</span>
        <h2 class="section-title" id="workflow-legend-title">{html.escape(legend.title)}</h2>
        <p class="section-copy">{html.escape(legend.description)}</p>
        <div class="legend-grid">{items}</div>
      </div>
    </section>
    """


def _chart_card(
    div: str,
    chart_key: content.ChartKey,
    *,
    help_id: str,
    extra_class: str = "",
    context: content.PresentationContext = content.PresentationContext(),
) -> str:
    chart_copy = content.CHART_CONTENT[chart_key].formatted(context)
    note = ""
    if chart_key in {"closed_by_month", "daily_closures", "recent_closures"}:
        note = (
            '<p class="section-copy completion-date-note">'
            f"{html.escape(content.COMPLETION_DATE_NOTE)}</p>"
        )
    classes = "chart-container"
    if extra_class:
        classes = f"{classes} {extra_class}"
    return f"""
      <div class="{classes}" role="region" aria-label="{html.escape(chart_copy.title)}">
        <div class="card-heading">
          <h2>{html.escape(chart_copy.title)}</h2>
          {_help_control(chart_copy.title, chart_copy.help_text, help_id=help_id)}
        </div>
        {note}
        {div}
      </div>
    """


def _json_for_script(value: object) -> str:
    """Serialize JSON without allowing source values to close a script tag."""

    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def _age_idle_action_matrix_card(
    div: str,
    table: pd.DataFrame,
) -> str:
    """Render action controls and an initially hidden ID-only drilldown."""

    chart_copy = content.CHART_CONTENT["age_idle_action_matrix"].formatted(
        content.PresentationContext(
            backlog_age_days=float(table.attrs.get("backlog_age_days", 7)),
            old_age_days=float(table.attrs.get("old_age_days", 14)),
            stale_idle_days=float(table.attrs.get("stale_idle_days", 3)),
        )
    )
    total_open = int(table.attrs.get("total_open_count", len(table)))
    valid_count = int(len(table))
    excluded_count = max(0, total_open - valid_count)
    coverage = f"{valid_count:,}/{total_open:,} open cases shown" + (
        f" · {excluded_count:,} excluded for missing or invalid timing"
        if excluded_count
        else " · complete timing coverage"
    )
    counts = table["action_bucket"].value_counts().to_dict()
    bucket_labels = content.action_bucket_labels(float(table.attrs.get("backlog_age_days", 7)))
    buttons = []
    for bucket in bucket_labels:
        count = int(counts.get(bucket, 0))
        disabled = " disabled" if count == 0 else ""
        buttons.append(f"""
            <button type="button" class="action-group-button action-group-{html.escape(bucket)}"
                    data-action-bucket="{html.escape(bucket)}"
                    aria-controls="age-idle-action-drilldown"
                    aria-pressed="false"{disabled}>
              <span>{html.escape(bucket_labels[bucket])}</span>
              <strong>{count:,}</strong>
            </button>
            """)

    last_activity_labels = (
        dashboard_time_series(table["last_activity_at"])
        .dt.strftime("%Y-%m-%d %I:%M %p %Z")
        .fillna("")
        .tolist()
    )
    rows = [
        {
            "record_id": str(row["record_id"]),
            "step_name": str(row["step_name"]),
            "age_days": float(row["age_days"]),
            "idle_days": float(row["idle_days"]),
            "last_activity_at": last_activity_label,
            "action_bucket": str(row["action_bucket"]),
        }
        for (_, row), last_activity_label in zip(
            table.iterrows(), last_activity_labels
        )
    ]
    matrix_data = _json_for_script(rows)
    return f"""
      <div class="chart-container chart-container-wide action-matrix-card"
           role="region" aria-label="{html.escape(chart_copy.title)}">
        <div class="card-heading">
          <h2>{html.escape(chart_copy.title)}</h2>
          {_help_control(chart_copy.title, chart_copy.help_text, help_id="age-idle-action-matrix-help")}
        </div>
        <p class="action-matrix-coverage">{html.escape(coverage)}</p>
        <div class="action-matrix-controls" id="age-idle-action-controls"
             role="group" aria-label="Choose an action group to reveal cases by Package ID">
          {"".join(buttons)}
        </div>
        {div}
        <section class="action-matrix-drilldown" id="age-idle-action-drilldown"
                 aria-labelledby="age-idle-action-drilldown-title" hidden>
          <div class="action-drilldown-heading">
            <div>
              <h3 id="age-idle-action-drilldown-title">Selected Cases</h3>
              <p id="age-idle-action-drilldown-summary" aria-live="polite"></p>
            </div>
            <button type="button" class="action-drilldown-clear" id="age-idle-action-clear">
              Clear
            </button>
          </div>
          <div class="action-drilldown-scroll">
            <table class="data-table action-drilldown-table">
              <thead>
                <tr>
                  <th>{html.escape(content.CHART_LABELS.package_id)}</th>
                  <th>{html.escape(content.CHART_LABELS.workflow_step)}</th>
                  <th>{html.escape(content.CHART_LABELS.age_since_step_submission)}</th>
                  <th>{html.escape(content.CHART_LABELS.idle_time)}</th>
                  <th>{html.escape(content.CHART_LABELS.last_activity)}</th>
                </tr>
              </thead>
              <tbody id="age-idle-action-rows"></tbody>
            </table>
          </div>
        </section>
        <script type="application/json" id="age-idle-action-data">{matrix_data}</script>
        <script>
          (() => {{
            const source = document.getElementById("age-idle-action-data");
            const plot = document.getElementById("plot-age-idle-action-matrix");
            const controls = document.getElementById("age-idle-action-controls");
            const drilldown = document.getElementById("age-idle-action-drilldown");
            const title = document.getElementById("age-idle-action-drilldown-title");
            const summary = document.getElementById("age-idle-action-drilldown-summary");
            const body = document.getElementById("age-idle-action-rows");
            const clear = document.getElementById("age-idle-action-clear");
            const buttons = Array.from(
              document.querySelectorAll("[data-action-bucket]")
            );
            const labels = {_json_for_script(bucket_labels)};
            const rows = source ? JSON.parse(source.textContent) : [];
            const scrollBehavior = () =>
              window.matchMedia("(prefers-reduced-motion: reduce)").matches
                ? "auto"
                : "smooth";

            const scrollToElement = (element, afterScroll) => {{
              window.requestAnimationFrame(() => {{
                element.scrollIntoView({{
                  behavior: scrollBehavior(),
                  block: "start",
                }});
                if (afterScroll) afterScroll();
              }});
            }};

            const sortRows = (values) => values.slice().sort((left, right) =>
              right.idle_days - left.idle_days ||
              right.age_days - left.age_days ||
              left.record_id.localeCompare(right.record_id)
            );

            const appendCell = (row, value) => {{
              const cell = document.createElement("td");
              cell.textContent = value;
              row.appendChild(cell);
            }};

            const renderRows = (
              values,
              heading,
              activeBucket,
              scrollToDrilldown = false
            ) => {{
              const selected = sortRows(values);
              body.replaceChildren();
              selected.forEach((record) => {{
                const row = document.createElement("tr");
                appendCell(row, record.record_id);
                appendCell(row, record.step_name);
                appendCell(row, `${{record.age_days.toFixed(1)}} days`);
                appendCell(row, `${{record.idle_days.toFixed(1)}} days`);
                appendCell(row, record.last_activity_at);
                body.appendChild(row);
              }});
              buttons.forEach((button) => {{
                button.setAttribute(
                  "aria-pressed",
                  button.dataset.actionBucket === activeBucket ? "true" : "false"
                );
              }});
              title.textContent = heading;
              summary.textContent =
                `${{selected.length.toLocaleString()}} case${{selected.length === 1 ? "" : "s"}}`;
              drilldown.hidden = false;
              if (scrollToDrilldown) scrollToElement(drilldown);
            }};

            buttons.forEach((button) => {{
              button.addEventListener("click", () => {{
                const bucket = button.dataset.actionBucket;
                renderRows(
                  rows.filter((record) => record.action_bucket === bucket),
                  labels[bucket],
                  bucket,
                  true
                );
              }});
            }});

            if (plot && typeof plot.on === "function") {{
              plot.on("plotly_click", (event) => {{
                const point = event.points && event.points[0];
                const packageId = point && point.customdata && point.customdata[0];
                if (!packageId) return;
                const selected = rows.find(
                  (record) => record.record_id === String(packageId)
                );
                if (selected) {{
                  renderRows([selected], "Selected Case", selected.action_bucket);
                }}
              }});
            }}

            clear.addEventListener("click", () => {{
              const activeButton =
                buttons.find(
                  (button) => button.getAttribute("aria-pressed") === "true"
                ) || buttons.find((button) => !button.disabled);
              drilldown.hidden = true;
              body.replaceChildren();
              buttons.forEach((button) => button.setAttribute("aria-pressed", "false"));
              scrollToElement(controls, () => {{
                if (activeButton) activeButton.focus({{ preventScroll: true }});
              }});
            }});
          }})();
        </script>
      </div>
    """


def _evaluation_type_summary_html(summary: pd.DataFrame) -> str:
    table_copy = content.EVALUATION_TYPE_TABLE
    required_columns = {
        "evaluation_type",
        "total_count",
        "in_progress_count",
        "completed_count",
        "completion_rate",
        "backlog_count",
        "open_age_valid_count",
        "median_open_age_days",
        "completion_valid_count",
        "median_completion_days",
    }
    if summary.empty or not required_columns.issubset(summary.columns):
        return (
            '<div class="empty-table">'
            f"{html.escape(table_copy.empty_message)}</div>"
        )

    display_columns = [
        "evaluation_type",
        "total_count",
        "in_progress_count",
        "completed_count",
        "completion_rate",
        "backlog_summary",
        "median_open_age_summary",
        "median_completion_summary",
    ]
    headers = "".join(
        (
            '<th scope="col">'
            f"{html.escape(table_copy.header_labels[column])}</th>"
        )
        for column in display_columns
    )
    rows: list[str] = []
    for _, row in summary.iterrows():
        total_count = int(row["total_count"])
        in_progress_count = int(row["in_progress_count"])
        completed_count = int(row["completed_count"])
        backlog_count = int(row["backlog_count"])
        completion_rate = format_one_decimal(
            float(row["completion_rate"]) * 100
            if pd.notna(row["completion_rate"])
            else None,
            suffix="%",
            missing="—",
        )
        median_open_age = format_one_decimal(
            row["median_open_age_days"],
            suffix="d",
            missing="—",
        )
        median_completion = format_one_decimal(
            row["median_completion_days"],
            suffix="d",
            missing="—",
        )
        cells = [
            (
                '<th scope="row" class="evaluation-type-name">'
                f"{html.escape(str(row['evaluation_type']))}</th>"
            ),
            f'<td class="numeric-cell">{total_count:,}</td>',
            f'<td class="numeric-cell">{in_progress_count:,}</td>',
            f'<td class="numeric-cell">{completed_count:,}</td>',
            f'<td class="numeric-cell">{completion_rate}</td>',
            f'<td class="numeric-cell">{backlog_count:,}</td>',
            (
                '<td class="metric-cell">'
                f"<strong>{median_open_age}</strong></td>"
            ),
            (
                '<td class="metric-cell">'
                f"<strong>{median_completion}</strong></td>"
            ),
        ]
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return (
        '<table class="data-table evaluation-type-table">'
        f"<thead><tr>{headers}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _table_html(exceptions: pd.DataFrame) -> str:
    columns = [
        "exception_reasons",
        "record_id",
        "item_label",
        "step_name",
        "status",
        "owner",
        "age_days",
        "idle_days",
        "submitted_at",
        "last_activity_at",
    ]
    if exceptions.empty:
        return (
            '<div class="empty-table">'
            f"{html.escape(content.OBSERVATION_TABLE.empty_message)}</div>"
        )
    table = exceptions[
        [column for column in columns if column in exceptions.columns]
    ].copy()
    if "age_days" in table.columns:
        table["_age_sort"] = pd.to_numeric(table["age_days"], errors="coerce")
        table = (
            table.sort_values(
                "_age_sort",
                ascending=False,
                na_position="last",
                kind="stable",
            )
            .drop(columns="_age_sort")
        )
    for date_col in ("submitted_at", "last_activity_at"):
        if date_col in table.columns:
            table[date_col] = (
                dashboard_time_series(table[date_col])
                .dt.strftime("%Y-%m-%d %I:%M %p %Z")
                .fillna("")
            )
    for duration_col in ("age_days", "idle_days"):
        if duration_col in table.columns:
            table[duration_col] = table[duration_col].map(
                lambda value: format_one_decimal(value, missing="")
            )
    headers = "".join(
        f"<th>{html.escape(content.OBSERVATION_TABLE.header_labels.get(column, column.replace('_', ' ').title()))}</th>"
        for column in table.columns
    )
    rows = []
    for _, row in table.head(100).iterrows():
        cells = "".join(
            f"<td>{html.escape('' if pd.isna(value) else str(value))}</td>"
            for value in row
        )
        rows.append(f"<tr>{cells}</tr>")
    return f'<table class="data-table"><thead><tr>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def render_dashboard(
    *,
    df: pd.DataFrame,
    analytics: AnalyticsBundle,
    history: pd.DataFrame,
    owner_history: pd.DataFrame,
    output_path: Path,
) -> Path:
    """Render a standalone offline HTML dashboard."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    generated = _format_generated_at(analytics.generated_at)
    divs = _plot_divs(analytics, history)
    shown_exceptions = min(len(analytics.exceptions), 100)
    page_copy = content.PAGE
    sections = content.SECTION_CONTENT
    evaluation_table_copy = content.EVALUATION_TYPE_TABLE
    observation_copy = content.OBSERVATION_TABLE
    intro_html = "\n".join(
        f"      <p>{html.escape(paragraph)}</p>"
        for paragraph in page_copy.intro_paragraphs
    )
    table_summary = observation_copy.summary_template.format(
        shown=shown_exceptions,
        total=len(analytics.exceptions),
    )
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(analytics.dashboard_title)}</title>
  <style>
    :root {{
      --background: {BG};
      --surface: #ffffff;
      --surface-muted: {SURFACE_MUTED};
      --border: {BORDER};
      --border-strong: #cbd6e2;
      --text: {TEXT};
      --muted: {MUTED};
      --primary: {PRIMARY};
      --primary-dark: {PRIMARY_DARK};
      --primary-soft: #e8f0ff;
      --shadow: 0 10px 28px rgba(34, 49, 73, 0.07);
    }}
    *, *::before, *::after {{ box-sizing: border-box; }}
    html {{
      background: var(--background);
      scroll-behavior: smooth;
    }}
    body {{
      background: var(--background);
      color: var(--text);
      font-family: Segoe UI, Inter, system-ui, -apple-system, sans-serif;
      letter-spacing: 0;
      line-height: 1.5;
      margin: 0;
      min-width: 0;
      overflow-x: hidden;
    }}
    .dashboard-shell {{
      margin: 0 auto;
      max-width: 1680px;
      padding: 28px 32px 48px;
      width: 100%;
    }}
    .dashboard-header {{
      background: linear-gradient(135deg, #ffffff 0%, #f7faff 100%);
      border: 1px solid var(--border);
      border-radius: 12px;
      box-shadow: var(--shadow);
      padding: 24px 28px;
    }}
    .header-top {{
      align-items: center;
      display: flex;
      flex-wrap: wrap;
      gap: 8px 20px;
      justify-content: space-between;
    }}
    .header-utility-row {{
      align-items: center;
      border-top: 1px solid var(--border);
      display: flex;
      flex-wrap: wrap;
      gap: 12px 20px;
      justify-content: space-between;
      margin-top: 18px;
      padding-top: 12px;
    }}
    .dashboard-header h1 {{ margin-top: 10px; }}
    .header-top .eyebrow {{ margin-bottom: 0; }}
    .dashboard-header .generated-at {{
      font-size: 13px;
      line-height: 1.4;
      margin: 0;
    }}
    .dashboard-header .authorship-credit {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      margin: 0;
    }}
    .authorship-credit strong {{
      color: inherit;
      font-weight: 600;
    }}
    .eyebrow {{
      color: var(--primary-dark);
      display: block;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0;
      margin-bottom: 4px;
      text-transform: uppercase;
    }}
    h1 {{
      color: var(--text);
      font-size: clamp(28px, 3vw, 38px);
      letter-spacing: 0;
      line-height: 1.16;
      margin: 0;
    }}
    h2 {{ margin: 0; }}
    .prototype-label {{
      color: var(--muted);
      font-size: 0.58em;
      font-weight: 700;
      white-space: nowrap;
    }}
    .dashboard-header p {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.7;
      margin: 18px 0 0;
      max-width: 980px;
    }}
    .dashboard-section {{ margin-top: 30px; }}
    .section-heading {{ margin-bottom: 14px; }}
    .section-title {{
      color: var(--text);
      font-size: 23px;
      letter-spacing: 0;
      line-height: 1.25;
    }}
    .section-copy {{
      color: var(--muted);
      font-size: 14px;
      margin: 5px 0 0;
    }}
    .kpi-grid {{
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(7, minmax(0, 1fr));
    }}
    .kpi {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: 0 4px 14px rgba(34, 49, 73, 0.05);
      min-height: 122px;
      padding: 17px 18px;
      position: relative;
    }}
    .kpi:hover,
    .kpi:focus-within {{ z-index: 10; }}
    .kpi-heading {{
      align-items: flex-start;
      display: flex;
      gap: 6px;
      justify-content: space-between;
    }}
    .kpi-label {{
      color: var(--muted);
      font-size: 13px;
      font-weight: 600;
      line-height: 1.25;
    }}
    .kpi strong {{
      color: var(--text);
      display: block;
      font-size: clamp(22px, 1.8vw, 28px);
      letter-spacing: 0;
      line-height: 1.15;
      margin-top: 10px;
      overflow-wrap: anywhere;
    }}
    .kpi-warning {{
      color: #a33a16;
      display: block;
      font-size: 12px;
      font-weight: 700;
      line-height: 1.3;
      margin-top: 7px;
    }}
    .kpi-link {{
      color: var(--primary-dark);
      display: inline-block;
      font-size: 13px;
      font-weight: 700;
      margin-top: 10px;
      text-decoration: none;
    }}
    .kpi-link:hover {{ text-decoration: underline; }}
    .legend-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      box-shadow: var(--shadow);
      padding: 24px 28px 22px;
    }}
    .legend-grid {{
      display: grid;
      gap: 18px 56px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin-top: 20px;
    }}
    .legend-item {{
      display: grid;
      gap: 12px;
      grid-template-columns: 24px minmax(0, 1fr);
    }}
    .legend-number {{
      color: var(--text);
      font-size: 15px;
      font-weight: 700;
      line-height: 1.35;
    }}
    .legend-item h3 {{
      color: var(--text);
      font-size: 15px;
      line-height: 1.35;
      margin: 0;
    }}
    .legend-item p {{
      color: var(--muted);
      font-size: 14px;
      margin: 4px 0 0;
    }}
    .chart-container,
    .table-container {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: var(--shadow);
      min-width: 0;
      position: relative;
    }}
    .chart-container {{
      margin-bottom: 20px;
      overflow: hidden;
      padding: 20px 22px 14px;
    }}
    .chart-stack .chart-container:last-child {{ margin-bottom: 0; }}
    .table-container {{
      overflow: hidden;
      padding: 20px 22px 22px;
      scroll-margin-top: 20px;
    }}
    .card-heading {{
      align-items: center;
      display: flex;
      gap: 8px;
      justify-content: flex-start;
      min-height: 28px;
      position: relative;
      z-index: 2;
    }}
    .card-heading h2 {{
      color: var(--text);
      font-size: 18px;
      letter-spacing: 0;
      line-height: 1.3;
    }}
    .chart-container .js-plotly-plot,
    .chart-container .plot-container,
    .chart-container .svg-container {{
      max-width: 100%;
    }}
    .help-control {{
      display: inline-flex;
      flex: 0 0 auto;
      position: relative;
    }}
    .info-button {{
      align-items: center;
      background: var(--primary-soft);
      border: 1px solid #b9cdf7;
      border-radius: 50%;
      color: var(--primary-dark);
      cursor: help;
      display: inline-flex;
      font-family: Georgia, serif;
      font-size: 12px;
      font-style: italic;
      font-weight: bold;
      height: 18px;
      justify-content: center;
      line-height: 1;
      padding: 0;
      width: 18px;
    }}
    .info-button:hover {{ background: #dce8ff; }}
    .info-button:focus-visible,
    .kpi-link:focus-visible,
    .action-group-button:focus-visible,
    .action-drilldown-clear:focus-visible,
    .jump-to-top:focus-visible {{
      outline: 3px solid rgba(37, 99, 235, 0.28);
      outline-offset: 2px;
    }}
    .info-tooltip {{
      background: var(--text);
      border-radius: 8px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.22);
      color: #ffffff;
      font-size: 13px;
      font-weight: normal;
      left: 0;
      line-height: 1.4;
      max-width: 360px;
      min-width: 240px;
      opacity: 0;
      padding: 10px 12px;
      pointer-events: none;
      position: absolute;
      text-align: left;
      top: 26px;
      transform: translateY(-4px);
      transition: opacity 120ms ease, transform 120ms ease, visibility 120ms ease;
      visibility: hidden;
      white-space: normal;
      z-index: 20;
    }}
    .kpi .info-tooltip {{
      left: auto;
      right: 0;
    }}
    .card-heading .help-control {{ position: static; }}
    .card-heading .info-tooltip {{
      max-width: 100%;
      min-width: 0;
      top: 100%;
      width: 360px;
    }}
    .help-control:hover .info-tooltip,
    .help-control:focus-within .info-tooltip {{
      opacity: 1;
      transform: translateY(0);
      visibility: visible;
    }}
    .current-open-grid,
    .trend-grid {{
      display: grid;
      gap: 22px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .current-open-grid .chart-container,
    .trend-grid .chart-container {{ margin-bottom: 0; }}
    .current-open-grid .chart-container-wide {{
      grid-column: 1 / -1;
      overflow-x: auto;
    }}
    .chart-container-wide .js-plotly-plot {{
      max-width: none;
      min-width: 720px;
    }}
    .chart-container-wide .card-heading {{
      background: var(--surface);
      left: 0;
      position: sticky;
      z-index: 3;
    }}
    .action-matrix-coverage {{
      color: var(--muted);
      font-size: 13px;
      margin: 7px 0 12px;
    }}
    .action-matrix-controls {{
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      margin-bottom: 4px;
      scroll-margin-top: 24px;
    }}
    .action-group-button {{
      align-items: center;
      background: var(--surface-muted);
      border: 1px solid var(--border);
      border-radius: 8px;
      color: var(--text);
      cursor: pointer;
      display: flex;
      font: inherit;
      gap: 10px;
      justify-content: space-between;
      min-height: 54px;
      padding: 9px 12px;
      text-align: left;
    }}
    .action-group-button span {{
      font-size: 12px;
      font-weight: 700;
      line-height: 1.25;
    }}
    .action-group-button strong {{
      font-size: 20px;
      line-height: 1;
    }}
    .action-group-young_active {{ border-top: 3px solid #2f855a; }}
    .action-group-young_stale {{ border-top: 3px solid #c89b19; }}
    .action-group-backlog_active {{ border-top: 3px solid #e8792e; }}
    .action-group-backlog_stale {{ border-top: 3px solid #b4233c; }}
    .action-group-button:hover:not(:disabled),
    .action-group-button[aria-pressed="true"] {{
      background: var(--primary-soft);
      border-color: #9cb9f2;
    }}
    .action-group-button:disabled {{
      cursor: default;
      opacity: 0.55;
    }}
    .action-matrix-drilldown {{
      border-top: 1px solid var(--border);
      margin-top: 10px;
      padding-top: 16px;
      scroll-margin-top: 24px;
    }}
    .action-matrix-drilldown[hidden] {{ display: none; }}
    .action-drilldown-heading {{
      align-items: center;
      display: flex;
      gap: 16px;
      justify-content: space-between;
      margin-bottom: 10px;
    }}
    .action-drilldown-heading h3 {{
      font-size: 16px;
      margin: 0;
    }}
    .action-drilldown-heading p {{
      color: var(--muted);
      font-size: 13px;
      margin: 2px 0 0;
    }}
    .action-drilldown-clear {{
      background: var(--surface);
      border: 1px solid var(--border-strong);
      border-radius: 7px;
      color: var(--primary-dark);
      cursor: pointer;
      font: inherit;
      font-size: 13px;
      font-weight: 700;
      padding: 7px 11px;
    }}
    .action-drilldown-scroll {{
      max-height: 360px;
      overflow: auto;
    }}
    .action-drilldown-table {{
      min-width: 680px;
    }}
    .action-drilldown-table th:nth-child(3),
    .action-drilldown-table th:nth-child(4),
    .action-drilldown-table td:nth-child(3),
    .action-drilldown-table td:nth-child(4) {{
      text-align: right;
    }}
    .trend-grid .chart-container:last-child:nth-child(odd) {{ grid-column: 1 / -1; }}
    .table-card-header,
    .table-card-footer {{
      align-items: center;
      display: flex;
      gap: 16px;
      justify-content: space-between;
    }}
    .table-card-header {{ margin-bottom: 14px; }}
    .table-card-header .card-heading {{ flex: 1; min-width: 0; }}
    .table-card-footer {{
      border-top: 1px solid var(--border);
      margin-top: 14px;
      padding-top: 14px;
    }}
    .table-summary {{
      color: var(--muted);
      font-size: 13px;
    }}
    .table-scroll {{
      max-height: 560px;
      overflow-x: auto;
    }}
    .data-table {{
      border-collapse: separate;
      border-spacing: 0;
      font-size: 13px;
      min-width: 980px;
      width: 100%;
    }}
    .data-table th,
    .data-table td {{
      border-bottom: 1px solid var(--border);
      overflow-wrap: anywhere;
      padding: 10px 11px;
      text-align: left;
      vertical-align: top;
    }}
    .data-table th {{
      background: var(--surface-muted);
      color: #34435a;
      font-size: 12px;
      letter-spacing: 0;
      position: sticky;
      text-transform: uppercase;
      top: 0;
      z-index: 1;
    }}
    .data-table tbody tr:hover {{ background: #f7faff; }}
    .evaluation-type-table-container .table-scroll {{
      max-height: none;
    }}
    .evaluation-type-table-container .empty-table {{
      text-align: center;
    }}
    .evaluation-type-table {{
      min-width: 1080px;
    }}
    .evaluation-type-table th,
    .evaluation-type-table td {{
      text-align: center;
      white-space: nowrap;
    }}
    .evaluation-type-name {{
      color: var(--text);
      font-size: 14px;
      min-width: 150px;
    }}
    .metric-cell {{
      min-width: 145px;
      white-space: nowrap;
    }}
    .metric-cell strong {{
      display: block;
      font-size: 14px;
    }}
    .empty-table {{
      border: 1px dashed var(--border);
      border-radius: 8px;
      color: var(--muted);
      padding: 22px;
    }}
    .page-footer {{
      display: flex;
      justify-content: flex-end;
      margin-top: 24px;
    }}
    .jump-to-top {{
      color: var(--primary-dark);
      font-size: 14px;
      font-weight: 700;
      text-decoration: none;
    }}
    .jump-to-top:hover {{ text-decoration: underline; }}
    @media (max-width: 1400px) {{
      .kpi-grid {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
    }}
    @media (max-width: 1050px) {{
      .dashboard-shell {{ padding: 24px 22px 40px; }}
      .kpi-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
      .current-open-grid,
      .trend-grid {{ grid-template-columns: 1fr; }}
      .trend-grid .chart-container:last-child:nth-child(odd) {{ grid-column: auto; }}
    }}
    @media (max-width: 720px) {{
      .header-top {{ align-items: flex-start; flex-direction: column; }}
      .header-utility-row {{ align-items: flex-start; }}
      .dashboard-header {{ padding: 21px 22px; }}
      .kpi-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .legend-grid {{ grid-template-columns: 1fr; }}
      .action-matrix-controls {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .chart-container {{ padding: 18px 16px 12px; }}
      .table-container {{ padding: 18px 16px; }}
      .table-card-header,
      .table-card-footer {{
        align-items: stretch;
        flex-direction: column;
      }}
    }}
    @media (max-width: 520px) {{
      .dashboard-shell {{ padding: 14px 12px 30px; }}
      .kpi-grid {{ grid-template-columns: 1fr; }}
      .kpi {{ min-height: 106px; }}
      .card-heading h2 {{ font-size: 16px; }}
      .section-title {{ font-size: 21px; }}
      .chart-container {{
        border-radius: 8px;
        padding: 16px 10px 10px;
      }}
      .table-container {{ border-radius: 8px; }}
      .action-matrix-controls {{ grid-template-columns: 1fr; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      html {{ scroll-behavior: auto; }}
    }}
{PRINT_STYLES}
  </style>
</head>
<body>
  <main class="dashboard-shell" id="dashboard-top">
    <header class="dashboard-header">
      <div class="header-top">
        <span class="eyebrow">{html.escape(page_copy.team_eyebrow)}</span>
        <p class="authorship-credit"><span>{html.escape(page_copy.authorship_prefix)} </span><strong>{html.escape(page_copy.author_name)}</strong></p>
      </div>
      <h1>{html.escape(analytics.dashboard_title)} <span class="prototype-label">{html.escape(page_copy.prototype_label)}</span></h1>
      <div class="header-utility-row">
        <p class="generated-at">{html.escape(page_copy.generated_prefix)} {html.escape(generated)}</p>
        <div class="pdf-export">
          <p class="pdf-export-status" id="pdf-export-status" role="status" aria-live="polite"></p>
          <div class="pdf-export-control">
            <button type="button" id="save-pdf" aria-describedby="pdf-export-hint">
              <svg class="pdf-printer-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                <path d="M6 9V3h12v6M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>
                <rect x="6" y="14" width="12" height="7" rx="1"/><path d="M18 12h.01"/>
              </svg>
              <span class="pdf-spinner" aria-hidden="true"></span>
              <span class="pdf-button-label">{html.escape(page_copy.save_pdf)}</span>
            </button>
            <span id="pdf-export-hint" class="pdf-export-hint" role="tooltip">{html.escape(page_copy.save_pdf_hint)}</span>
          </div>
        </div>
      </div>
{intro_html}
    </header>

    {_process_guide_html()}

    <section class="dashboard-section" aria-labelledby="overview-title">
      <div class="section-heading">
        <span class="eyebrow">{html.escape(sections["overview"].eyebrow)}</span>
        <h2 class="section-title" id="overview-title">{html.escape(sections["overview"].title)}</h2>
      </div>
      <div class="kpi-grid">{_kpi_html(analytics)}</div>
    </section>

    <section class="dashboard-section" aria-labelledby="operations-title">
      <div class="section-heading">
        <span class="eyebrow">{html.escape(sections["operations"].eyebrow)}</span>
        <h2 class="section-title" id="operations-title">{html.escape(sections["operations"].title)}</h2>
        <p class="section-copy">{html.escape(sections["operations"].description or "")}</p>
      </div>
      <div class="current-open-grid">
        {_chart_card(divs["in_the_works_by_step"], "in_the_works_by_step", help_id="in-the-works-by-step-help", context=analytics.presentation)}
        {_chart_card(divs["status_mix"], "status_mix", help_id="status-mix-help", context=analytics.presentation)}
        {_chart_card(divs["owner_workload"], "owner_workload", help_id="owner-workload-help", context=analytics.presentation)}
        {_chart_card(divs["aging_by_step"], "aging_by_step", help_id="aging-by-step-help", context=analytics.presentation)}
        {_chart_card(divs["workflow_aging_matrix"], "workflow_aging_matrix", help_id="workflow-aging-matrix-help", extra_class="chart-container-wide", context=analytics.presentation)}
        {_age_idle_action_matrix_card(divs["age_idle_action_matrix"], analytics.chart_tables["age_idle_action_matrix"])}
      </div>
    </section>

    <section class="dashboard-section" aria-labelledby="evaluation-types-title">
      <div class="section-heading">
        <span class="eyebrow">{html.escape(sections["evaluation_types"].eyebrow)}</span>
        <h2 class="section-title" id="evaluation-types-title">{html.escape(sections["evaluation_types"].title)}</h2>
        <p class="section-copy">{html.escape(sections["evaluation_types"].description or "")}</p>
      </div>
      <div class="table-container evaluation-type-table-container" id="evaluation-type-summary-table" role="region" aria-label="{html.escape(evaluation_table_copy.title)}">
        <div class="table-card-header">
          <div class="card-heading">
            <h2>{html.escape(evaluation_table_copy.title)}</h2>
            {_help_control(evaluation_table_copy.title, analytics.presentation.format(evaluation_table_copy.help_text), help_id="evaluation-type-summary-table-help")}
          </div>
        </div>
        <div class="table-scroll">
          {_evaluation_type_summary_html(analytics.chart_tables["evaluation_type_summary"])}
        </div>
      </div>
    </section>

    <section class="dashboard-section" aria-labelledby="trends-title">
      <div class="section-heading">
        <span class="eyebrow">{html.escape(sections["trends"].eyebrow)}</span>
        <h2 class="section-title" id="trends-title">{html.escape(sections["trends"].title)}</h2>
        <p class="section-copy">{html.escape(sections["trends"].description or "")}</p>
      </div>
      <div class="trend-grid">
        {_chart_card(divs["closed_by_month"], "closed_by_month", help_id="closed-by-month-help", context=analytics.presentation)}
        {_chart_card(divs["daily_closures"], "daily_closures", help_id="daily-closures-help", context=analytics.presentation)}
        {_chart_card(divs["recent_closures"], "recent_closures", help_id="recent-closures-help", context=analytics.presentation)}
        {_chart_card(divs["backlog_trend"], "backlog_trend", help_id="backlog-trend-help", context=analytics.presentation)}
        {_chart_card(divs["age_trend"], "age_trend", help_id="age-trend-help", context=analytics.presentation)}
      </div>
    </section>

    <section class="dashboard-section" aria-labelledby="staff-title">
      <div class="section-heading">
        <span class="eyebrow">{html.escape(sections["staff"].eyebrow)}</span>
        <h2 class="section-title" id="staff-title">{html.escape(sections["staff"].title)}</h2>
        <p class="section-copy">{html.escape(sections["staff"].description or "")}</p>
      </div>
      <div class="chart-stack">
        {_chart_card(divs["submitted_by_workload"], "submitted_by_workload", help_id="submitted-by-workload-help", context=analytics.presentation)}
        {_chart_card(divs["submitted_by_date_activity"], "submitted_by_date_activity", help_id="submitted-by-date-help", context=analytics.presentation)}
      </div>
    </section>

    <section class="dashboard-section" aria-labelledby="exceptions-title">
      <div class="section-heading">
        <span class="eyebrow">{html.escape(sections["exceptions"].eyebrow)}</span>
        <h2 class="section-title" id="exceptions-title">{html.escape(sections["exceptions"].title)}</h2>
      </div>
      <div class="table-container" id="problem-rows-table">
        <div class="table-card-header">
          <div class="card-heading">
            <h2>{html.escape(observation_copy.title)}</h2>
            {_help_control(observation_copy.title, observation_copy.help_text, help_id="problem-rows-table-help")}
          </div>
        </div>
        <div class="table-scroll">{_table_html(analytics.exceptions)}</div>
        <div class="table-card-footer">
          <span class="table-summary">{html.escape(table_summary)}</span>
        </div>
      </div>
    </section>

    <footer class="page-footer">
      <a class="jump-to-top" href="#dashboard-top">{html.escape(page_copy.jump_to_top)}</a>
    </footer>
  </main>
  {export_script(_json_for_script)}
</body>
</html>
"""
    output_path.write_text(html_text, encoding="utf-8")
    return output_path
